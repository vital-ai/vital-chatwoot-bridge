"""
Main entry point for the Vital Chatwoot Bridge FastAPI application.
"""

import asyncio
import logging
import os
import uvicorn
from contextlib import asynccontextmanager
from typing import Dict, Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware

# Load environment variables from .env file
from dotenv import load_dotenv
load_dotenv()

from vital_chatwoot_bridge.core.config import get_settings
from vital_chatwoot_bridge.api.routes import health_router
from vital_chatwoot_bridge.handlers.webhook_handler import WebhookHandler
from vital_chatwoot_bridge.agents.websocket_manager import WebSocketManager
from vital_chatwoot_bridge.chatwoot.api_client import get_chatwoot_client, close_chatwoot_client

# Configure logging using centralized utility
from vital_chatwoot_bridge.utils.logging_config import get_logger
logger = get_logger(__name__)

settings = get_settings()

# Global instances
websocket_manager: WebSocketManager = None
webhook_handler: WebhookHandler = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager."""
    global websocket_manager, webhook_handler
    
    logger.info("Starting Vital Chatwoot Bridge...")
    
    try:
        # Initialize WebSocket manager
        websocket_manager = WebSocketManager()
        await websocket_manager.start()
        
        # Initialize Chatwoot API client
        chatwoot_client = await get_chatwoot_client()
        
        # Initialize webhook handler
        webhook_handler = WebhookHandler(websocket_manager, chatwoot_client)
        
        # Health check
        api_healthy = await chatwoot_client.health_check()
        if api_healthy:
            logger.info("✅ Chatwoot API connection verified")
        else:
            logger.warning("⚠️  Chatwoot API connection failed - continuing anyway")
        
        logger.info("🚀 Vital Chatwoot Bridge started successfully")
        
        yield
        
    finally:
        logger.info("Shutting down Vital Chatwoot Bridge...")
        
        # Cleanup
        if websocket_manager:
            await websocket_manager.stop()
        
        await close_chatwoot_client()
        
        logger.info("✅ Vital Chatwoot Bridge shutdown complete")


app = FastAPI(
    title="Vital Chatwoot Bridge",
    description="Bridge service connecting Chatwoot with AI agents via WebSocket",
    version="1.0.0",
    lifespan=lifespan
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure appropriately for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.post("/webhook/chatwoot")
async def chatwoot_webhook(request: Request):
    """Handle incoming Chatwoot webhooks."""
    try:
        payload = await request.json()
        
        if not webhook_handler:
            raise HTTPException(status_code=503, detail="Webhook handler not initialized")
        
        response = await webhook_handler.handle_webhook(payload)
        return response
        
    except Exception as e:
        logger.error(f"Webhook processing error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Webhook processing failed: {str(e)}")


@app.get("/status")
async def get_status():
    """Get bridge service status."""
    try:
        status = {
            "service": "vital-chatwoot-bridge",
            "status": "running",
            "websocket_manager": "not_initialized",
            "agents": {},
            "chatwoot_api": "unknown"
        }
        
        if websocket_manager:
            status["websocket_manager"] = "running"
            status["agents"] = await websocket_manager.get_all_agent_status()
        
        # Check Chatwoot API
        try:
            chatwoot_client = await get_chatwoot_client()
            api_healthy = await chatwoot_client.health_check()
            status["chatwoot_api"] = "healthy" if api_healthy else "unhealthy"
        except Exception:
            status["chatwoot_api"] = "error"
        
        return status
        
    except Exception as e:
        logger.error(f"Status check error: {e}")
        raise HTTPException(status_code=500, detail=f"Status check failed: {str(e)}")


# Include API routes
app.include_router(health_router)


@app.on_event("startup")
async def startup_event():
    """Application startup event handler."""
    logger.info("🚀 Vital Chatwoot Bridge starting up...")


@app.on_event("shutdown")
async def shutdown_event():
    """Application shutdown event handler."""
    logger.info("🛑 Vital Chatwoot Bridge shutting down...")


def main():
    """Main entry point for running the application."""
    uvicorn.run(
        "vital_chatwoot_bridge.main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.debug,
        log_level="info" if not settings.debug else "debug",
    )


if __name__ == "__main__":
    main()
