"""
Main entry point for the Vital Chatwoot Bridge FastAPI application.
"""

import asyncio
import json
import logging
import os
import uvicorn
from contextlib import asynccontextmanager
from typing import Dict, Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware

# Load .env file in development (ECS injects env vars directly)
if os.getenv("CW_BRIDGE__app__environment") != "production":
    from dotenv import load_dotenv
    load_dotenv()

from vital_chatwoot_bridge.core.config import get_settings
from vital_chatwoot_bridge.api.routes import health_router
from vital_chatwoot_bridge.api.api_inbox_routes import api_inbox_router
from vital_chatwoot_bridge.api.chatwoot_management_routes import router as chatwoot_management_router
from vital_chatwoot_bridge.handlers.webhook_handler import WebhookHandler
from vital_chatwoot_bridge.chatwoot.api_client import get_chatwoot_client, close_chatwoot_client
from vital_chatwoot_bridge.utils.webhook_security import verify_webhook_signature, log_webhook_headers

# Configure logging using centralized utility
from vital_chatwoot_bridge.utils.logging_config import get_logger
logger = get_logger(__name__)

settings = get_settings()

# Global instances
webhook_handler: WebhookHandler = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager."""
    global webhook_handler
    
    logger.info("Starting Vital Chatwoot Bridge...")
    
    try:
        # Initialize Chatwoot API client
        chatwoot_client = await get_chatwoot_client()
        
        # Initialize webhook handler (now uses per-message WebSocket client)
        webhook_handler = WebhookHandler(chatwoot_client)
        
        # Health check
        api_healthy = await chatwoot_client.health_check()
        if api_healthy:
            logger.info("✅ Chatwoot API connection verified")
        else:
            logger.warning("⚠️  Chatwoot API connection failed - continuing anyway")
        
        # Initialize webhook worker pool for Attentive rate limiting
        from vital_chatwoot_bridge.services.webhook_queue import (
            create_queue, WebhookWorkerPool, set_worker_pool,
        )
        from vital_chatwoot_bridge.services.api_inbox_service import APIInboxService
        from vital_chatwoot_bridge.chatwoot.client_models import AttentiveWebhookRequest

        async def _attentive_queue_handler(raw_payload: dict) -> None:
            """Process a single Attentive webhook payload from the queue."""
            try:
                validated = AttentiveWebhookRequest(**raw_payload)
                svc = APIInboxService()
                await svc.process_attentive_webhook(validated)
            except Exception as exc:
                logger.error(f"❌ Queue handler error: {exc}", exc_info=True)

        try:
            queue = create_queue(
                backend=settings.rl_queue_backend,
                maxsize=settings.rl_attentive_queue_size,
                redis_url=settings.rl_redis_url,
                queue_key=settings.rl_redis_queue_key,
            )
            pool = WebhookWorkerPool(
                queue=queue,
                handler=_attentive_queue_handler,
                num_workers=settings.rl_attentive_workers,
            )
            pool.start()
            set_worker_pool(pool)
            logger.info(
                f"🚀 Webhook worker pool started — "
                f"backend={settings.rl_queue_backend}, "
                f"workers={settings.rl_attentive_workers}"
            )
        except Exception as e:
            logger.warning(f"⚠️  Webhook worker pool init failed: {e}")

        # Initialize email template renderer (if configured)
        if settings.email_templates:
            try:
                from vital_chatwoot_bridge.email.renderer import init_renderer
                init_renderer(
                    settings.email_templates,
                    aws_access_key_id=settings.aws_access_key_id,
                    aws_secret_access_key=settings.aws_secret_access_key,
                )
                logger.info("📧 Email template renderer initialized")
            except Exception as e:
                logger.warning(f"⚠️  Email template renderer init failed: {e}")
        
        logger.info("🚀 Vital Chatwoot Bridge started successfully")
        
        yield
        
    finally:
        logger.info("Shutting down Vital Chatwoot Bridge...")
        
        # Stop webhook worker pool
        from vital_chatwoot_bridge.services.webhook_queue import get_worker_pool as _gwp
        _pool = _gwp()
        if _pool is not None:
            await _pool.stop()
        
        # Cleanup
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
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.post("/webhook/chatwoot")
async def chatwoot_webhook(request: Request):
    """Handle incoming Chatwoot webhooks with signature verification."""
    try:
        # Get raw payload for signature verification
        raw_payload = await request.body()
        payload_str = raw_payload.decode('utf-8')
        
        # Log all webhook headers for debugging
        log_webhook_headers(dict(request.headers))
        
        # Get signature and timestamp headers
        signature = request.headers.get('X-Chatwoot-Signature')
        timestamp = request.headers.get('X-Chatwoot-Timestamp')
        
        # Parse JSON payload (needed to extract inbox_id for bot token lookup)
        try:
            payload = json.loads(payload_str) if payload_str else {}
        except json.JSONDecodeError as e:
            logger.error(f"🔐 WEBHOOK: Invalid JSON payload: {e}")
            raise HTTPException(status_code=400, detail="Invalid JSON payload")
        
        # Resolve the webhook secret: inbox_id → bot → access_token
        inbox_id = None
        conversation = payload.get("conversation", {})
        if isinstance(conversation, dict):
            inbox_id = str(conversation.get("inbox_id", ""))
        
        webhook_secret = ""
        if inbox_id:
            webhook_secret = settings.get_webhook_secret_for_inbox(inbox_id) or ""
        
        if not webhook_secret and settings.enforce_webhook_signatures:
            logger.error(f"🔐 WEBHOOK: No bot token configured for inbox {inbox_id}")
            raise HTTPException(status_code=401, detail=f"No bot token for inbox {inbox_id}")
        
        # Verify webhook signature with the resolved bot token
        is_valid = verify_webhook_signature(
            payload=payload_str,
            signature=signature,
            timestamp=timestamp,
            webhook_secret=webhook_secret,
            enforce_signatures=settings.enforce_webhook_signatures
        )
        
        if not is_valid:
            logger.error("🔐 WEBHOOK: Signature verification failed - rejecting webhook")
            raise HTTPException(status_code=401, detail="Invalid webhook signature")
        
        if not webhook_handler:
            raise HTTPException(status_code=503, detail="Webhook handler not initialized")
        
        response = await webhook_handler.handle_webhook(payload)
        return response
        
    except HTTPException:
        # Re-raise HTTP exceptions as-is
        raise
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
            "websocket_client": "per_message",
            "chatwoot_api": "unknown"
        }
        
        # Check Chatwoot API
        try:
            chatwoot_client = await get_chatwoot_client()
            api_healthy = await chatwoot_client.health_check()
            status["chatwoot_api"] = "healthy" if api_healthy else "unhealthy"
        except Exception:
            status["chatwoot_api"] = "error"

        # Webhook worker pool stats
        from vital_chatwoot_bridge.services.webhook_queue import get_worker_pool as _gwp
        _pool = _gwp()
        if _pool is not None:
            status["webhook_queue"] = await _pool.stats()
        else:
            status["webhook_queue"] = {"running": False}

        # Contact cache stats
        try:
            from vital_chatwoot_bridge.chatwoot.contact_cache import get_contact_cache
            status["contact_cache"] = get_contact_cache().stats()
        except Exception:
            pass
        
        return status
        
    except Exception as e:
        logger.error(f"Status check error: {e}")
        raise HTTPException(status_code=500, detail=f"Status check failed: {str(e)}")


# Include API routes
app.include_router(health_router)
app.include_router(api_inbox_router)
app.include_router(chatwoot_management_router)


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
