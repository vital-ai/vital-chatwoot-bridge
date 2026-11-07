"""MemoryDB is always reached through the cluster client (planning_vital_ai_api/07 §2a)."""

import os

import pytest
import redis.asyncio as aioredis
from pydantic import ValidationError

from vital_chatwoot_bridge.core.config import MemoryDBConfig
from vital_chatwoot_bridge.services import redis_client
from vital_chatwoot_bridge.services.webhook_queue import RedisQueue

LOCAL = os.getenv("MEMORYDB_LOCAL_URL")


def test_standalone_redis_is_refused():
    with pytest.raises(ValidationError, match="cluster client"):
        MemoryDBConfig(url="redis://localhost:6379/1", ssl=False, cluster=False)


def test_always_the_cluster_client():
    client = redis_client.init_redis(MemoryDBConfig(url="redis://localhost:7390", ssl=False))
    assert isinstance(client, aioredis.RedisCluster)
    assert redis_client.address_remap("") is None
    assert redis_client.address_remap("host.docker.internal=127.0.0.1")(("host.docker.internal", 7390)) == ("127.0.0.1", 7390)


@pytest.mark.skipif(not LOCAL, reason="needs the local cluster (vital-saas-api-app/dev/docker-compose.memorydb.yml)")
@pytest.mark.asyncio
async def test_the_webhook_queue_on_a_real_cluster(monkeypatch):
    monkeypatch.setenv("REDIS_DEV_ADDRESS_REMAP", "host.docker.internal=127.0.0.1")
    q = RedisQueue(redis_url=LOCAL, queue_key="cw_bridge:pytest:{queue}:attentive")
    try:
        assert await q.enqueue({"n": 1})
        assert await q.depth() == 1
        assert await q.dequeue(timeout=1) == {"n": 1}
    finally:
        await q.close()
