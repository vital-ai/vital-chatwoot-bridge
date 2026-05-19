"""
Message debouncer using AWS MemoryDB (Redis-compatible).

Implements:
- Layer 1: Message ID deduplication (SET NX EX)
- Layer 2: Per-conversation debounce buffer (List + Hash)
- Layer 3: Distributed lock for drain arbitration (SET NX EX)
- Drain worker: background polling task

Key namespace (hash-tagged for cluster slot co-location):
    cw_bridge:dedup:{message_id}          — String, 60s TTL
    cw_bridge:{conv_id}:debounce          — List (buffered messages)
    cw_bridge:{conv_id}:meta              — Hash (first_arrival, last_arrival, inbox_id)
    cw_bridge:{conv_id}:lock              — String (lock holder)
    cw_bridge:active_conversations        — Set (pending conversation IDs)
"""

import asyncio
import json
import logging
import time
import uuid
from typing import Any, Callable, Coroutine, Dict, List, Optional

import redis.asyncio as aioredis

from vital_chatwoot_bridge.core.config import DebounceConfig

logger = logging.getLogger(__name__)

# Key templates — {conv_id} acts as the Redis hash tag for slot co-location
_DEDUP_KEY = "cw_bridge:dedup:{message_id}"
_BUFFER_KEY = "cw_bridge:{{{conv_id}}}:debounce"
_META_KEY = "cw_bridge:{{{conv_id}}}:meta"
_LOCK_KEY = "cw_bridge:{{{conv_id}}}:lock"
_ACTIVE_SET = "cw_bridge:active_conversations"


class MessageDebouncer:
    """Manages message deduplication, buffering, and drain polling."""

    def __init__(
        self,
        redis: aioredis.RedisCluster,
        config: DebounceConfig,
        drain_callback: Callable[[str, str, Dict[str, Any]], Coroutine],
    ):
        """
        Args:
            redis: RedisCluster client instance.
            config: Debounce configuration.
            drain_callback: Async function called when a batch is ready.
                Signature: drain_callback(conversation_id, concatenated_content, metadata)
                metadata includes: inbox_id, first_arrival, last_arrival, message_count, last_message_payload
        """
        self._r = redis
        self._config = config
        self._drain_callback = drain_callback
        self._drain_task: Optional[asyncio.Task] = None
        self._task_id = f"task_{uuid.uuid4().hex[:8]}"
        self._running = False

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Start the background drain worker."""
        self._running = True
        self._drain_task = asyncio.create_task(self._drain_loop(), name="debounce_drain")
        logger.info(f"⏱️  DEBOUNCE: Drain worker started (task_id={self._task_id}, poll={self._config.drain_poll_interval}s)")

    async def stop(self) -> None:
        """Stop the drain worker gracefully."""
        self._running = False
        if self._drain_task and not self._drain_task.done():
            self._drain_task.cancel()
            try:
                await self._drain_task
            except asyncio.CancelledError:
                pass
        logger.info("⏱️  DEBOUNCE: Drain worker stopped")

    async def handle_message(
        self,
        message_id: str,
        conversation_id: str,
        content: str,
        inbox_id: str,
        full_payload: Dict[str, Any],
    ) -> str:
        """Process an incoming message through dedup + debounce.

        Returns:
            "duplicate" — message already processed (skip)
            "buffered"  — message added to debounce buffer (202 Accepted)
            "passthrough" — debounce disabled for this inbox (process immediately)
        """
        # Only debounce inboxes explicitly listed in sms_inbox_ids
        if inbox_id not in self._config.sms_inbox_ids:
            return "passthrough"

        # Layer 1: Dedup
        dedup_key = _DEDUP_KEY.format(message_id=message_id)
        is_new = await self._r.set(
            dedup_key, "1", nx=True, ex=self._config.dedup_ttl_seconds
        )
        if not is_new:
            logger.info(f"⏱️  DEBOUNCE: Duplicate message_id={message_id} — skipping")
            return "duplicate"

        # Layer 2: Buffer
        buffer_key = _BUFFER_KEY.format(conv_id=conversation_id)
        meta_key = _META_KEY.format(conv_id=conversation_id)
        now = time.time()
        ttl = int(self._config.max_window_seconds) + 5

        # Store the full payload as JSON so drain can reconstruct metadata
        entry = json.dumps({
            "message_id": message_id,
            "content": content,
            "inbox_id": inbox_id,
            "timestamp": now,
            "payload": full_payload,
        })

        # Buffer the message
        await self._r.rpush(buffer_key, entry)
        await self._r.expire(buffer_key, ttl)

        # Meta: first_arrival (idempotent), last_arrival (always update)
        await self._r.hsetnx(meta_key, "first_arrival", str(now))
        await self._r.hset(meta_key, "last_arrival", str(now))
        await self._r.hset(meta_key, "inbox_id", inbox_id)
        await self._r.expire(meta_key, ttl)

        # Track active conversation
        await self._r.sadd(_ACTIVE_SET, conversation_id)

        buf_len = await self._r.llen(buffer_key)
        logger.info(
            f"⏱️  DEBOUNCE: Buffered msg={message_id} for conv={conversation_id} "
            f"(buffer_size={buf_len})"
        )
        return "buffered"

    # ------------------------------------------------------------------
    # Drain Worker
    # ------------------------------------------------------------------

    async def _drain_loop(self) -> None:
        """Background loop: poll for conversations ready to drain."""
        while self._running:
            try:
                await self._poll_and_drain()
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error(f"⏱️  DEBOUNCE: Drain loop error: {e}", exc_info=True)
            await asyncio.sleep(self._config.drain_poll_interval)

    async def _poll_and_drain(self) -> None:
        """Check all active conversations and drain any that are ready."""
        # Get active conversation IDs
        active = await self._r.smembers(_ACTIVE_SET)
        if not active:
            return

        now = time.time()
        for conv_id in active:
            try:
                await self._check_and_drain(conv_id, now)
            except Exception as e:
                logger.error(f"⏱️  DEBOUNCE: Error checking conv={conv_id}: {e}")

    async def _check_and_drain(self, conv_id: str, now: float) -> None:
        """Check if a conversation is ready to drain, and drain if so."""
        meta_key = _META_KEY.format(conv_id=conv_id)
        meta = await self._r.hgetall(meta_key)

        if not meta:
            # Stale entry in active set — clean up
            await self._r.srem(_ACTIVE_SET, conv_id)
            return

        first_arrival = float(meta.get("first_arrival", now))
        last_arrival = float(meta.get("last_arrival", now))

        # Quiet window check: silence for >= window_seconds
        quiet_elapsed = now - last_arrival >= self._config.window_seconds
        # Hard cap check: first message arrived >= max_window_seconds ago
        hard_cap = now - first_arrival >= self._config.max_window_seconds

        if not quiet_elapsed and not hard_cap:
            return  # Not ready yet

        reason = "quiet_window" if quiet_elapsed else "hard_cap"
        logger.info(f"⏱️  DEBOUNCE: Draining conv={conv_id} (reason={reason})")

        # Acquire distributed lock
        lock_key = _LOCK_KEY.format(conv_id=conv_id)
        lock_value = f"{self._task_id}:{uuid.uuid4().hex[:8]}"
        acquired = await self._r.set(lock_key, lock_value, nx=True, ex=30)
        if not acquired:
            logger.debug(f"⏱️  DEBOUNCE: Lock not acquired for conv={conv_id} — another worker handling")
            return

        try:
            await self._drain_conversation(conv_id, meta)
        finally:
            # Release lock (only if we still hold it)
            current = await self._r.get(lock_key)
            if current == lock_value:
                await self._r.delete(lock_key)

    async def _drain_conversation(self, conv_id: str, meta: Dict[str, str]) -> None:
        """Drain the buffer for a conversation and invoke the callback."""
        buffer_key = _BUFFER_KEY.format(conv_id=conv_id)
        meta_key = _META_KEY.format(conv_id=conv_id)

        # Atomic read + delete
        entries_raw = await self._r.lrange(buffer_key, 0, -1)
        if not entries_raw:
            # Buffer already drained by another worker or expired
            await self._r.srem(_ACTIVE_SET, conv_id)
            await self._r.delete(meta_key)
            return

        # Delete buffer and meta
        await self._r.delete(buffer_key)
        await self._r.delete(meta_key)
        await self._r.srem(_ACTIVE_SET, conv_id)

        # Parse entries
        entries: List[Dict[str, Any]] = []
        for raw in entries_raw:
            try:
                entries.append(json.loads(raw))
            except json.JSONDecodeError:
                logger.warning(f"⏱️  DEBOUNCE: Skipping malformed buffer entry for conv={conv_id}")

        if not entries:
            return

        # Concatenate content
        contents = [e.get("content", "") for e in entries if e.get("content")]
        concatenated = "\n".join(contents)

        # Use metadata from last message (most recent context)
        last_entry = entries[-1]
        callback_meta = {
            "inbox_id": meta.get("inbox_id", ""),
            "first_arrival": meta.get("first_arrival", ""),
            "last_arrival": meta.get("last_arrival", ""),
            "message_count": len(entries),
            "last_message_payload": last_entry.get("payload", {}),
        }

        logger.info(
            f"⏱️  DEBOUNCE: Delivering batch for conv={conv_id} — "
            f"{len(entries)} message(s), {len(concatenated)} chars"
        )

        try:
            await self._drain_callback(conv_id, concatenated, callback_meta)
        except Exception as e:
            logger.error(
                f"⏱️  DEBOUNCE: Drain callback failed for conv={conv_id}: {e}",
                exc_info=True,
            )
