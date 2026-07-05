"""
Pydantic models for Zoom Phone SMS integration.
"""

import hashlib
from typing import Dict, List, Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Configuration models
# ---------------------------------------------------------------------------


class ZoomAccount(BaseModel):
    """A single Zoom Phone user account authorized for SMS sending."""
    zoom_user_id: str = Field(..., description="Zoom user ID (email or unique ID)")
    phone_number: str = Field(..., description="E.164 phone number assigned to this user")
    display_name: str = Field(default="", description="Human-readable name for this account")
    default_inbox_id: Optional[str] = Field(None, description="Chatwoot inbox ID for recording")
    enabled: bool = Field(default=True, description="Whether this account is active for sending")


class ZoomOAuthConfig(BaseModel):
    """OAuth app-level configuration (shared across all user accounts)."""
    client_id: str = Field(..., description="Zoom OAuth app client ID")
    client_secret: str = Field(..., description="Zoom OAuth app client secret")
    redirect_uri: str = Field(default="", description="OAuth callback URL (ngrok for initial auth)")


class ZoomTokenRefreshConfig(BaseModel):
    """Configuration for the background token refresh worker."""
    refresh_interval_minutes: int = Field(default=30, description="How often to check token expiry")
    refresh_buffer_minutes: int = Field(default=15, description="Refresh if token expires within this window")
    weekly_force_refresh: bool = Field(default=True, description="Force refresh all tokens weekly")


class ZoomTokenStorageConfig(BaseModel):
    """Configuration for token persistence."""
    backend: str = Field(default="secrets_manager", description="Storage backend: secrets_manager")
    secret_prefix: str = Field(
        default="vital-bridge/zoom-tokens/",
        description="Prefix for secrets in AWS Secrets Manager",
    )


class ZoomConfig(BaseModel):
    """Top-level Zoom Phone SMS configuration."""
    oauth: ZoomOAuthConfig = Field(..., description="OAuth app credentials")
    accounts: Dict[str, ZoomAccount] = Field(default_factory=dict, description="Named user accounts")
    token_storage: ZoomTokenStorageConfig = Field(
        default_factory=ZoomTokenStorageConfig, description="Token storage config"
    )
    token_refresh: ZoomTokenRefreshConfig = Field(
        default_factory=ZoomTokenRefreshConfig, description="Token refresh worker config"
    )


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------


class ZoomSmsSendRequest(BaseModel):
    """Request model for the POST /api/v1/inboxes/zoom/sms/send endpoint."""
    account: str = Field(..., description="Account name (key in zoom.accounts config)")
    to: str = Field(..., description="Recipient phone number in E.164 format")
    message: str = Field(..., description="SMS message text (max 500 characters)")


class ZoomSmsSendResponse(BaseModel):
    """Response from Zoom Phone SMS API after successful send."""
    message_id: str = Field(..., description="Zoom message ID")
    session_id: str = Field(..., description="Zoom session ID (perpetual per sender/recipient pair)")
    date_time: str = Field(..., description="Message creation time in UTC")


class ZoomTokenPair(BaseModel):
    """OAuth token pair stored in Secrets Manager."""
    access_token: str = Field(..., description="Current access token")
    refresh_token: str = Field(..., description="Current refresh token")
    expires_at: float = Field(..., description="Unix timestamp when access token expires")
    scope: str = Field(default="", description="Granted scopes")
    account_name: str = Field(default="", description="Account name this token belongs to")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def generate_session_id(sender_phone: str, recipient_phone: str) -> str:
    """
    Deterministic session ID from sender + recipient phone numbers.
    Same pair always produces the same session, maintaining Zoom thread continuity.
    MD5 hex digest = 32 chars, matches Zoom's session ID format.
    """
    key = f"{sender_phone}:{recipient_phone}"
    return hashlib.md5(key.encode()).hexdigest()
