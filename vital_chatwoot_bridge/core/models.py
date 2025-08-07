"""
Core data models for the Vital Chatwoot Bridge.
"""

from datetime import datetime
from typing import Dict, Any, Optional, Literal
from pydantic import BaseModel, Field
from enum import Enum


class ResponseMode(str, Enum):
    """Response mode for AI agent processing."""
    SYNC = "sync"
    ASYNC = "async"


class MessageSender(BaseModel):
    """Message sender information."""
    id: str = Field(..., description="Sender ID")
    name: str = Field(..., description="Sender name")
    email: Optional[str] = Field(None, description="Sender email")
    type: str = Field(default="contact", description="Sender type (contact/user)")


class MessageContext(BaseModel):
    """Context information for a message."""
    channel: str = Field(..., description="Communication channel")
    created_at: datetime = Field(..., description="Message creation timestamp")
    additional_attributes: Dict[str, Any] = Field(default_factory=dict, description="Additional context data")


class BridgeToAgentMessage(BaseModel):
    """Message format sent from bridge to AI agent."""
    message_id: str = Field(..., description="Unique message ID for correlation")
    inbox_id: str = Field(..., description="Chatwoot inbox identifier")
    conversation_id: str = Field(..., description="Chatwoot conversation ID")
    content: str = Field(..., description="Message content from customer")
    sender: MessageSender = Field(..., description="Message sender information")
    context: MessageContext = Field(..., description="Message context")
    response_mode: ResponseMode = Field(default=ResponseMode.SYNC, description="Expected response type")


class AgentResponseMetadata(BaseModel):
    """Metadata for AI agent response."""
    agent_id: str = Field(..., description="AI agent identifier")
    processing_time_ms: Optional[int] = Field(None, description="Processing time in milliseconds")
    confidence: Optional[float] = Field(None, description="Response confidence score")
    ai_model_version: Optional[str] = Field(None, description="AI model version used")


class AgentToBridgeMessage(BaseModel):
    """Message format sent from AI agent to bridge."""
    message_id: str = Field(..., description="Correlation ID matching original request")
    inbox_id: int = Field(..., description="Target inbox for routing")
    conversation_id: int = Field(..., description="Target conversation ID")
    content: str = Field(..., description="AI response content")
    response_type: ResponseMode = Field(..., description="Response handling mode")
    metadata: Optional[AgentResponseMetadata] = Field(None, description="Response metadata")


class WebhookResponse(BaseModel):
    """Response format for Chatwoot webhooks."""
    status: str = Field(..., description="Processing status")
    message: str = Field(..., description="Status message")
    data: Optional[Dict[str, Any]] = Field(None, description="Additional response data")


class ErrorResponse(BaseModel):
    """Error response format."""
    error: str = Field(..., description="Error message")
    error_code: str = Field(..., description="Error code")
    details: Optional[Dict[str, Any]] = Field(None, description="Additional error details")


class HealthStatus(BaseModel):
    """Health check response."""
    status: Literal["ok", "degraded", "error"] = Field(..., description="Service status")
    timestamp: datetime = Field(default_factory=datetime.utcnow, description="Status check timestamp")
    details: Optional[Dict[str, Any]] = Field(None, description="Additional status details")


class AgentConnectionStatus(BaseModel):
    """AI agent connection status."""
    agent_id: str = Field(..., description="AI agent identifier")
    websocket_url: str = Field(..., description="WebSocket URL")
    connected: bool = Field(..., description="Connection status")
    last_ping: Optional[datetime] = Field(None, description="Last ping timestamp")
    reconnect_attempts: int = Field(default=0, description="Number of reconnection attempts")
    error_message: Optional[str] = Field(None, description="Last error message")
