"""
AI agent data models and WebSocket message formats.
"""

from datetime import datetime
from typing import Dict, Any, Optional, List
from pydantic import BaseModel, Field
from enum import Enum

from vital_chatwoot_bridge.core.models import ResponseMode, AgentResponseMetadata


class AgentStatus(str, Enum):
    """AI agent connection status."""
    CONNECTED = "connected"
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    ERROR = "error"


class WebSocketMessageType(str, Enum):
    """WebSocket message types."""
    CHAT_MESSAGE = "chat_message"
    PING = "ping"
    PONG = "pong"
    ERROR = "error"
    STATUS = "status"


class WebSocketMessage(BaseModel):
    """Base WebSocket message format."""
    type: WebSocketMessageType = Field(..., description="Message type")
    timestamp: datetime = Field(default_factory=datetime.utcnow, description="Message timestamp")
    data: Dict[str, Any] = Field(default_factory=dict, description="Message data")


class AgentChatRequest(BaseModel):
    """Chat request sent to AI agent via WebSocket."""
    message_id: str = Field(..., description="Unique message ID for correlation")
    inbox_id: str = Field(..., description="Chatwoot inbox identifier")
    conversation_id: int = Field(..., description="Chatwoot conversation ID")
    content: str = Field(..., description="Customer message content")
    sender: Dict[str, Any] = Field(..., description="Message sender information")
    context: Dict[str, Any] = Field(default_factory=dict, description="Message context")
    response_mode: ResponseMode = Field(default=ResponseMode.SYNC, description="Expected response type")
    timeout_seconds: int = Field(default=30, description="Response timeout")


class AgentChatResponse(BaseModel):
    """Chat response received from AI agent via WebSocket."""
    message_id: str = Field(..., description="Correlation ID matching original request")
    inbox_id: str = Field(..., description="Target inbox for routing")
    conversation_id: int = Field(..., description="Target conversation ID")
    content: str = Field(..., description="AI response content")
    response_type: ResponseMode = Field(..., description="Response handling mode")
    metadata: Optional[AgentResponseMetadata] = Field(None, description="Response metadata")
    success: bool = Field(default=True, description="Whether response was successful")
    error_message: Optional[str] = Field(None, description="Error message if unsuccessful")


class AgentPingMessage(BaseModel):
    """Ping message for WebSocket health check."""
    agent_id: str = Field(..., description="AI agent identifier")
    timestamp: datetime = Field(default_factory=datetime.utcnow, description="Ping timestamp")


class AgentPongMessage(BaseModel):
    """Pong response for WebSocket health check."""
    agent_id: str = Field(..., description="AI agent identifier")
    timestamp: datetime = Field(default_factory=datetime.utcnow, description="Pong timestamp")
    ping_timestamp: datetime = Field(..., description="Original ping timestamp")


class AgentStatusMessage(BaseModel):
    """Status message from AI agent."""
    agent_id: str = Field(..., description="AI agent identifier")
    status: AgentStatus = Field(..., description="Current agent status")
    capabilities: List[str] = Field(default=[], description="Agent capabilities")
    load_info: Optional[Dict[str, Any]] = Field(None, description="Agent load information")
    version: Optional[str] = Field(None, description="Agent version")


class AgentErrorMessage(BaseModel):
    """Error message from AI agent."""
    agent_id: str = Field(..., description="AI agent identifier")
    error_code: str = Field(..., description="Error code")
    error_message: str = Field(..., description="Error description")
    context: Optional[Dict[str, Any]] = Field(None, description="Error context")
    recoverable: bool = Field(default=True, description="Whether error is recoverable")


class AgentConnectionInfo(BaseModel):
    """Information about AI agent connection."""
    agent_id: str = Field(..., description="AI agent identifier")
    websocket_url: str = Field(..., description="WebSocket URL")
    status: AgentStatus = Field(..., description="Connection status")
    connected_at: Optional[datetime] = Field(None, description="Connection timestamp")
    last_ping: Optional[datetime] = Field(None, description="Last ping timestamp")
    last_pong: Optional[datetime] = Field(None, description="Last pong timestamp")
    reconnect_attempts: int = Field(default=0, description="Number of reconnection attempts")
    error_count: int = Field(default=0, description="Number of errors encountered")
    last_error: Optional[str] = Field(None, description="Last error message")
    message_count: int = Field(default=0, description="Number of messages processed")
    average_response_time: Optional[float] = Field(None, description="Average response time in seconds")


class MockAgentBehavior(str, Enum):
    """Mock agent behavior modes."""
    ECHO = "echo"
    TEST = "test"
    DELAY = "delay"
    ERROR = "error"
    RANDOM = "random"


class MockAgentConfig(BaseModel):
    """Configuration for mock AI agent."""
    agent_id: str = Field(..., description="Mock agent identifier")
    behavior: MockAgentBehavior = Field(default=MockAgentBehavior.ECHO, description="Agent behavior mode")
    delay_seconds: int = Field(default=5, description="Delay for delay behavior")
    error_rate: float = Field(default=0.1, description="Error rate for random behavior")
    response_templates: Dict[str, str] = Field(default_factory=dict, description="Response templates for test behavior")


class MockAgentResponse(BaseModel):
    """Response from mock AI agent."""
    content: str = Field(..., description="Mock response content")
    processing_time_ms: int = Field(..., description="Simulated processing time")
    behavior_used: MockAgentBehavior = Field(..., description="Behavior mode used")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Additional metadata")
