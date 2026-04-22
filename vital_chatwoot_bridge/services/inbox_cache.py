"""
InboxCacheService — caches Chatwoot inbox list and provides
inbox_id → channel type mapping with API inbox reverse lookup.
"""

import asyncio
import logging
import time
from typing import Dict, Optional

from vital_chatwoot_bridge.core.config import get_settings
from vital_chatwoot_bridge.chatwoot.api_client import get_chatwoot_client

logger = logging.getLogger(__name__)

# Standard Chatwoot channel_type → friendly name
_CHANNEL_MAP: Dict[str, str] = {
    "Channel::Email": "email",
    "Channel::Twilio::SmsSender": "sms",
    "Channel::TwilioSms": "sms",
    "Channel::WebWidget": "webchat",
    "Channel::Whatsapp": "whatsapp",
    "Channel::Telegram": "telegram",
    "Channel::Line": "line",
    "Channel::FacebookPage": "facebook",
}


class InboxCacheService:
    """Caches inbox metadata and resolves inbox_id → channel type."""

    def __init__(self, ttl_seconds: float = 300.0):
        self._ttl = ttl_seconds
        self._cache: Dict[int, Dict] = {}  # inbox_id → inbox dict
        self._channel_cache: Dict[int, str] = {}  # inbox_id → channel name
        self._loaded_at: float = 0.0
        self._lock = asyncio.Lock()

    async def _refresh_if_stale(self) -> None:
        """Fetch inboxes from Chatwoot if cache is older than TTL."""
        if time.monotonic() - self._loaded_at < self._ttl and self._cache:
            return
        async with self._lock:
            # Double-check after acquiring lock
            if time.monotonic() - self._loaded_at < self._ttl and self._cache:
                return
            try:
                client = await get_chatwoot_client()
                account_id = int(get_settings().chatwoot_account_id)
                data = await client.list_inboxes(account_id)
                payload = data.get("payload", data) if isinstance(data, dict) else data
                if isinstance(payload, list):
                    inboxes = payload
                else:
                    inboxes = payload if isinstance(payload, list) else []

                self._cache.clear()
                self._channel_cache.clear()

                settings = get_settings()
                for inbox in inboxes:
                    iid = int(inbox.get("id", 0))
                    self._cache[iid] = inbox
                    channel_type = inbox.get("channel_type", "")
                    if channel_type == "Channel::Api":
                        # Reverse-lookup via bridge config
                        api_cfg = settings.get_api_inbox_by_chatwoot_id(str(iid))
                        if api_cfg and api_cfg.message_types:
                            self._channel_cache[iid] = api_cfg.message_types[0]
                        else:
                            self._channel_cache[iid] = "api"
                    else:
                        self._channel_cache[iid] = _CHANNEL_MAP.get(channel_type, channel_type)

                self._loaded_at = time.monotonic()
                logger.info(f"InboxCacheService refreshed: {len(self._cache)} inboxes cached")
            except Exception:
                logger.exception("Failed to refresh inbox cache")

    async def get_channel(self, inbox_id: int) -> str:
        """Return the friendly channel name for an inbox ID."""
        await self._refresh_if_stale()
        return self._channel_cache.get(inbox_id, "unknown")

    async def get_inbox(self, inbox_id: int) -> Optional[Dict]:
        """Return the full inbox dict for an inbox ID."""
        await self._refresh_if_stale()
        return self._cache.get(inbox_id)

    async def get_inbox_name(self, inbox_id: int) -> str:
        """Return the inbox display name."""
        inbox = await self.get_inbox(inbox_id)
        return inbox.get("name", "Unknown") if inbox else "Unknown"


# Module-level singleton
_instance: Optional[InboxCacheService] = None


def get_inbox_cache() -> InboxCacheService:
    global _instance
    if _instance is None:
        _instance = InboxCacheService()
    return _instance
