"""
Dual-mode webhook queue for throttling Attentive webhook processing.

Supports two backends:
- **memory** (default): ``asyncio.Queue`` — zero dependencies, per-task only.
- **redis**: Redis list via ``redis.asyncio`` — durable, shared across ECS tasks.

Both backends expose the same interface and are consumed by an identical
worker pool that processes items at a controlled rate.
"""

import asyncio
import json
import logging
import time
from typing import Any, Awaitable, Callable, Dict, List, Optional, Protocol

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Queue protocol
# ---------------------------------------------------------------------------

class WebhookQueue(Protocol):
    """Common interface for webhook queue backends."""

    async def enqueue(self, item: dict) -> bool:
        """Push an item.  Returns True on success, False if queue is full."""
        ...

    async def dequeue(self, timeout: float = 1.0) -> Optional[dict]:
        """Pop the next item, blocking up to *timeout* seconds."""
        ...

    async def depth(self) -> int:
        """Return current queue length."""
        ...

    async def close(self) -> None:
        """Release resources."""
        ...


# ---------------------------------------------------------------------------
# In-memory backend
# ---------------------------------------------------------------------------

class InMemoryQueue:
    """Bounded ``asyncio.Queue`` backend."""

    def __init__(self, maxsize: int = 5000):
        self._queue: asyncio.Queue[dict] = asyncio.Queue(maxsize=maxsize)
        self._maxsize = maxsize

    async def enqueue(self, item: dict) -> bool:
        try:
            self._queue.put_nowait(item)
            return True
        except asyncio.QueueFull:
            return False

    async def dequeue(self, timeout: float = 1.0) -> Optional[dict]:
        try:
            return await asyncio.wait_for(self._queue.get(), timeout=timeout)
        except asyncio.TimeoutError:
            return None

    async def depth(self) -> int:
        return self._queue.qsize()

    async def close(self) -> None:
        pass  # nothing to clean up


# ---------------------------------------------------------------------------
# Redis backend
# ---------------------------------------------------------------------------

class RedisQueue:
    """Redis list-based queue using ``redis.asyncio``."""

    def __init__(self, redis_url: str, queue_key: str = "cw_bridge:attentive_queue"):
        self._queue_key = queue_key
        self._redis_url = redis_url
        self._redis = None  # lazy init

    async def _get_redis(self):
        if self._redis is None:
            try:
                import redis.asyncio as aioredis
            except ImportError:
                raise ImportError(
                    "redis package is required for Redis queue backend. "
                    "Install it with: pip install redis>=5.0.0"
                )
            self._redis = aioredis.from_url(
                self._redis_url,
                decode_responses=True,
            )
            # Verify connectivity
            await self._redis.ping()
            logger.info(f"📋 RedisQueue connected — url={self._redis_url}, key={self._queue_key}")
        return self._redis

    async def enqueue(self, item: dict) -> bool:
        r = await self._get_redis()
        await r.lpush(self._queue_key, json.dumps(item))
        return True

    async def dequeue(self, timeout: float = 1.0) -> Optional[dict]:
        r = await self._get_redis()
        # BRPOP returns (key, value) or None on timeout
        result = await r.brpop(self._queue_key, timeout=int(max(timeout, 1)))
        if result is None:
            return None
        _, raw = result
        return json.loads(raw)

    async def depth(self) -> int:
        r = await self._get_redis()
        return await r.llen(self._queue_key)

    async def close(self) -> None:
        if self._redis is not None:
            await self._redis.aclose()
            self._redis = None


# ---------------------------------------------------------------------------
# Rate limiter protocol + implementations
# ---------------------------------------------------------------------------

class RateLimiter(Protocol):
    """Common interface for rate limiters (local or distributed)."""

    @property
    def rate(self) -> float:
        ...

    async def acquire(self) -> None:
        ...


class TokenBucket:
    """In-process token-bucket rate limiter shared across workers.

    Limits the aggregate throughput to *rate* items per second regardless of
    how many workers are running concurrently.  **Per-process only** — use
    DistributedTokenBucket for multi-instance coordination.
    """

    def __init__(self, rate: float, burst: int = 1):
        """
        Args:
            rate: Sustained tokens per second (e.g., 1.5 = 1.5 items/sec).
            burst: Maximum tokens that can accumulate (allows small bursts).
        """
        self._rate = rate
        self._burst = burst
        self._tokens = float(burst)
        self._last_refill = time.monotonic()
        self._lock = asyncio.Lock()

    @property
    def rate(self) -> float:
        return self._rate

    async def acquire(self) -> None:
        """Wait until a token is available, then consume one."""
        while True:
            async with self._lock:
                self._refill()
                if self._tokens >= 1.0:
                    self._tokens -= 1.0
                    return
                # Calculate how long to wait for the next token
                wait = (1.0 - self._tokens) / self._rate
            await asyncio.sleep(wait)

    def _refill(self) -> None:
        now = time.monotonic()
        elapsed = now - self._last_refill
        self._tokens = min(self._burst, self._tokens + elapsed * self._rate)
        self._last_refill = now


# Lua script for atomic token-bucket operation in Redis.
# KEYS[1] = bucket key
# ARGV[1] = rate (tokens/sec), ARGV[2] = burst (max tokens), ARGV[3] = current time (float seconds)
# Returns: wait time in seconds (0 = token granted immediately, >0 = must sleep this long)
_REDIS_TOKEN_BUCKET_LUA = """
local key = KEYS[1]
local rate = tonumber(ARGV[1])
local burst = tonumber(ARGV[2])
local now = tonumber(ARGV[3])

local data = redis.call('HMGET', key, 'tokens', 'last_refill')
local tokens = tonumber(data[1])
local last_refill = tonumber(data[2])

if tokens == nil then
    -- First call: initialize bucket
    tokens = burst
    last_refill = now
end

-- Refill
local elapsed = now - last_refill
if elapsed > 0 then
    tokens = math.min(burst, tokens + elapsed * rate)
    last_refill = now
end

if tokens >= 1.0 then
    tokens = tokens - 1.0
    redis.call('HMSET', key, 'tokens', tostring(tokens), 'last_refill', tostring(last_refill))
    redis.call('EXPIRE', key, 300)
    return '0'
else
    -- Not enough tokens — report how long to wait
    redis.call('HMSET', key, 'tokens', tostring(tokens), 'last_refill', tostring(last_refill))
    redis.call('EXPIRE', key, 300)
    local wait = (1.0 - tokens) / rate
    return tostring(wait)
end
"""


class DistributedTokenBucket:
    """Redis-backed token bucket for global rate limiting across ECS tasks.

    All instances sharing the same Redis key and bucket name will collectively
    be limited to *rate* items per second.
    """

    def __init__(self, redis_client, rate: float, burst: int = 1, key: str = "cw_bridge:rate_limiter:attentive"):
        """
        Args:
            redis_client: An async Redis client (RedisCluster or Redis).
            rate: Sustained tokens per second across ALL instances.
            burst: Maximum burst capacity.
            key: Redis key for this bucket.
        """
        self._redis = redis_client
        self._rate = rate
        self._burst = burst
        self._key = key
        self._script_sha: Optional[str] = None

    @property
    def rate(self) -> float:
        return self._rate

    async def acquire(self) -> None:
        """Wait until a token is available globally, then consume one."""
        while True:
            wait = await self._try_acquire()
            if wait <= 0:
                return
            await asyncio.sleep(wait)

    async def _try_acquire(self) -> float:
        """Execute the Lua script and return wait time (0 = acquired)."""
        now = time.time()  # wall-clock (consistent across instances)
        try:
            result = await self._redis.eval(
                _REDIS_TOKEN_BUCKET_LUA,
                1,
                self._key,
                str(self._rate),
                str(self._burst),
                str(now),
            )
            return float(result)
        except Exception as exc:
            # If Redis is unreachable, fall through (don't block forever)
            logger.warning(f"⚠️  DistributedTokenBucket Redis error (allowing through): {exc}")
            return 0.0


# ---------------------------------------------------------------------------
# Worker pool
# ---------------------------------------------------------------------------

class WebhookWorkerPool:
    """Manages N async workers that consume from a WebhookQueue."""

    def __init__(
        self,
        queue: WebhookQueue,
        handler: Callable[[dict], Awaitable[None]],
        num_workers: int = 3,
        max_per_second: float = 0,
    ):
        self._queue = queue
        self._handler = handler
        self._num_workers = num_workers
        self._workers: List[asyncio.Task] = []
        self._running = False
        # Rate limiter (0 = unlimited, set externally or created locally)
        self._rate_limiter: Optional[RateLimiter] = None
        if max_per_second > 0:
            self._rate_limiter = TokenBucket(rate=max_per_second, burst=max(1, int(max_per_second)))
        # Counters
        self._total_enqueued = 0
        self._total_processed = 0
        self._total_errors = 0
        self._total_dropped = 0

    @property
    def queue(self) -> WebhookQueue:
        return self._queue

    def set_rate_limiter(self, limiter: RateLimiter) -> None:
        """Replace the rate limiter (e.g., swap local for distributed)."""
        self._rate_limiter = limiter
        logger.info(
            f"🚦 Rate limiter set: {type(limiter).__name__} @ {limiter.rate}/sec"
        )

    async def enqueue(self, item: dict) -> bool:
        """Enqueue an item and track the counter.  Returns False if full."""
        ok = await self._queue.enqueue(item)
        if ok:
            self._total_enqueued += 1
        else:
            self._total_dropped += 1
        return ok

    def start(self) -> None:
        """Spawn worker tasks."""
        if self._running:
            return
        self._running = True
        for i in range(self._num_workers):
            task = asyncio.create_task(self._worker_loop(i), name=f"wh-worker-{i}")
            self._workers.append(task)
        logger.info(f"🚀 WebhookWorkerPool started — {self._num_workers} workers")

    async def stop(self) -> None:
        """Cancel workers and wait for them to finish."""
        self._running = False
        for task in self._workers:
            task.cancel()
        await asyncio.gather(*self._workers, return_exceptions=True)
        self._workers.clear()
        await self._queue.close()
        logger.info("🛑 WebhookWorkerPool stopped")

    async def stats(self) -> dict:
        """Return pool statistics for /status endpoint."""
        return {
            "queue_backend": type(self._queue).__name__,
            "queue_depth": await self._queue.depth(),
            "num_workers": self._num_workers,
            "max_per_second": self._rate_limiter.rate if self._rate_limiter else None,
            "rate_limiter_type": type(self._rate_limiter).__name__ if self._rate_limiter else None,
            "total_enqueued": self._total_enqueued,
            "total_processed": self._total_processed,
            "total_errors": self._total_errors,
            "total_dropped": self._total_dropped,
            "running": self._running,
        }

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    async def _worker_loop(self, worker_id: int) -> None:
        """Single worker: dequeue → acquire token → process → repeat."""
        logger.info(f"Worker {worker_id} started")
        while self._running:
            try:
                item = await self._queue.dequeue(timeout=2.0)
                if item is None:
                    continue  # Timeout — loop back and check _running

                # Throttle: wait for a token before processing
                if self._rate_limiter:
                    await self._rate_limiter.acquire()

                try:
                    await self._handler(item)
                    self._total_processed += 1
                except Exception as exc:
                    self._total_errors += 1
                    logger.error(
                        f"❌ Worker {worker_id}: handler error — {exc}",
                        exc_info=True,
                    )
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error(
                    f"❌ Worker {worker_id}: unexpected error — {exc}",
                    exc_info=True,
                )
                await asyncio.sleep(1)  # Back off before retrying
        logger.info(f"Worker {worker_id} stopped")


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def create_queue(backend: str, **kwargs) -> WebhookQueue:
    """Create a queue instance based on the backend name.

    Args:
        backend: ``"memory"`` or ``"redis"``.
        **kwargs: Backend-specific arguments.
            - memory: ``maxsize`` (int)
            - redis: ``redis_url`` (str), ``queue_key`` (str)
    """
    if backend == "redis":
        redis_url = kwargs.get("redis_url")
        if not redis_url:
            raise ValueError("redis_url is required for Redis queue backend")
        return RedisQueue(
            redis_url=redis_url,
            queue_key=kwargs.get("queue_key", "cw_bridge:attentive_queue"),
        )
    else:
        return InMemoryQueue(maxsize=kwargs.get("maxsize", 5000))


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------
_worker_pool: Optional[WebhookWorkerPool] = None


def get_worker_pool() -> Optional[WebhookWorkerPool]:
    """Return the module-level worker pool (may be None if not started)."""
    return _worker_pool


def set_worker_pool(pool: WebhookWorkerPool) -> None:
    """Set the module-level worker pool singleton."""
    global _worker_pool
    _worker_pool = pool
