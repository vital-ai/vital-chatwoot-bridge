"""
Pydantic models for Chatwoot Management API endpoints.
Request/response models with standardized pagination envelope.
"""

from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


# ── Pagination envelope ──────────────────────────────────────────────

class PaginationMeta(BaseModel):
    """Pagination metadata."""
    page: int = Field(..., description="Current page number")
    per_page: int = Field(default=25, description="Items per page")
    total_count: Optional[int] = Field(None, description="Total number of items")
    total_pages: Optional[int] = Field(None, description="Total number of pages")


class PaginatedResponse(BaseModel):
    """Standardized paginated response envelope."""
    success: bool = Field(default=True)
    data: Any = Field(..., description="Response payload")
    meta: Optional[PaginationMeta] = Field(None, description="Pagination metadata")


class SingleResponse(BaseModel):
    """Standardized single-item response envelope."""
    success: bool = Field(default=True)
    data: Any = Field(..., description="Response payload")


class ErrorResponse(BaseModel):
    """Standardized error response."""
    success: bool = Field(default=False)
    error: str = Field(..., description="Error message")
    detail: Optional[str] = Field(None, description="Detailed error information")


# ── Contact models ───────────────────────────────────────────────────

class CreateContactRequest(BaseModel):
    """Request model for creating a contact."""
    name: str = Field(..., description="Contact name")
    email: Optional[str] = Field(None, description="Contact email")
    phone_number: Optional[str] = Field(None, description="Contact phone number")
    identifier: Optional[str] = Field(None, description="Custom external identifier")
    inbox_id: Optional[int] = Field(None, description="Inbox ID to associate with")
    custom_attributes: Optional[Dict[str, Any]] = Field(None, description="Custom attributes")


class UpdateContactRequest(BaseModel):
    """Request model for updating a contact."""
    name: Optional[str] = Field(None, description="Contact name")
    email: Optional[str] = Field(None, description="Contact email")
    phone_number: Optional[str] = Field(None, description="Contact phone number")
    identifier: Optional[str] = Field(None, description="Custom external identifier")
    custom_attributes: Optional[Dict[str, Any]] = Field(None, description="Custom attributes")


class MergeContactsRequest(BaseModel):
    """Request model for merging two contacts."""
    base_contact_id: int = Field(..., description="The contact to keep (merge target)")
    mergee_contact_id: int = Field(..., description="The contact to merge into base (will be removed)")


# ── Conversation models ──────────────────────────────────────────────

class CreateConversationRequest(BaseModel):
    """Request model for creating a conversation."""
    inbox_id: int = Field(..., description="Inbox ID")
    contact_id: int = Field(..., description="Contact ID")
    source_id: Optional[str] = Field(None, description="Source ID for the conversation")
    custom_attributes: Optional[Dict[str, Any]] = Field(None, description="Custom attributes")


class UpdateConversationRequest(BaseModel):
    """Request model for updating a conversation."""
    status: Optional[str] = Field(None, description="Conversation status: open, resolved, pending")
    assignee_id: Optional[int] = Field(None, description="Agent ID to assign conversation to")
    team_id: Optional[int] = Field(None, description="Team ID to assign conversation to")
    label: Optional[str] = Field(None, description="Label to add")
    custom_attributes: Optional[Dict[str, Any]] = Field(None, description="Custom attributes")


# ── Message models ───────────────────────────────────────────────────

class PostMessageContact(BaseModel):
    """Contact info for the post-message endpoint."""
    identifier: str = Field(..., description="Unique contact ID (phone or email)")
    name: Optional[str] = Field(None, description="Display name")
    email: Optional[str] = Field(None, description="Contact email")
    phone_number: Optional[str] = Field(None, description="Contact phone number")


class PostMessageContent(BaseModel):
    """Message content for the post-message endpoint."""
    content: str = Field(..., description="Message body text")
    content_type: str = Field(default="text", description="'text' or 'html'")


class PostMessageRequest(BaseModel):
    """Request model for the unified POST /messages endpoint."""
    direction: str = Field(..., description="'inbound' or 'outbound'")
    inbox_id: int = Field(..., description="Inbox ID")
    contact: PostMessageContact = Field(..., description="Contact information")
    message: PostMessageContent = Field(..., description="Message content")
    conversation_id: Optional[int] = Field(None, description="Explicit conversation ID (overrides conversation_mode)")
    conversation_mode: str = Field(
        default="reuse_newest",
        description="'reuse_newest' (default): reuse most recent open conversation; 'create_new': always create a new conversation",
    )
    suppress_delivery: bool = Field(default=False, description="Log only, do not dispatch (outbound only)")
    to_emails: Optional[str] = Field(None, description="Explicit email recipients, comma-separated (outbound only)")
    cc_emails: Optional[str] = Field(None, description="CC recipients, comma-separated (outbound only)")
    bcc_emails: Optional[str] = Field(None, description="BCC recipients, comma-separated (outbound only)")
