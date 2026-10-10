"""
Tests for AimpMessageClient against a scripted contract v2 (vital-agent.v2) agent.

The scripted server stands in for an agent on vital-agent-container-sdk 0.2.0: it
answers each AIMP request with handler output, then ``sdk.status done``, and closes
1000 on the client's ``close`` intent.
"""

import asyncio
import json
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, List, Optional

import pytest
from websockets.asyncio.server import ServerConnection, serve
from websockets.typing import Subprotocol

from vital_agent_container_client import SUBPROTOCOL, VitalAgentContainerClient
from vital_agent_container_client.protocol import INTENT_PROPERTY, URI_PROPERTY

from vital_chatwoot_bridge.agents.aimp_message_client import AimpMessageClient
from vital_chatwoot_bridge.core.models import (
    BridgeToAgentMessage,
    MessageContext,
    MessageSender,
)

AIMP = "http://vital.ai/ontology/vital-aimp#"

Script = Callable[[ServerConnection, List[Any]], Awaitable[None]]


def agent_reply(text: str, direct: bool = True) -> List[dict]:
    return [
        {
            "type": "http://vital.ai/ontology/vital-aimp#AIMPIntent",
            "URI": "urn:reply",
            f"{AIMP}isDirectMessageResponse": direct,
        },
        {
            "type": "http://vital.ai/ontology/vital-aimp#AgentMessageContent",
            "URI": "urn:content",
            f"{AIMP}hasMessageContentJSON": json.dumps({"message_body": text}),
        },
    ]


async def recv(ws: ServerConnection, received: List[Any]) -> List[Any]:
    message = json.loads(await asyncio.wait_for(ws.recv(), 5))
    received.append(message)
    return message


async def done(ws: ServerConnection, request: List[Any]) -> None:
    await ws.send(json.dumps({
        "type": "sdk.status", "status": "done", "in_reply_to": request[0][URI_PROPERTY],
    }))


async def expect_close_intent(ws: ServerConnection, received: List[Any]) -> None:
    intent = await recv(ws, received)
    assert intent[0][INTENT_PROPERTY] == "close"
    await ws.close(code=1000, reason="Closed by client request")


@pytest.fixture
async def agent():
    """Start a scripted agent; returns ``start(script, subprotocols=...) -> (url, received)``."""
    servers = []

    async def start(script: Script, subprotocols: Optional[List[str]] = None):
        received: List[Any] = []

        async def handler(ws: ServerConnection) -> None:
            await script(ws, received)
            await ws.wait_closed()

        offered = [SUBPROTOCOL] if subprotocols is None else subprotocols
        server = await serve(
            handler, "127.0.0.1", 0,
            subprotocols=[Subprotocol(p) for p in offered] or None,
        )
        servers.append(server)
        port = server.sockets[0].getsockname()[1]
        return f"http://127.0.0.1:{port}", received

    yield start
    for server in servers:
        server.close()
        await server.wait_closed()


@pytest.fixture
def client(monkeypatch):
    async def healthy(self):
        return {"status": "ok"}

    monkeypatch.setattr(VitalAgentContainerClient, "check_health", healthy)
    c = AimpMessageClient()
    c.jwt_manager = None
    return c


def bridge_message() -> BridgeToAgentMessage:
    return BridgeToAgentMessage(
        message_id="m1",
        inbox_id="7",
        inbox_name="CarlyAgent",
        conversation_id=42,
        content="hello",
        sender=MessageSender(id="c1", name="Pat", phone="+15555550100"),
        context=MessageContext(
            channel="Channel::TwilioSms", created_at=datetime.now(timezone.utc)
        ),
    )


async def test_reply_then_done(agent, client):
    async def script(ws, received):
        request = await recv(ws, received)
        await ws.send(json.dumps(agent_reply("hi there")))
        await done(ws, request)
        await expect_close_intent(ws, received)

    url, received = await agent(script)
    responses = await client.send_message_with_responses(url, bridge_message(), timeout=5)

    assert [r.content for r in responses] == ["hi there"]
    assert responses[0].deliver_to_chatwoot is True
    assert responses[0].conversation_id == 42
    # The bridge's own URIGenerator URI is kept, not replaced by the client's urn:uuid
    assert received[0][0][URI_PROPERTY].startswith("http://vital.ai/")
    assert len(received) == 2


async def test_handler_error_close_keeps_earlier_replies(agent, client):
    async def script(ws, received):
        await recv(ws, received)
        await recv(ws, received)  # close intent, sent right after the request
        await ws.send(json.dumps(agent_reply("partial")))
        await ws.close(code=1011, reason="Handler error")

    url, _ = await agent(script)
    responses = await client.send_message_with_responses(url, bridge_message(), timeout=5)

    assert [r.content for r in responses] == ["partial"]


async def test_client_timeout_interrupts(agent, client):
    async def script(ws, received):
        request = await recv(ws, received)
        await recv(ws, received)  # close intent
        interrupt = await recv(ws, received)
        assert interrupt[0][INTENT_PROPERTY] == "interrupt"
        await ws.send(json.dumps({
            "type": "sdk.status", "status": "interrupted",
            "in_reply_to": request[0][URI_PROPERTY],
        }))
        # close was requested earlier: the server closes right after "interrupted"
        await ws.close(code=1000, reason="Closed by client request")

    url, received = await agent(script)
    responses = await client.send_message_with_responses(url, bridge_message(), timeout=1)

    assert responses == []
    assert received[2][0][INTENT_PROPERTY] == "interrupt"


async def test_pre_v2_agent_returns_no_responses(agent, client):
    async def script(ws, received):
        pass

    url, received = await agent(script, subprotocols=[])
    responses = await client.send_message_with_responses(url, bridge_message(), timeout=5)

    assert responses == []
    assert received == []


async def test_chunked_reply_is_dropped(agent, client):
    async def script(ws, received):
        request = await recv(ws, received)
        await ws.send(json.dumps({"aimp_chunk": {"index": 0, "data": "..."}}))
        await ws.send(json.dumps(agent_reply("small reply")))
        await done(ws, request)
        await expect_close_intent(ws, received)

    url, _ = await agent(script)
    responses = await client.send_message_with_responses(url, bridge_message(), timeout=5)

    assert [r.content for r in responses] == ["small reply"]
