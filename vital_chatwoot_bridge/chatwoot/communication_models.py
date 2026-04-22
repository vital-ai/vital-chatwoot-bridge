"""
Response models for the GET /communications endpoint.
"""

from typing import Dict, List, Optional

from pydantic import BaseModel, Field


class CommunicationSender(BaseModel):
    name: str
    type: str  # "agent", "bot", "contact"


class CommunicationMessage(BaseModel):
    id: int
    direction: str  # "inbound" or "outbound"
    content: str
    content_type: str  # "text" or "html"
    channel: str  # "email", "sms", "imessage", "webchat"
    subject: Optional[str] = None  # email only
    sender: CommunicationSender
    created_at: str  # ISO 8601


class CommunicationConversation(BaseModel):
    id: int
    inbox_id: int
    inbox_name: str
    channel: str
    status: str  # "open", "resolved", "pending"
    created_at: str
    messages: List[CommunicationMessage]


class CommunicationContact(BaseModel):
    id: int
    name: Optional[str] = None
    email: Optional[str] = None
    phone_number: Optional[str] = None


class CommunicationSummary(BaseModel):
    total_conversations: int
    total_messages: int
    channels: List[str]
    date_range: Dict[str, str]  # {"earliest": ..., "latest": ...}


class CommunicationsResponse(BaseModel):
    success: bool = True
    data: Dict  # {contact, conversations, summary}
