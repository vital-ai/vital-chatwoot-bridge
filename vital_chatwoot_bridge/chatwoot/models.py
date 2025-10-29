"""
Chatwoot webhook and API data models.
"""

from datetime import datetime
from typing import Dict, Any, List, Optional, Literal
from pydantic import BaseModel, Field


class ChatwootAccount(BaseModel):
    """Chatwoot account object."""
    id: str = Field(..., description="Account ID as string")
    name: str = Field(..., description="Account name")


# Simplified webhook event models (what Chatwoot actually sends)
class ChatwootWebhookMessageData(BaseModel):
    """Chatwoot webhook message payload - matches official specification exactly."""
    event: str = Field(..., description="Event type (e.g., 'message_created')")
    id: str = Field(..., description="Message ID as string")
    content: str = Field(..., description="Message content")
    created_at: str = Field(..., description="Creation timestamp")
    message_type: str = Field(..., description="Message type (incoming/outgoing/template)")
    content_type: str = Field(default="text", description="Content type (text, input_select, cards, form)")
    content_attributes: Dict[str, Any] = Field(default_factory=dict, description="Content attributes object")
    source_id: Optional[str] = Field(default="", description="External ID for integrations")
    sender: Dict[str, Any] = Field(..., description="Sender details (agent or contact)")
    contact: Dict[str, Any] = Field(..., description="Contact details")
    conversation: Dict[str, Any] = Field(..., description="Conversation details with display_id")
    account: Dict[str, Any] = Field(..., description="Account details")

class ChatwootWebhookEvent(BaseModel):
    """Chatwoot webhook event - matches actual Chatwoot webhook payload structure."""
    event: str = Field(..., description="Event type (e.g., 'message_created')")
    id: int = Field(..., description="Message ID as integer")
    content: str = Field(..., description="Message content")
    created_at: str = Field(..., description="Creation timestamp")
    message_type: str = Field(..., description="Message type (incoming/outgoing/template)")
    content_type: str = Field(default="text", description="Content type (text, input_select, cards, form)")
    content_attributes: Dict[str, Any] = Field(default_factory=dict, description="Content attributes object")
    source_id: Optional[str] = Field(default="", description="External ID for integrations")
    sender: Dict[str, Any] = Field(..., description="Sender details (agent or contact)")
    conversation: Dict[str, Any] = Field(..., description="Conversation details with display_id")
    account: Dict[str, Any] = Field(..., description="Account details")
    inbox: Dict[str, Any] = Field(..., description="Inbox details")
    additional_attributes: Dict[str, Any] = Field(default_factory=dict, description="Additional attributes")
    private: bool = Field(default=False, description="Whether message is private")


class ChatwootInbox(BaseModel):
    """Chatwoot inbox object."""
    id: str = Field(..., description="Inbox ID as string")
    name: str = Field(..., description="Inbox name")


class ChatwootContact(BaseModel):
    """Chatwoot contact object."""
    id: str = Field(..., description="Contact ID as string")
    name: str = Field(..., description="Contact name")
    avatar: Optional[str] = Field(None, description="Contact avatar URL")
    type: Literal["contact"] = Field(default="contact", description="Object type")
    account: Optional[ChatwootAccount] = Field(None, description="Associated account")


class ChatwootUser(BaseModel):
    """Chatwoot user object."""
    id: str = Field(..., description="User ID as string")
    name: str = Field(..., description="User name")
    email: str = Field(..., description="User email")
    type: Literal["user"] = Field(default="user", description="Object type")


class ChatwootContactInbox(BaseModel):
    """Chatwoot contact inbox relationship."""
    id: str = Field(..., description="Contact inbox ID as string")
    contact_id: str = Field(..., description="Contact ID as string")
    inbox_id: str = Field(..., description="Inbox ID as string")
    source_id: str = Field(..., description="Source identifier")
    created_at: str = Field(..., description="Creation timestamp as ISO string")
    updated_at: str = Field(..., description="Update timestamp as ISO string")
    hmac_verified: bool = Field(default=False, description="HMAC verification status")


class ChatwootConversationMeta(BaseModel):
    """Conversation metadata."""
    sender: Optional[ChatwootContact] = Field(None, description="Message sender")
    assignee: Optional[ChatwootUser] = Field(None, description="Assigned user")


class ChatwootBrowserInfo(BaseModel):
    """Browser information from additional attributes."""
    device_name: Optional[str] = Field(None, description="Device name")
    browser_name: Optional[str] = Field(None, description="Browser name")
    platform_name: Optional[str] = Field(None, description="Platform name")
    browser_version: Optional[str] = Field(None, description="Browser version")
    platform_version: Optional[str] = Field(None, description="Platform version")


class ChatwootAdditionalAttributes(BaseModel):
    """Additional attributes for conversation."""
    browser: Optional[ChatwootBrowserInfo] = Field(None, description="Browser information")
    referer: Optional[str] = Field(None, description="Referer URL")
    initiated_at: Optional[Dict[str, Any]] = Field(None, description="Initiation timestamp")


class ChatwootConversation(BaseModel):
    """Chatwoot conversation object."""
    id: str = Field(..., description="Conversation ID as string")
    inbox_id: str = Field(..., description="Inbox ID as string")
    status: str = Field(..., description="Conversation status")
    channel: str = Field(..., description="Communication channel")
    can_reply: bool = Field(..., description="Whether replies are allowed")
    contact_inbox: ChatwootContactInbox = Field(..., description="Contact inbox relationship")
    messages: List[Dict[str, Any]] = Field(default=[], description="Conversation messages")
    meta: ChatwootConversationMeta = Field(..., description="Conversation metadata")
    additional_attributes: Optional[ChatwootAdditionalAttributes] = Field(None, description="Additional attributes")
    unread_count: int = Field(default=0, description="Unread message count")
    agent_last_seen_at: Optional[int] = Field(None, description="Agent last seen timestamp")
    contact_last_seen_at: Optional[int] = Field(None, description="Contact last seen timestamp")
    timestamp: int = Field(..., description="Conversation timestamp")
    account_id: str = Field(..., description="Account ID as string")


class ChatwootMessage(BaseModel):
    """Chatwoot message object."""
    id: str = Field(..., description="Message ID as string")
    content: str = Field(..., description="Message content")
    message_type: str = Field(..., description="Message type (incoming/outgoing)")
    created_at: str = Field(..., description="Creation timestamp (ISO format)")
    private: bool = Field(default=False, description="Whether message is private")
    source_id: Optional[str] = Field(None, description="Source identifier")
    content_type: str = Field(default="text", description="Content type")
    content_attributes: Dict[str, Any] = Field(default_factory=dict, description="Content attributes")
    sender: Dict[str, Any] = Field(..., description="Message sender")
    account: ChatwootAccount = Field(..., description="Associated account")
    conversation: ChatwootConversation = Field(..., description="Associated conversation")
    inbox: ChatwootInbox = Field(..., description="Associated inbox")


class ChatwootMessageCreatedEvent(BaseModel):
    """Message created webhook event."""
    event: Literal["message_created"] = Field(default="message_created")
    id: str = Field(..., description="Message ID as string")
    content: str = Field(..., description="Message content")
    message_type: str = Field(..., description="Message type as string")
    created_at: str = Field(..., description="Creation timestamp as ISO string")
    private: bool = Field(default=False, description="Whether message is private")
    source_id: Optional[str] = Field(None, description="Source identifier")
    content_type: str = Field(default="text", description="Content type")
    content_attributes: Dict[str, Any] = Field(default_factory=dict, description="Content attributes")
    sender: Dict[str, Any] = Field(..., description="Message sender")
    contact: Dict[str, Any] = Field(..., description="Contact details")
    account: ChatwootAccount = Field(..., description="Associated account")
    conversation: ChatwootConversation = Field(..., description="Associated conversation")
    inbox: ChatwootInbox = Field(..., description="Associated inbox")


class ChatwootConversationCreatedEvent(ChatwootWebhookEvent):
    """Conversation created webhook event."""
    event: Literal["conversation_created"] = Field(default="conversation_created")
    id: int = Field(..., description="Conversation ID")
    inbox_id: int = Field(..., description="Inbox ID")
    status: str = Field(..., description="Conversation status")
    channel: str = Field(..., description="Communication channel")
    can_reply: bool = Field(..., description="Whether replies are allowed")
    contact_inbox: ChatwootContactInbox = Field(..., description="Contact inbox relationship")
    messages: List[Dict[str, Any]] = Field(default=[], description="Conversation messages")
    meta: ChatwootConversationMeta = Field(..., description="Conversation metadata")
    additional_attributes: Optional[ChatwootAdditionalAttributes] = Field(None, description="Additional attributes")
    unread_count: int = Field(default=0, description="Unread message count")
    agent_last_seen_at: Optional[int] = Field(None, description="Agent last seen timestamp")
    contact_last_seen_at: Optional[int] = Field(None, description="Contact last seen timestamp")
    timestamp: int = Field(..., description="Conversation timestamp")
    account_id: int = Field(..., description="Account ID")


class ChatwootWebWidgetTriggeredEvent(ChatwootWebhookEvent):
    """Web widget triggered webhook event."""
    event: Literal["webwidget_triggered"] = Field(default="webwidget_triggered")
    id: str = Field(..., description="Event ID")
    contact: ChatwootContact = Field(..., description="Contact information")
    inbox: ChatwootInbox = Field(..., description="Inbox information")
    account: ChatwootAccount = Field(..., description="Account information")
    current_conversation: Optional[ChatwootConversation] = Field(None, description="Current conversation")
    source_id: str = Field(..., description="Source identifier")
    event_info: Dict[str, Any] = Field(..., description="Event information")


class ChatwootAPIMessageRequest(BaseModel):
    """Request model for creating messages via Chatwoot API."""
    content: str = Field(..., description="Message content")
    message_type: Literal["outgoing"] = Field(default="outgoing", description="Message type")
    private: bool = Field(default=False, description="Whether message is private")
    content_type: str = Field(default="text", description="Content type")
    content_attributes: Dict[str, Any] = Field(default_factory=dict, description="Content attributes")


class ChatwootAPIMessageResponse(BaseModel):
    """Response model from Chatwoot API when creating messages."""
    id: int = Field(..., description="Message ID")
    content: str = Field(..., description="Message content")
    account_id: Optional[int] = Field(None, description="Account ID")
    inbox_id: Optional[int] = Field(None, description="Inbox ID")
    conversation_id: Optional[int] = Field(None, description="Conversation ID")
    message_type: Optional[int] = Field(None, description="Message type")
    created_at: Optional[int] = Field(None, description="Creation timestamp")
    updated_at: Optional[int] = Field(None, description="Update timestamp")
    private: Optional[bool] = Field(None, description="Whether message is private")
    status: Optional[str] = Field(None, description="Message status")
    source_id: Optional[str] = Field(None, description="Source identifier")
    content_type: Optional[str] = Field(None, description="Content type")
    content_attributes: Optional[Dict[str, Any]] = Field(None, description="Content attributes")
    sender_type: Optional[str] = Field(None, description="Sender type")
    sender_id: Optional[int] = Field(None, description="Sender ID")
