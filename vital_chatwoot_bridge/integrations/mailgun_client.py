"""
Mailgun API Client for sending emails (text and HTML).
Follows the same pattern as LoopMessageClient.
"""

import logging
import httpx
from typing import Dict, Any, Optional

from vital_chatwoot_bridge.email.models import MailgunConfig

logger = logging.getLogger(__name__)


class MailgunClientError(Exception):
    """Exception raised for Mailgun API errors."""

    def __init__(self, message: str, status_code: Optional[int] = None, response_data: Optional[Dict] = None):
        super().__init__(message)
        self.status_code = status_code
        self.response_data = response_data


class MailgunClient:
    """Client for Mailgun API email sending operations."""

    def __init__(self, config: MailgunConfig):
        self.config = config
        self.client = httpx.AsyncClient(timeout=30.0)

    async def __aenter__(self):
        """Async context manager entry."""
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        await self.client.aclose()

    async def send_email(
        self,
        to: str,
        subject: str,
        html: Optional[str] = None,
        text: Optional[str] = None,
        from_email: Optional[str] = None,
        cc: Optional[str] = None,
        bcc: Optional[str] = None,
        reply_to: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Send an email via Mailgun API.

        Args:
            to: Recipient email address
            subject: Email subject line
            html: HTML email body
            text: Plain text email body
            from_email: Sender address (defaults to config from_email)
            cc: CC addresses, comma-separated
            bcc: BCC addresses, comma-separated
            reply_to: Reply-to address

        Returns:
            Mailgun API response with 'id' and 'message' fields

        Raises:
            MailgunClientError: If the API request fails
        """
        if not html and not text:
            raise MailgunClientError("At least one of 'html' or 'text' must be provided")

        sender = from_email or self.config.from_email
        if not sender:
            raise MailgunClientError("No sender address: provide from_email or configure mailgun.from_email")

        url = f"{self.config.base_url}/{self.config.domain}/messages"

        # Mailgun uses multipart/form-data, not JSON
        data = {
            "from": sender,
            "to": to,
            "subject": subject,
        }
        if html:
            data["html"] = html
        if text:
            data["text"] = text
        if cc:
            data["cc"] = cc
        if bcc:
            data["bcc"] = bcc
        if reply_to:
            data["h:Reply-To"] = reply_to

        try:
            logger.info(f"📧 Sending email via Mailgun to: {to}, subject: {subject}")

            response = await self.client.post(
                url,
                auth=("api", self.config.api_key),
                data=data,
            )

            if response.status_code == 200:
                result = response.json()
                logger.info(f"✅ Mailgun email sent: {result.get('id', 'unknown')}")
                return result

            # Handle error responses
            error_data = None
            try:
                error_data = response.json()
            except Exception:
                pass

            error_msg = "Unknown error"
            if error_data and "message" in error_data:
                error_msg = error_data["message"]
            elif response.text:
                error_msg = response.text[:200]

            if response.status_code == 401:
                raise MailgunClientError(
                    f"Unauthorized: invalid Mailgun API key",
                    status_code=401, response_data=error_data,
                )
            elif response.status_code == 400:
                raise MailgunClientError(
                    f"Bad Request: {error_msg}",
                    status_code=400, response_data=error_data,
                )
            else:
                raise MailgunClientError(
                    f"Mailgun API error (HTTP {response.status_code}): {error_msg}",
                    status_code=response.status_code, response_data=error_data,
                )

        except MailgunClientError:
            raise
        except httpx.RequestError as e:
            raise MailgunClientError(f"Network error contacting Mailgun: {e}")
        except Exception as e:
            raise MailgunClientError(f"Unexpected error sending email via Mailgun: {e}")

    async def close(self):
        """Close the underlying HTTP client."""
        await self.client.aclose()
