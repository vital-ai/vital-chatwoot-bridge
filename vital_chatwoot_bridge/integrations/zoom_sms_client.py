"""
Thin Zoom Phone SMS send client.

Sends SMS via Zoom Phone API and handles:
- Message length validation (500 char max)
- Automatic token refresh on 401
- Rate limit handling (429 with Retry-After)
- Deterministic session IDs for conversation continuity
"""

import logging
from typing import Dict, Optional

import httpx

from vital_chatwoot_bridge.zoom.models import (
    ZoomConfig, ZoomAccount, ZoomSmsSendResponse, generate_session_id,
)
from vital_chatwoot_bridge.zoom.oauth import ZoomOAuthManager, ZoomOAuthError

logger = logging.getLogger(__name__)

ZOOM_SMS_URL = "https://api.zoom.us/v2/phone/sms/messages"
MAX_MESSAGE_LENGTH = 500


class ZoomSmsError(Exception):
    """Exception raised for Zoom SMS API errors."""

    def __init__(
        self,
        message: str,
        status_code: Optional[int] = None,
        error_code: Optional[int] = None,
        response_data: Optional[Dict] = None,
    ):
        super().__init__(message)
        self.status_code = status_code
        self.error_code = error_code
        self.response_data = response_data


class ZoomSmsClient:
    """
    Sends SMS messages via the Zoom Phone API.

    Usage:
        async with ZoomSmsClient(config, oauth_manager) as client:
            result = await client.send_sms("sales1", "+15559876543", "Hello!")
    """

    def __init__(self, config: ZoomConfig, oauth_manager: ZoomOAuthManager):
        self.config = config
        self.oauth_manager = oauth_manager
        self._http = httpx.AsyncClient(
            timeout=30.0,
            transport=httpx.AsyncHTTPTransport(retries=2),
        )

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self._http.aclose()

    async def close(self):
        await self._http.aclose()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def send_sms(
        self,
        account_name: str,
        to: str,
        message: str,
        session_id: Optional[str] = None,
    ) -> ZoomSmsSendResponse:
        """
        Send an SMS via Zoom Phone.

        Args:
            account_name: Key in config.accounts identifying the sender
            to: Recipient phone number in E.164 format
            message: SMS text (max 500 chars)
            session_id: Optional explicit session ID (defaults to deterministic hash)

        Returns:
            ZoomSmsSendResponse with message_id, session_id, date_time

        Raises:
            ZoomSmsError: On validation failure or API error
        """
        # Validate account exists and is enabled
        account = self._get_account(account_name)

        # Validate message length
        if len(message) > MAX_MESSAGE_LENGTH:
            raise ZoomSmsError(
                f"Message length ({len(message)}) exceeds maximum of "
                f"{MAX_MESSAGE_LENGTH} characters",
                status_code=400,
            )
        if not message.strip():
            raise ZoomSmsError("Message cannot be empty", status_code=400)

        # Generate deterministic session ID if not provided
        if session_id is None:
            session_id = generate_session_id(account.phone_number, to)

        # Build request body
        body = {
            "sender": {
                "phone_number": account.phone_number,
            },
            "to_members": [
                {"phone_number": to}
            ],
            "message": message,
            "session_id": session_id,
        }

        # Include user_id if we have it
        if account.zoom_user_id:
            body["sender"]["user_id"] = account.zoom_user_id

        # Send with auto-refresh on 401
        return await self._send_with_retry(account_name, body)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _get_account(self, account_name: str) -> ZoomAccount:
        """Look up and validate the account."""
        account = self.config.accounts.get(account_name)
        if account is None:
            raise ZoomSmsError(
                f"Zoom account '{account_name}' not found in configuration",
                status_code=404,
            )
        if not account.enabled:
            raise ZoomSmsError(
                f"Zoom account '{account_name}' is disabled",
                status_code=403,
            )
        return account

    async def _send_with_retry(
        self, account_name: str, body: Dict, retried_auth: bool = False
    ) -> ZoomSmsSendResponse:
        """Send SMS request with automatic 401 retry (token refresh)."""
        access_token = await self.oauth_manager.get_valid_token(account_name)

        response = await self._http.post(
            ZOOM_SMS_URL,
            json=body,
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
            },
        )

        if response.status_code == 201:
            data = response.json()
            logger.info(
                f"📱 SMS sent via Zoom: {body['sender']['phone_number']} → "
                f"{body['to_members'][0]['phone_number']} "
                f"(message_id={data.get('message_id', 'N/A')})"
            )
            return ZoomSmsSendResponse(
                message_id=data["message_id"],
                session_id=data["session_id"],
                date_time=data["date_time"],
            )

        # Handle 401 — token expired, try refresh once
        if response.status_code == 401 and not retried_auth:
            logger.info(f"🔄 Zoom 401 for '{account_name}' — refreshing token and retrying")
            try:
                await self.oauth_manager.refresh_token(account_name)
            except ZoomOAuthError as e:
                raise ZoomSmsError(
                    f"Token refresh failed for '{account_name}': {e}",
                    status_code=401,
                )
            return await self._send_with_retry(account_name, body, retried_auth=True)

        # Handle 429 — rate limited
        if response.status_code == 429:
            retry_after = response.headers.get("Retry-After", "60")
            raise ZoomSmsError(
                f"Rate limited by Zoom API. Retry after {retry_after}s",
                status_code=429,
            )

        # Handle other errors
        error_data = None
        try:
            error_data = response.json()
        except Exception:
            pass

        error_code = error_data.get("code") if error_data else None
        error_msg = error_data.get("message", response.text) if error_data else response.text

        raise ZoomSmsError(
            f"Zoom SMS API error: {response.status_code} — {error_msg}",
            status_code=response.status_code,
            error_code=error_code,
            response_data=error_data,
        )
