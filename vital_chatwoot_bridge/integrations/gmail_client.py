"""
Gmail API Client for sending emails via Google Workspace service account
with domain-wide delegation.

Thin send-only client — Follows the same structure as MailgunClient.
"""

import asyncio
import base64
import logging
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Any, Dict, Optional

import httpx
from google.auth.transport.requests import Request
from google.oauth2 import service_account

from vital_chatwoot_bridge.email.models import GmailConfig, GmailSender

logger = logging.getLogger(__name__)

GMAIL_SEND_SCOPE = "https://www.googleapis.com/auth/gmail.send"
GMAIL_BASE = "https://gmail.googleapis.com/gmail/v1"


class GmailClientError(Exception):
    """Exception raised for Gmail API errors."""

    def __init__(
        self,
        message: str,
        status_code: Optional[int] = None,
        response_data: Optional[Dict] = None,
    ):
        super().__init__(message)
        self.status_code = status_code
        self.response_data = response_data


class GmailClient:
    """
    Thin Gmail send client using service account domain-wide delegation.

    Impersonates whitelisted domain users to send emails via the Gmail API.
    Tokens are transient (not cached) — ~50ms per token exchange.
    """

    def __init__(self, config: GmailConfig):
        self.config = config
        self._client = httpx.AsyncClient(
            timeout=30.0,
            transport=httpx.AsyncHTTPTransport(retries=2),
        )

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self._client.aclose()

    # ------------------------------------------------------------------ #
    # Sender whitelist
    # ------------------------------------------------------------------ #

    def get_sender(self, sender_email: str) -> GmailSender:
        """Look up sender in whitelist; raise GmailClientError if not allowed."""
        for sender in self.config.senders.values():
            if sender.email == sender_email:
                return sender
        raise GmailClientError(
            f"Sender not in whitelist: {sender_email}",
            status_code=403,
        )

    # ------------------------------------------------------------------ #
    # Authentication
    # ------------------------------------------------------------------ #

    def _get_send_token(self, sender_email: str) -> str:
        """
        Get a transient OAuth2 token for impersonating sender_email.

        Borrowed from reference client _get_user_token().
        JWT sign + token exchange (~50ms), not cached.
        """
        creds = service_account.Credentials.from_service_account_info(
            self.config.service_account_info,
            scopes=[GMAIL_SEND_SCOPE],
        ).with_subject(sender_email)
        creds.refresh(Request())
        return creds.token

    # ------------------------------------------------------------------ #
    # MIME building
    # ------------------------------------------------------------------ #

    def _build_mime(
        self,
        sender: GmailSender,
        to: str,
        subject: str,
        html: str,
        text: Optional[str] = None,
        cc: Optional[str] = None,
        bcc: Optional[str] = None,
    ) -> str:
        """
        Build a MIME multipart/alternative message and return base64url-encoded.

        Uses email.mime stdlib — same approach as the proven test script.
        """
        msg = MIMEMultipart("alternative")

        # From header with display name
        if sender.display_name:
            msg["From"] = f"{sender.display_name} <{sender.email}>"
        else:
            msg["From"] = sender.email

        msg["To"] = to
        msg["Subject"] = subject

        if cc:
            msg["Cc"] = cc
        if bcc:
            msg["Bcc"] = bcc

        reply_to = sender.reply_to or sender.email
        if reply_to:
            msg["Reply-To"] = reply_to

        # Text part (fallback)
        if text:
            msg.attach(MIMEText(text, "plain", "utf-8"))
        else:
            # Auto-generate plain text fallback
            msg.attach(MIMEText(subject, "plain", "utf-8"))

        # HTML part
        msg.attach(MIMEText(html, "html", "utf-8"))

        # Base64url encode for Gmail API
        raw = base64.urlsafe_b64encode(msg.as_bytes()).decode("ascii")
        return raw

    # ------------------------------------------------------------------ #
    # Gmail API request with retry
    # ------------------------------------------------------------------ #

    async def _gmail_send_request(
        self,
        sender_email: str,
        raw_message: str,
    ) -> Dict[str, Any]:
        """
        POST to Gmail API /users/me/messages/send with retry.

        Retry logic borrowed from reference client _gmail_request():
        - 429 → respect Retry-After
        - 401 → re-auth (get fresh token)
        - 5xx → exponential backoff
        """
        token = self._get_send_token(sender_email)
        url = f"{GMAIL_BASE}/users/me/messages/send"
        headers = {"Authorization": f"Bearer {token}"}
        body = {"raw": raw_message}

        max_retries = 3
        for attempt in range(max_retries):
            resp = await self._client.post(url, headers=headers, json=body)

            if resp.status_code == 200:
                return resp.json()

            # Rate limited
            if resp.status_code == 429:
                retry_after = int(resp.headers.get("Retry-After", 2))
                logger.warning(
                    "Gmail rate limited for %s, retry after %ds",
                    sender_email, retry_after,
                )
                await asyncio.sleep(retry_after)
                continue

            # Token expired — get fresh transient token
            if resp.status_code == 401:
                logger.info("Gmail 401 for %s, refreshing token", sender_email)
                token = self._get_send_token(sender_email)
                headers["Authorization"] = f"Bearer {token}"
                continue

            # 5xx — retry with exponential backoff
            if resp.status_code >= 500 and attempt < max_retries - 1:
                delay = 2 ** attempt
                logger.warning(
                    "Gmail %d for %s, retrying in %ds (attempt %d/%d)",
                    resp.status_code, sender_email, delay, attempt + 1, max_retries,
                )
                await asyncio.sleep(delay)
                continue

            # Non-retryable error
            error_data = None
            try:
                error_data = resp.json()
            except Exception:
                pass

            error_msg = "Unknown error"
            if error_data and "error" in error_data:
                err = error_data["error"]
                error_msg = err.get("message", str(err))
            elif resp.text:
                error_msg = resp.text[:200]

            raise GmailClientError(
                f"Gmail API error (HTTP {resp.status_code}): {error_msg}",
                status_code=resp.status_code,
                response_data=error_data,
            )

        raise GmailClientError(
            f"Gmail API request failed after {max_retries} retries",
            status_code=None,
        )

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #

    async def send_email(
        self,
        sender_email: str,
        to: str,
        subject: str,
        html: str,
        text: Optional[str] = None,
        cc: Optional[str] = None,
        bcc: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Send an email via Gmail API, impersonating sender_email.

        Args:
            sender_email: Must be in allowed_senders whitelist
            to: Recipient email address
            subject: Email subject line
            html: HTML email body
            text: Plain text fallback (auto-generated if not provided)
            cc: CC addresses, comma-separated
            bcc: BCC addresses, comma-separated

        Returns:
            Gmail API response: {id, threadId, labelIds}

        Raises:
            GmailClientError: If sender not whitelisted or API request fails
        """
        if not html:
            raise GmailClientError("html body is required")

        # Validate sender is whitelisted
        sender = self.get_sender(sender_email)

        logger.info(f"📧 Sending email via Gmail as {sender_email} to: {to}, subject: {subject}")

        # Build MIME message
        raw_message = self._build_mime(
            sender=sender,
            to=to,
            subject=subject,
            html=html,
            text=text,
            cc=cc,
            bcc=bcc,
        )

        # Send via Gmail API
        try:
            result = await self._gmail_send_request(sender_email, raw_message)
            logger.info(
                f"✅ Gmail email sent: id={result.get('id')}, "
                f"threadId={result.get('threadId')}"
            )
            return result
        except GmailClientError:
            raise
        except httpx.RequestError as e:
            raise GmailClientError(f"Network error contacting Gmail API: {e}")
        except Exception as e:
            raise GmailClientError(f"Unexpected error sending email via Gmail: {e}")

    async def close(self):
        """Close the underlying HTTP client."""
        await self._client.aclose()
