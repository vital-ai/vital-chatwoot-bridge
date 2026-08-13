"""
Response models for the GET /communications endpoint.
"""

from typing import Dict, List, Optional

from pydantic import BaseModel, Field


class CommunicationSender(BaseModel):
    name: str
    type: str  # "agent", "bot", "contact"


class CommunicationAttachment(BaseModel):
    """A file attached to a message.

    Mirrors Chatwoot's attachment payload. Note it carries no explicit filename
    or MIME type: `file_type` is a coarse category ("image", "file", "audio",
    "video"), and `filename` below is derived from the `data_url` basename.
    Callers needing a MIME type must map it from the filename extension.
    """
    id: int
    file_type: str
    filename: Optional[str] = None      # derived from data_url
    extension: Optional[str] = None
    file_size: Optional[int] = None
    data_url: Optional[str] = None
    thumb_url: Optional[str] = None
    width: Optional[int] = None
    height: Optional[int] = None


class CommunicationMessage(BaseModel):
    id: int
    # Raw Chatwoot message_type: 0=incoming, 1=outgoing, 2=activity, 3=template.
    # Exposed because `direction` cannot represent it: activity rows ("Conversation
    # was marked resolved by ...") are system events, not messages, and collapse
    # to "outbound" below. Consumers building a communications record almost
    # certainly want to skip message_type == 2.
    message_type: Optional[int] = None
    # Only meaningful for message_type 0/1. Anything else reports "outbound".
    direction: str  # "inbound" or "outbound"
    content: str
    content_type: str  # "text" or "html"
    channel: str  # "email", "sms", "imessage", "webchat"
    subject: Optional[str] = None  # email only
    sender: CommunicationSender
    private: bool = False
    created_at: str  # ISO 8601
    attachments: List[CommunicationAttachment] = Field(default_factory=list)


class CommunicationConversation(BaseModel):
    id: int
    inbox_id: int
    inbox_name: str
    channel: str
    status: str  # "open", "resolved", "pending"
    created_at: str
    messages: List[CommunicationMessage]
    # True when messages may have been omitted — more matched than the local cap
    # allows, or the upstream fetch stopped before exhausting the conversation
    # (Chatwoot serves 20 per page; see MAX_MESSAGE_PAGES). Without it a
    # truncated result is indistinguishable from a complete one.
    #
    # Conservative by design: a conversation holding exactly the page size, or
    # exactly the cap, reports True even though nothing was dropped. Ruling that
    # out costs an extra round trip per conversation. Treat True as "there may be
    # more", not "there is more"; False is exact.
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
    # True when the conversation cap bound, or any conversation reported
    # messages_truncated. Same conservatism as that flag: True means "there may
    # be more", False is exact. Compare conversations_available against
    # conversations_returned to see how much the conversation cap dropped.
    truncated: bool = False
    # Conversations matching the query before the cap was applied.
    conversations_available: Optional[int] = None
    conversations_returned: Optional[int] = None


class CommunicationsResponse(BaseModel):
    success: bool = True
    data: Dict  # {contact, conversations, summary}
