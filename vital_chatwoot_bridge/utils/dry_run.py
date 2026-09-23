"""
Server-wide dry-run mode (``CW_BRIDGE__app__dry_run=true``).

When enabled, nothing reaches a real recipient:

- Outbound Chatwoot messages are forced to private notes (Chatwoot does not
  dispatch private notes through the inbox channel), or — with
  ``CW_BRIDGE__app__dry_run_record_notes=false`` — not written at all.
- Inbound Chatwoot messages are never written (an incoming message would
  trigger the production bridge's AI agent, whose public reply Chatwoot
  would deliver).
- Mailgun, Gmail, Zoom SMS and LoopMessage sends are skipped and a fake
  success response is returned so the rest of the flow still runs.

See ``planning/testing/dry-run-mode.md``.
"""

import logging
import time
import uuid
from typing import Any, Dict

logger = logging.getLogger(__name__)


def is_dry_run() -> bool:
    """Return True if the server is running in dry-run mode."""
    from vital_chatwoot_bridge.core.config import get_settings
    return bool(getattr(get_settings(), "dry_run", False))


def records_notes() -> bool:
    """Return True if dry-run should record outbound messages as private notes."""
    from vital_chatwoot_bridge.core.config import get_settings
    return bool(getattr(get_settings(), "dry_run_record_notes", True))


def fake_provider_id(provider: str) -> str:
    """Generate a recognisable fake provider message ID."""
    return f"dryrun-{provider}-{uuid.uuid4().hex[:12]}"


def log_skipped_send(provider: str, **details: Any) -> None:
    """Log what would have been sent."""
    detail_str = ", ".join(f"{k}={v!r}" for k, v in details.items())
    logger.warning(f"🧪 DRY RUN: skipped {provider} send ({detail_str})")


def _is_outgoing(message_type: Any) -> bool:
    return message_type in ("outgoing", 1, "1")


def _is_incoming(message_type: Any) -> bool:
    return message_type in ("incoming", 0, "0")


def should_skip_chatwoot_message(payload: Dict[str, Any]) -> bool:
    """True if a Chatwoot message should not be written at all.

    In dry-run, incoming messages are always skipped; outgoing messages are
    skipped unless ``dry_run_record_notes`` is on.
    """
    if not is_dry_run():
        return False
    message_type = payload.get("message_type", "outgoing")
    if _is_incoming(message_type):
        return True
    return _is_outgoing(message_type) and not records_notes()


def fake_chatwoot_message(conversation_id: Any, payload: Dict[str, Any]) -> Dict[str, Any]:
    """Build a stand-in for the Chatwoot message-create response (id=0)."""
    logger.warning(
        f"🧪 DRY RUN: skipped Chatwoot message write (conversation={conversation_id}, "
        f"content={str(payload.get('content', ''))[:80]!r})"
    )
    return {
        "id": 0,
        "content": payload.get("content") or "",
        "conversation_id": conversation_id,
        "message_type": 0 if _is_incoming(payload.get("message_type", "outgoing")) else 1,
        "content_type": payload.get("content_type", "text"),
        "private": bool(payload.get("private", False)),
        "created_at": int(time.time()),
        "content_attributes": payload.get("content_attributes") or {},
        "sender": {},
        "attachments": [],
        "dry_run": True,
    }


def apply_dry_run_to_message_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Force an outgoing Chatwoot message payload to a private note (in place).

    No-op when dry-run is off, the message is incoming, or it is already private.
    """
    if not is_dry_run():
        return payload
    if not _is_outgoing(payload.get("message_type", "outgoing")):
        return payload
    if payload.get("private") in (True, "true"):
        return payload

    payload["private"] = True
    attrs = payload.get("content_attributes")
    if isinstance(attrs, dict):
        attrs["dry_run"] = True
    elif attrs is None:
        payload["content_attributes"] = {"dry_run": True}
    logger.warning("🧪 DRY RUN: outgoing Chatwoot message forced to private note")
    return payload
