"""
Pydantic models for the email template system.
"""

from typing import Dict, Optional
from pydantic import BaseModel, Field


class MailgunConfig(BaseModel):
    """Mailgun API configuration."""
    api_key: str = Field(..., description="Mailgun API key")
    domain: str = Field(..., description="Mailgun sending domain (e.g. mg.example.com)")
    from_email: str = Field(default="", description="Default sender address")
    base_url: str = Field(default="https://api.mailgun.net/v3", description="Mailgun API base URL")


class EmailTemplateDef(BaseModel):
    """Definition of a single email template."""
    s3_key: str = Field(..., description="S3 object key for the .html.j2 file")
    subject_default: str = Field(default="", description="Jinja-rendered default subject line")
    description: str = Field(default="", description="Human-readable template description")


class EmailTemplatesConfig(BaseModel):
    """Email template system configuration."""
    s3_bucket: str = Field(..., description="S3 bucket containing template files")
    s3_region: str = Field(default="us-east-1", description="AWS region for the bucket")
    asset_base_url: str = Field(default="", description="CloudFront URL prefix for template assets")
    defaults: Dict[str, str] = Field(default_factory=dict, description="Default template variables")
    templates: Dict[str, EmailTemplateDef] = Field(default_factory=dict, description="Named template definitions")


class MailgunSendEmailRequest(BaseModel):
    """Request model for the POST /api/v1/inboxes/mailgun/email/send endpoint."""
    to: str = Field(..., description="Recipient email address")
    subject: str = Field(..., description="Email subject line")
    text: Optional[str] = Field(None, description="Plain text email body")
    html: Optional[str] = Field(None, description="HTML email body")
    from_email: Optional[str] = Field(None, description="Sender address (overrides config default)")
    cc: Optional[str] = Field(None, description="CC addresses, comma-separated")
    bcc: Optional[str] = Field(None, description="BCC addresses, comma-separated")
    reply_to: Optional[str] = Field(None, description="Reply-to address")


# ---------------------------------------------------------------------------
# Gmail / Google Workspace
# ---------------------------------------------------------------------------


class GmailSender(BaseModel):
    """A whitelisted sender identity for Gmail impersonation."""
    email: str = Field(..., description="Sender email address (domain user to impersonate)")
    display_name: str = Field(default="", description="Sender display name (e.g. 'Jordan Lane')")
    reply_to: str = Field(default="", description="Reply-to address (defaults to sender email)")
    default_inbox_id: Optional[int] = Field(None, description="Chatwoot inbox ID for recording sent emails")


class GmailTrackingConfig(BaseModel):
    """Configuration for open/click tracking in Gmail-sent emails."""
    pixel_url: str = Field(default="", description="Open-tracking pixel endpoint URL")
    click_url: str = Field(default="", description="Click-tracking redirect endpoint URL")
    default_campaign: str = Field(default="", description="Default campaign identifier")


class GmailConfig(BaseModel):
    """Gmail API configuration using service account domain-wide delegation."""
    service_account_info: Dict = Field(..., description="Parsed service account key JSON")
    senders: Dict[str, GmailSender] = Field(default_factory=dict, description="Whitelisted sender identities")
    tracking: GmailTrackingConfig = Field(default_factory=GmailTrackingConfig, description="Tracking config")


class GmailSendEmailRequest(BaseModel):
    """Request model for the POST /api/v1/inboxes/gmail/email/send endpoint."""
    sender: str = Field(..., description="Sender email (must be in allowed senders whitelist)")
    to: str = Field(..., description="Recipient email address")
    subject: str = Field(..., description="Email subject line")
    html: Optional[str] = Field(None, description="HTML email body")
    text: Optional[str] = Field(None, description="Plain text email body")
    cc: Optional[str] = Field(None, description="CC addresses, comma-separated")
    bcc: Optional[str] = Field(None, description="BCC addresses, comma-separated")


class SendTemplatedEmailRequest(BaseModel):
    """Request model for the send_templated_email endpoint."""
    template_name: str = Field(..., description="Name of the template to render")
    to: str = Field(..., description="Recipient email address")
    subject: Optional[str] = Field(None, description="Subject line (overrides template default)")
    cc: Optional[str] = Field(None, description="CC addresses, comma-separated")
    bcc: Optional[str] = Field(None, description="BCC addresses, comma-separated")
    inbox_id: int = Field(..., description="Chatwoot email inbox ID")
    contact_name: Optional[str] = Field(None, description="Display name for the contact")
    template_vars: Dict[str, str] = Field(default_factory=dict, description="Variables to pass to the Jinja template")
    suppress_delivery: bool = Field(default=False, description="Log only, do not dispatch")
