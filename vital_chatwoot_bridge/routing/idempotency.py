"""Idempotency keys for writes that must not happen twice, such as a reply that sends an email.

The first call with a key does the write and keeps its result; a repeat with the same key gets that result back without
writing again. While the first is still running, a repeat gets a 409. Results are kept for the configured TTL (7 days by
default), in Redis (MemoryDB) so every instance sees them; in memory without Redis.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any, Awaitable, Callable, Dict, Optional, Tuple

logger = logging.getLogger(__name__)

PENDING = "__pending__"
CLAIM_SECONDS = 120


class InProgress(Exception):
    """The same key is being written right now."""


class IdempotencyStore:
    def __init__(self, redis, prefix: str, ttl_seconds: int):
        self.redis = redis
        self.prefix = prefix
        self.ttl = ttl_seconds
        self._memory: Dict[str, Tuple[float, str]] = {}

    def _key(self, scope: str, key: str) -> str:
        return f"{self.prefix}idem:{{{scope}:{key}}}"

    async def _get(self, k: str) -> Optional[str]:
        if self.redis is not None:
            return await self.redis.get(k)
        hit = self._memory.get(k)
        if hit and hit[0] > time.time():
            return hit[1]
        self._memory.pop(k, None)
        return None

    async def _claim(self, k: str) -> bool:
        if self.redis is not None:
            return bool(await self.redis.set(k, PENDING, nx=True, ex=CLAIM_SECONDS))
        if await self._get(k) is not None:
            return False
        self._memory[k] = (time.time() + CLAIM_SECONDS, PENDING)
        return True

    async def _put(self, k: str, value: str) -> None:
        if self.redis is not None:
            await self.redis.set(k, value, ex=self.ttl)
        else:
            self._memory[k] = (time.time() + self.ttl, value)

    async def _drop(self, k: str) -> None:
        if self.redis is not None:
            await self.redis.delete(k)
        else:
            self._memory.pop(k, None)

    async def run(self, scope: str, key: Optional[str], write: Callable[[], Awaitable[Any]]) -> Tuple[Any, bool]:
        """(result, replayed). Without a key, it just writes."""
        if not key:
            return await write(), False
        k = self._key(scope, key)
        seen = await self._get(k)
        if seen is not None and seen != PENDING:
            return json.loads(seen), True
        if seen == PENDING or not await self._claim(k):
            again = await self._get(k)
            if again is not None and again != PENDING:
                return json.loads(again), True
            raise InProgress(key)
        try:
            result = await write()
        except BaseException:
            await self._drop(k)                 # nothing was written: a retry may try again
            raise
        await self._put(k, json.dumps(result, default=str))
        return result, False


_store: Optional[IdempotencyStore] = None


def get_idempotency_store() -> IdempotencyStore:
    global _store
    if _store is None:
        from vital_chatwoot_bridge.core.config import get_settings
        from vital_chatwoot_bridge.services.redis_client import get_redis
        s = get_settings()
        _store = IdempotencyStore(get_redis(), s.routing_key_prefix, s.idempotency_ttl_seconds)
    return _store


def set_idempotency_store(store: Optional[IdempotencyStore]) -> None:
    global _store
    _store = store
