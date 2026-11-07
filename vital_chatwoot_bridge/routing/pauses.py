"""Pausing an inbox: its messages still arrive in Chatwoot, but none is handed to its agent until it's resumed.

Runtime state, kept in Redis (MemoryDB, cluster mode) so it survives restarts and is shared by every instance of the
bridge. Reloading the routes never touches it: only resume ends a pause. One hash per route,
``<prefix>{route:<account>:<inbox>}:pause``, holds when, by whom and why; a set, ``<prefix>{routes}:paused``, lists the
paused routes. Without Redis (local development), pauses are kept in memory and logged as such.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


class PauseStore:
    def __init__(self, redis, prefix: str):
        self.redis = redis
        self.prefix = prefix
        self._memory: Dict[Tuple[int, str], dict] = {}
        if redis is None:
            logger.warning("⏸️  PAUSES: no Redis configured: pauses are kept in memory and lost on restart")

    def _key(self, account_id: int, inbox_id: str) -> str:
        return f"{self.prefix}{{route:{account_id}:{inbox_id}}}:pause"

    @property
    def _index(self) -> str:
        return f"{self.prefix}{{routes}}:paused"

    async def get(self, account_id: int, inbox_id: str) -> Optional[dict]:
        if self.redis is None:
            return self._memory.get((account_id, str(inbox_id)))
        found = await self.redis.hgetall(self._key(account_id, inbox_id))
        return found or None

    async def pause(self, account_id: int, inbox_id: str, by: str, reason: str) -> dict:
        state = {"paused_at": datetime.now(timezone.utc).isoformat(), "by": by, "reason": reason}
        if self.redis is None:
            self._memory[(account_id, str(inbox_id))] = state
        else:
            await self.redis.hset(self._key(account_id, inbox_id), mapping=state)
            await self.redis.sadd(self._index, f"{account_id}:{inbox_id}")
        logger.warning(f"⏸️  PAUSES: account {account_id} inbox {inbox_id} paused by {by}: {reason}")
        return state

    async def resume(self, account_id: int, inbox_id: str, by: str) -> bool:
        if self.redis is None:
            was = self._memory.pop((account_id, str(inbox_id)), None) is not None
        else:
            was = bool(await self.redis.delete(self._key(account_id, inbox_id)))
            await self.redis.srem(self._index, f"{account_id}:{inbox_id}")
        logger.warning(f"▶️  PAUSES: account {account_id} inbox {inbox_id} resumed by {by}")
        return was

    async def all(self) -> Dict[Tuple[int, str], dict]:
        if self.redis is None:
            return dict(self._memory)
        out: Dict[Tuple[int, str], dict] = {}
        for member in await self.redis.smembers(self._index):
            account, _, inbox = member.partition(":")
            state = await self.get(int(account), inbox)
            if state:
                out[(int(account), inbox)] = state
        return out


_store: Optional[PauseStore] = None


def get_pause_store() -> PauseStore:
    global _store
    if _store is None:
        from vital_chatwoot_bridge.core.config import get_settings
        from vital_chatwoot_bridge.services.redis_client import get_redis
        _store = PauseStore(get_redis(), get_settings().routing_key_prefix)
    return _store


def set_pause_store(store: Optional[PauseStore]) -> None:
    global _store
    _store = store


def paused_list(states: Dict[Tuple[int, str], dict]) -> List[dict]:
    return [{"account_id": a, "inbox_id": i, **s} for (a, i), s in sorted(states.items())]
