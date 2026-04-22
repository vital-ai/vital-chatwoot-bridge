"""
Pydantic models for Chatwoot Management API endpoints.
Request/response models with standardized pagination envelope.
"""

from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field, model_validator


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


# ── Attachment models ────────────────────────────────────────────────

class AttachmentInput(BaseModel):
    """Attachment input for the post-message endpoint.

    Provide either `data` (base64-encoded content) or `url` (URL to fetch),
    but not both.
    """
    filename: str = Field(..., description="Original filename including extension")
    content_type: str = Field(default="application/octet-stream", description="MIME type")
    data: Optional[str] = Field(None, description="Base64-encoded file content")
    url: Optional[str] = Field(None, description="URL to fetch file content from")

    @model_validator(mode="after")
    def _require_data_or_url(self):
        if not self.data and not self.url:
            raise ValueError("Either 'data' (base64) or 'url' must be provided")
        if self.data and self.url:
            raise ValueError("Provide either 'data' or 'url', not both")
        return self


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
    subject: Optional[str] = Field(None, description="Email subject line (email inboxes only)")
    to_emails: Optional[str] = Field(None, description="Explicit email recipients, comma-separated (outbound only)")
    cc_emails: Optional[str] = Field(None, description="CC recipients, comma-separated (outbound only)")
    bcc_emails: Optional[str] = Field(None, description="BCC recipients, comma-separated (outbound only)")
    from_email: Optional[str] = Field(None, description="Sender address override (Mailgun html/template modes only)")
    attachments: Optional[List[AttachmentInput]] = Field(None, description="File attachments (base64 or URL)")
    content_attributes: Optional[Dict[str, Any]] = Field(None, description="Chatwoot content_attributes (e.g. email html_content)")
    content_mode: str = Field(
        default="text",
        description=(
            "How the message content is handled: "
            "'text' (plain text via Chatwoot), "
            "'markdown' (markdown via Chatwoot), "
            "'html' (raw HTML sent via Mailgun, recorded in Chatwoot), "
            "'template' (Jinja template rendered + sent via Mailgun, recorded in Chatwoot), "
            "'gmail_template' (Jinja template rendered + sent via Gmail API, recorded in Chatwoot)"
        ),
    )
    template_name: Optional[str] = Field(None, description="Jinja2 template name (required when content_mode='template' or 'gmail_template')")
    template_vars: Optional[Dict[str, Any]] = Field(None, description="Template variables (used when content_mode='template' or 'gmail_template')")
    # Gmail-specific fields (used when content_mode='gmail_template')
    gmail_sender: Optional[str] = Field(
        None,
        description="Sender email for Gmail delivery (must be in whitelist). Required when content_mode='gmail_template'.",
    )
    enable_open_tracking: bool = Field(
        default=False,
        description="Inject open-tracking pixel into rendered template. Only with content_mode='gmail_template'.",
    )
    enable_click_tracking: bool = Field(
        default=False,
        description="Wrap CTA link with click-tracking redirect. Only with content_mode='gmail_template'.",
    )
    cta_url: Optional[str] = Field(
        None,
        description="CTA destination URL (wrapped for click tracking). Only used when enable_click_tracking=True.",
    )
    campaign: Optional[str] = Field(
        None,
        description="Campaign tag for tracking (overrides config default).",
    )
    lead_id: Optional[str] = Field(
        None,
        description="Lead ID for tracking attribution.",
    )
