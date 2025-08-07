"""
API routes for the Vital Chatwoot Bridge application.
"""

from typing import Dict, Any
from fastapi import APIRouter
from pydantic import BaseModel

# Health check router
health_router = APIRouter()


class HealthResponse(BaseModel):
    """Health check response model."""
    status: str


@health_router.get("/health", response_model=HealthResponse)
async def health_check() -> HealthResponse:
    """
    Health check endpoint.
    
    Returns:
        HealthResponse: Status indicating the service is healthy.
    """
    return HealthResponse(status="ok")
