"""
Pydantic models for Chatwoot Client API operations.
These models handle the public API endpoints used for API inbox integrations.
"""

from typing import Dict, Any, Optional, List, Literal, Union
from datetime import datetime
from pydantic import BaseModel, Field, validator


class ChatwootContact(BaseModel):
    """Contact model for Chatwoot Client API."""
    identifier: str = Field(..., description="External identifier for the contact")
    name: Optional[str] = Field(None, description="Contact's display name")
    email: Optional[str] = Field(None, description="Contact's email address")
    phone_number: Optional[str] = Field(None, description="Contact's phone number")
    custom_attributes: Dict[str, Any] = Field(default_factory=dict, description="Custom contact attributes")
    
    @validator('identifier')
    def validate_identifier(cls, v):
        if not v or not v.strip():
            raise ValueError('Contact identifier cannot be empty')
        return v.strip()


class ChatwootContactResponse(BaseModel):
    """Response model for contact creation/retrieval."""
    id: int = Field(..., description="Chatwoot internal contact ID")
    source_id: str = Field(..., description="Contact identifier for subsequent API calls")
    name: Optional[str] = Field(None, description="Contact's display name")
    email: Optional[str] = Field(None, description="Contact's email address")
    pubsub_token: Optional[str] = Field(None, description="WebSocket token for real-time updates")


class ChatwootConversationRequest(BaseModel):
    """Request model for conversation creation."""
    custom_attributes: Dict[str, Any] = Field(default_factory=dict, description="Custom conversation attributes")


class ChatwootConversationResponse(BaseModel):
    """Response model for conversation creation."""
    id: int = Field(..., description="Conversation ID")
    inbox_id: Union[str, int] = Field(..., description="Inbox identifier")
    messages: List[Dict[str, Any]] = Field(default_factory=list, description="Initial messages in conversation")
    contact: Dict[str, Any] = Field(..., description="Associated contact information")


class ChatwootClientMessage(BaseModel):
    """Message model for Chatwoot Client API."""
    content: str = Field(..., description="Message content")
    message_type: Literal["incoming", "outgoing"] = Field(default="incoming", description="Message direction")
    echo_id: Optional[str] = Field(None, description="Temporary identifier for WebSocket responses")
    attachments: Optional[List[Dict[str, Any]]] = Field(None, description="Message attachments")
    
    @validator('content')
    def validate_content(cls, v):
        if not v or not v.strip():
            raise ValueError('Message content cannot be empty')
        return v.strip()


class ChatwootMessageResponse(BaseModel):
    """Response model for message creation."""
    id: Union[str, int] = Field(..., description="Message ID")
    content: str = Field(..., description="Message content")
    message_type: Union[str, int] = Field(..., description="Message type")
    content_type: Optional[str] = Field(None, description="Content type")
    created_at: Union[str, int] = Field(..., description="Creation timestamp")
    conversation_id: Union[str, int] = Field(..., description="Associated conversation ID")
    sender: Dict[str, Any] = Field(..., description="Sender information")
    attachments: List[Dict[str, Any]] = Field(default_factory=list, description="Message attachments")


class APIInboxMessageRequest(BaseModel):
    """Generic API inbox message request."""
    inbox_type: str = Field(..., description="Type of API inbox (loopmessage, attentive)")
    contact: ChatwootContact = Field(..., description="Contact information")
    message: ChatwootClientMessage = Field(..., description="Message content")
    conversation_id: Optional[str] = Field(None, description="Existing conversation ID if continuing thread")


# LoopMessage specific models
class LoopMessageContact(BaseModel):
    """Contact model for LoopMessage inbox."""
    phone_number: str = Field(..., description="Phone number for iMessage")
    name: Optional[str] = Field(None, description="Contact display name")
    
    @validator('phone_number')
    def validate_phone_number(cls, v):
        if not v or not v.strip():
            raise ValueError('Phone number is required for LoopMessage contacts')
        return v.strip()


class LoopMessageInboundRequest(BaseModel):
    """Inbound iMessage from LoopMessage app to Chatwoot."""
    contact: LoopMessageContact = Field(..., description="Contact information")
    message_content: str = Field(..., description="Message content")
    message_type: Literal["imessage"] = Field(default="imessage", description="Message type")
    conversation_id: Optional[str] = Field(None, description="Existing conversation ID")
    timestamp: Optional[datetime] = Field(None, description="Message timestamp")
    
    @validator('message_content')
    def validate_message_content(cls, v):
        if not v or not v.strip():
            raise ValueError('Message content cannot be empty')
        return v.strip()


class LoopMessageOutboundRequest(BaseModel):
    """Outbound iMessage from Chatwoot to LoopMessage."""
    phone_number: str = Field(..., description="Recipient phone number")
    message_content: str = Field(..., description="Message content")
    conversation_id: str = Field(..., description="Chatwoot conversation ID")
    chatwoot_message_id: str = Field(..., description="Chatwoot message ID")
    agent_name: Optional[str] = Field(None, description="Sending agent name")


# Attentive specific models
class AttentiveContact(BaseModel):
    """Contact model for Attentive inbox."""
    email: Optional[str] = Field(None, description="Contact email address")
    phone_number: Optional[str] = Field(None, description="Contact phone number")
    name: Optional[str] = Field(None, description="Contact display name")
    
    @validator('email', 'phone_number')
    def validate_contact_method(cls, v, values):
        # At least one contact method must be provided
        if not v and not values.get('email') and not values.get('phone_number'):
            raise ValueError('Either email or phone_number must be provided')
        return v


class AttentiveWebhookRequest(BaseModel):
    """Attentive webhook payload for message aggregation in Chatwoot."""
    type: Literal["sms.sent", "email.sent", "sms.inbound_message"] = Field(..., description="Webhook event type")
    timestamp: int = Field(..., description="Unix timestamp from Attentive")
    company: Union[str, Dict[str, Any]] = Field(..., description="Attentive company information (string or dict)")
    subscriber: Dict[str, Any] = Field(..., description="Contact information from Attentive")
    message: Dict[str, Any] = Field(..., description="Message content and metadata")
    
    # Optional fields that may be present in real Attentive webhooks
    client_id: Optional[str] = Field(None, description="Client identifier")
    subject: Optional[str] = Field(None, description="API subject/key")
    event_id: Optional[str] = Field(None, description="Event identifier")


class AttentiveEmailReplyRequest(BaseModel):
    """Email reply captured outside of Attentive webhooks."""
    contact: AttentiveContact = Field(..., description="Contact information")
    message_content: str = Field(..., description="Email reply content")
    subject: Optional[str] = Field(None, description="Email subject line")
    from_email: str = Field(..., description="Customer's email address")
    to_email: str = Field(..., description="Business email address that received the reply")
    reply_to_message_id: Optional[str] = Field(None, description="Reference to original Attentive email")
    timestamp: Optional[datetime] = Field(None, description="Email timestamp")
    email_headers: Optional[Dict[str, str]] = Field(None, description="Additional email metadata")
    
    @validator('message_content')
    def validate_message_content(cls, v):
        if not v or not v.strip():
            raise ValueError('Email content cannot be empty')
        return v.strip()


class AttentiveInboundRequest(BaseModel):
    """Processed Attentive message for Chatwoot aggregation."""
    contact: AttentiveContact = Field(..., description="Contact information")
    message_content: str = Field(..., description="Message content")
    message_type: Literal["email", "sms"] = Field(..., description="Message channel type")
    sender_type: Literal["business", "customer"] = Field(..., description="Message direction")
    attentive_event_type: str = Field(..., description="Original Attentive webhook event type")
    attentive_message_id: str = Field(..., description="Attentive's internal message ID")
    attentive_timestamp: int = Field(..., description="Original Attentive timestamp")
    campaign_info: Optional[Dict[str, Any]] = Field(None, description="Campaign details if available")
