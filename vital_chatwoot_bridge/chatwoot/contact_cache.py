"""
In-memory TTL cache for Chatwoot contacts with per-key request coalescing.

Prevents duplicate contact search/create calls when many webhooks arrive
for the same contact simultaneously.  Each task has its own cache; cross-task
races are handled by the 422-graceful-handling logic in client_api.py.
"""

import asyncio
import logging
import time
from collections import OrderedDict
from typing import Any, Awaitable, Callable, Optional

logger = logging.getLogger(__name__)


class ContactCache:
    """In-memory LRU cache with TTL and per-key coalescing."""

    def __init__(self, ttl_seconds: int = 300, max_size: int = 10_000):
        self._ttl = ttl_seconds
        self._max_size = max_size
        # key → (value, expiry_timestamp)
        self._store: OrderedDict[str, tuple[Any, float]] = OrderedDict()
        # key → asyncio.Lock  (only exists while a lookup is in-flight)
        self._locks: dict[str, asyncio.Lock] = {}
        # stats
        self._hits = 0
        self._misses = 0

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def get_or_create(
        self,
        key: str,
        factory: Callable[[], Awaitable[Any]],
    ) -> Any:
        """Return cached value or call *factory* exactly once per key.

        Concurrent callers for the same *key* will wait for the first
        factory call to complete and then share the result.
        """
        # Fast-path: already cached & not expired
        cached = self._get(key)
        if cached is not None:
            self._hits += 1
            return cached

        # Slow-path: acquire per-key lock so only one factory runs
        lock = self._locks.setdefault(key, asyncio.Lock())
        async with lock:
            # Re-check after acquiring (another coroutine may have populated)
            cached = self._get(key)
            if cached is not None:
                self._hits += 1
                return cached

            self._misses += 1
            value = await factory()
            self._put(key, value)
            return value

    def get(self, key: str) -> Optional[Any]:
        """Return cached value if present and not expired, else None."""
        return self._get(key)

    def put(self, key: str, value: Any) -> None:
        """Manually store a value."""
        self._put(key, value)

    def invalidate(self, key: str) -> None:
        """Remove a key from the cache."""
        self._store.pop(key, None)

    def clear(self) -> None:
        """Clear all entries."""
        self._store.clear()
        self._locks.clear()
        self._hits = 0
        self._misses = 0

    def stats(self) -> dict:
        """Return cache statistics for observability."""
        total = self._hits + self._misses
        return {
            "size": len(self._store),
            "max_size": self._max_size,
            "ttl_seconds": self._ttl,
            "hits": self._hits,
            "misses": self._misses,
            "hit_ratio": round(self._hits / total, 3) if total else 0.0,
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get(self, key: str) -> Optional[Any]:
        entry = self._store.get(key)
        if entry is None:
            return None
        value, expiry = entry
        if time.monotonic() > expiry:
            # Expired — evict
            self._store.pop(key, None)
            return None
        # Move to end (most recently used)
        self._store.move_to_end(key)
        return value

    def _put(self, key: str, value: Any) -> None:
        expiry = time.monotonic() + self._ttl
        self._store[key] = (value, expiry)
        self._store.move_to_end(key)
        # Evict oldest entries if over capacity
        while len(self._store) > self._max_size:
            evicted_key, _ = self._store.popitem(last=False)
            self._locks.pop(evicted_key, None)
            logger.debug(f"ContactCache: evicted {evicted_key} (LRU)")


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------
_contact_cache: Optional[ContactCache] = None


def get_contact_cache() -> ContactCache:
    """Return the module-level ContactCache singleton (lazy-init)."""
    global _contact_cache
    if _contact_cache is None:
        from vital_chatwoot_bridge.core.config import get_settings
        settings = get_settings()
        _contact_cache = ContactCache(
            ttl_seconds=settings.rl_contact_cache_ttl,
            max_size=10_000,
        )
        logger.info(
            f"📋 ContactCache initialized — ttl={settings.rl_contact_cache_ttl}s, max_size=10000"
        )
    return _contact_cache
