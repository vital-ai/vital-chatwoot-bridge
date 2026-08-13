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
    private: bool = False
    created_at: str  # ISO 8601


class CommunicationConversation(BaseModel):
    id: int
    inbox_id: int
    inbox_name: str
    channel: str
    status: str  # "open", "resolved", "pending"
    created_at: str
    messages: List[CommunicationMessage]
    # True when this conversation held more matching messages than the per
    # conversation cap. Without it a truncated result is indistinguishable
    # from a complete one.
    messages_truncated: bool = False


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
    # Truncation is bounded but not always avoidable, so report it rather than
    # letting a partial result look complete.
    truncated: bool = False
    # Conversations matching the query before the cap was applied.
    conversations_available: Optional[int] = None
    conversations_returned: Optional[int] = None


class CommunicationsResponse(BaseModel):
    success: bool = True
    data: Dict  # {contact, conversations, summary}
