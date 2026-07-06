"""
General-purpose message event webhook.

Fires a normalized JSON payload to a configurable external endpoint whenever
the bridge receives or sends a message — regardless of channel or method.
"""

import asyncio
import hashlib
import hmac
import json
import logging
import uuid
from datetime import datetime
from typing import Any, Dict, Optional

import httpx

from vital_chatwoot_bridge.core.config import MessageWebhookConfig

logger = logging.getLogger(__name__)

# Module-level singleton
_instance: Optional["MessageEventWebhook"] = None


def init_message_webhook(config: Optional[MessageWebhookConfig]) -> None:
    """Initialize the module-level singleton."""
    global _instance
    if config and config.enabled and config.url:
        _instance = MessageEventWebhook(config)
        logger.info(f"📋 Message event webhook initialized — url={config.url}")
    else:
        _instance = None
        logger.info("📋 Message event webhook disabled (not configured or not enabled)")


def get_message_webhook() -> Optional["MessageEventWebhook"]:
    """Return the singleton (may be None if disabled)."""
    return _instance


def build_message_event(
    *,
    direction: str,
    channel: str,
    delivery_method: str,
    contact: Dict[str, Any],
    message: Dict[str, Any],
    metadata: Dict[str, Any],
    delivery: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Construct a normalized message event payload."""
    return {
        "event_id": str(uuid.uuid4()),
        "event": "message",
        "direction": direction,
        "channel": channel,
        "delivery_method": delivery_method,
        "contact": contact,
        "message": message,
        "metadata": {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            **metadata,
        },
        "delivery": delivery or {
            "status": "sent" if direction == "outbound" else "received",
        },
    }


async def fire_message_event(
    *,
    direction: str,
    channel: str,
    delivery_method: str,
    contact: Dict[str, Any],
    message: Dict[str, Any],
    metadata: Dict[str, Any],
    delivery: Optional[Dict[str, Any]] = None,
) -> None:
    """Convenience: build payload and fire if webhook is enabled."""
    webhook = get_message_webhook()
    if webhook is None:
        return

    # Enrich metadata with from_phone/from_email from inbox config
    inbox_id = metadata.get("inbox_id")
    if inbox_id:
        try:
            from vital_chatwoot_bridge.core.config import get_settings
            mapping = get_settings().get_inbox_mapping(str(inbox_id))
            if mapping:
                if mapping.from_phone and "from_phone" not in metadata:
                    metadata["from_phone"] = mapping.from_phone
                if mapping.from_email and "from_email" not in metadata:
                    metadata["from_email"] = mapping.from_email
        except Exception:
            pass  # Don't block webhook on config lookup failure

    payload = build_message_event(
        direction=direction,
        channel=channel,
        delivery_method=delivery_method,
        contact=contact,
        message=message,
        metadata=metadata,
        delivery=delivery,
    )
    await webhook.fire(payload)


class MessageEventWebhook:
    """Fire-and-forget webhook for message events."""

    def __init__(self, config: MessageWebhookConfig):
        self.config = config
        self._client = httpx.AsyncClient(
            timeout=config.timeout_seconds,
            transport=httpx.AsyncHTTPTransport(retries=0),
        )

    async def fire(self, payload: Dict[str, Any]) -> None:
        """Send webhook in background. Does not block the caller."""
        if not self.config.enabled or not self.config.url:
            return
        asyncio.create_task(self._send_with_retry(payload))

    async def _send_with_retry(self, payload: Dict[str, Any]) -> None:
        """POST payload with HMAC signature, retry on failure."""
        body = json.dumps(payload, default=str)
        timestamp = datetime.utcnow().isoformat() + "Z"
        # Sign over "timestamp.body" so the receiver can guard against replay
        sign_input = f"{timestamp}.{body}"
        signature = hmac.new(
            self.config.secret.encode(),
            sign_input.encode(),
            hashlib.sha256,
        ).hexdigest()

        headers = {
            "Content-Type": "application/json",
            "X-Message-Webhook-Signature": signature,
            "X-Message-Webhook-Timestamp": timestamp,
        }

        for attempt in range(self.config.max_retries + 1):
            try:
                resp = await self._client.post(
                    self.config.url, content=body, headers=headers,
                )
                if resp.status_code < 400:
                    logger.debug(
                        "Message webhook delivered event_id=%s status=%s",
                        payload.get("event_id"), resp.status_code,
                    )
                    return
                logger.warning(
                    "Message webhook returned %s (attempt %d/%d) event_id=%s",
                    resp.status_code, attempt + 1, self.config.max_retries + 1,
                    payload.get("event_id"),
                )
            except Exception as e:
                logger.warning(
                    "Message webhook failed (attempt %d/%d): %s",
                    attempt + 1, self.config.max_retries + 1, e,
                )

            if attempt < self.config.max_retries:
                await asyncio.sleep(
                    self.config.retry_delay_seconds * (attempt + 1)
                )

        logger.error(
            "Message webhook exhausted retries for event_id=%s",
            payload.get("event_id"),
        )

    async def close(self) -> None:
        """Shut down the HTTP client."""
        await self._client.aclose()
