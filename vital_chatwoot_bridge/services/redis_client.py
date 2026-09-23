"""
Shared Redis (MemoryDB) client singleton.

Provides a RedisCluster connection configured from CW_BRIDGE__memorydb__* env vars.
Cluster mode is required because the MemoryDB cluster has cluster_enabled=1.
Set ``CW_BRIDGE__memorydb__cluster=false`` to use a standalone Redis locally.

Usage:
    from vital_chatwoot_bridge.services.redis_client import get_redis, close_redis

    r = get_redis()
    await r.ping()
"""

import logging
from typing import Optional, Union
from urllib.parse import urlparse

import redis.asyncio as aioredis

from vital_chatwoot_bridge.core.config import MemoryDBConfig

logger = logging.getLogger(__name__)

RedisClient = Union[aioredis.RedisCluster, aioredis.Redis]

_client: Optional[RedisClient] = None


def init_redis(config: MemoryDBConfig) -> RedisClient:
    """Initialize the global Redis client from MemoryDBConfig.

    Call once during application lifespan startup.
    """
    global _client

    parsed = urlparse(config.url)
    if not config.cluster:
        db = int(parsed.path.lstrip("/") or 0)  # redis://host:port/<db>
        _client = aioredis.Redis(
            host=parsed.hostname,
            port=parsed.port or 6379,
            db=db,
            username=parsed.username,
            password=parsed.password,
            ssl=config.ssl,
            ssl_cert_reqs=config.ssl_cert_reqs,
            decode_responses=True,
        )
        logger.info(
            f"🗄️  REDIS: Initialized standalone Redis — host={parsed.hostname}:{parsed.port or 6379}, "
            f"db={db}, ssl={config.ssl}"
        )
        return _client

    _client = aioredis.RedisCluster(
        host=parsed.hostname,
        port=parsed.port or 6379,
        username=parsed.username or "default",
        password=parsed.password,
        ssl=config.ssl,
        ssl_cert_reqs=config.ssl_cert_reqs,
        decode_responses=True,
    )
    logger.info(
        f"🗄️  REDIS: Initialized RedisCluster — host={parsed.hostname}:{parsed.port}, "
        f"ssl={config.ssl}"
    )
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
