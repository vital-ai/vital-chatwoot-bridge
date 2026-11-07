"""MemoryDB (Redis in cluster mode) is always reached through the cluster client. The live tests need a local
cluster-mode Redis at MEMORYDB_LOCAL_URL (one node holding every slot is enough)."""

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


@pytest.mark.skipif(not LOCAL, reason="needs a local cluster-mode Redis (MEMORYDB_LOCAL_URL)")
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


@pytest.mark.skipif(not LOCAL, reason="needs a local cluster-mode Redis (MEMORYDB_LOCAL_URL)")
@pytest.mark.asyncio
async def test_pauses_and_idempotency_keys_on_a_real_cluster():
    import uuid

    from vital_chatwoot_bridge.routing.idempotency import IdempotencyStore
    from vital_chatwoot_bridge.routing.pauses import PauseStore

    client = redis_client.cluster_client(LOCAL, remap="host.docker.internal=127.0.0.1")
    prefix = f"cw_bridge:pytest-{uuid.uuid4().hex[:8]}:"
    try:
        pauses = PauseStore(client, prefix)
        await pauses.pause(3, "12", "pat", "agent misfiling")
        assert (await pauses.get(3, "12"))["by"] == "pat" and list(await pauses.all()) == [(3, "12")]
        assert await pauses.resume(3, "12", "pat") and await pauses.all() == {}
        keys = IdempotencyStore(client, prefix, 60)
        calls = []

        async def write():
            calls.append(1)
            return {"id": 1}

        assert await keys.run("3:reply", "k", write) == ({"id": 1}, False)
        assert await keys.run("3:reply", "k", write) == ({"id": 1}, True) and len(calls) == 1
    finally:
        for key in [k async for k in client.scan_iter(match=f"{prefix}*")]:
            await client.delete(key)
        await client.aclose()
