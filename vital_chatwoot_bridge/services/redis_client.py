"""
Shared Redis (MemoryDB) client singleton.

MemoryDB runs in cluster mode, so this is always Redis's cluster client, never a standalone ``Redis``. Locally, run
Redis in cluster mode as well (one node holding every slot is enough). Configured from CW_BRIDGE__memorydb__* env vars.

Usage:
    from vital_chatwoot_bridge.services.redis_client import get_redis, close_redis

    r = get_redis()
    await r.ping()
"""

import logging
from typing import Callable, Optional, Tuple
from urllib.parse import urlparse

import redis.asyncio as aioredis

from vital_chatwoot_bridge.core.config import MemoryDBConfig

logger = logging.getLogger(__name__)

RedisClient = aioredis.RedisCluster

_client: Optional[RedisClient] = None


def address_remap(spec: str) -> Optional[Callable[[Tuple[str, int]], Tuple[str, int]]]:
    """``"a=b,c=d"``: announced host ``a`` is reached at ``b`` (local development only). Empty: none."""
    pairs = dict(p.split("=", 1) for p in (x.strip() for x in spec.split(",")) if "=" in p)
    if not pairs:
        return None
    return lambda addr: (pairs.get(addr[0], addr[0]), addr[1])


def cluster_client(url: str, *, ssl: bool = False, ssl_cert_reqs: str = "none", remap: str = "",
                   username: Optional[str] = None) -> RedisClient:
    """A cluster client for ``url``. Every MemoryDB connection in the bridge is made here."""
    parsed = urlparse(url)
    return aioredis.RedisCluster(
        host=parsed.hostname,
        port=parsed.port or 6379,
        username=username or parsed.username or "default",
        password=parsed.password,
        ssl=ssl or parsed.scheme == "rediss",
        ssl_cert_reqs=ssl_cert_reqs,
        decode_responses=True,
        address_remap=address_remap(remap),
    )


def init_redis(config: MemoryDBConfig) -> RedisClient:
    """Initialize the global cluster client from MemoryDBConfig. Call once during application lifespan startup."""
    global _client
    _client = cluster_client(config.url, ssl=config.ssl, ssl_cert_reqs=config.ssl_cert_reqs, remap=config.address_remap)
    parsed = urlparse(config.url)
    logger.info(f"🗄️  REDIS: Initialized RedisCluster — host={parsed.hostname}:{parsed.port}, ssl={config.ssl}")
    return _client


def get_redis() -> Optional[RedisClient]:
    """Return the global Redis client (None if not initialized)."""
    return _client


async def close_redis() -> None:
    """Close the global Redis client."""
    global _client
    if _client is not None:
        await _client.aclose()
        logger.info("🗄️  REDIS: Connection closed")
        _client = None
