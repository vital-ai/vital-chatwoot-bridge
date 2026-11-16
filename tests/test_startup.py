"""A start-up that fails shows its own error, not one from the shutdown that follows."""

import asyncio

import pytest

from vital_chatwoot_bridge import main


def test_a_failed_start_raises_its_own_error(monkeypatch):
    async def refused():
        raise RuntimeError("chatwoot unreachable")

    monkeypatch.setattr(main, "get_chatwoot_client", refused)

    async def start():
        async with main.lifespan(main.app):
            pass

    with pytest.raises(RuntimeError, match="chatwoot unreachable"):
        asyncio.run(start())
