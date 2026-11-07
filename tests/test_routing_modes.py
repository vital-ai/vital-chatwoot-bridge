"""Account modes, routes, pauses, delivery reports, idempotent writes and the conversation operations.

single mode is the bridge's original behaviour; multi mode takes routes from route files, one Chatwoot account per
application, with the account in every management path. Chatwoot and the agents are fakes here.
"""

import asyncio
import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import fakeredis
import httpx
import pytest
from fastapi.testclient import TestClient

from vital_chatwoot_bridge.api import chatwoot_management_routes as mgmt
from vital_chatwoot_bridge.chatwoot.api_client import ChatwootAPIClient
from vital_chatwoot_bridge.client.client import ChatwootBridgeClient
from vital_chatwoot_bridge.core.auth_models import AuthenticatedUser
from vital_chatwoot_bridge.core.config import AgentConfig, BotConfig, InboxMapping, get_settings
from vital_chatwoot_bridge.handlers.webhook_handler import WebhookHandler
from vital_chatwoot_bridge.main import app
from vital_chatwoot_bridge.routing import deliveries, idempotency, pauses, routes
from vital_chatwoot_bridge.routing.idempotency import IdempotencyStore, InProgress
from vital_chatwoot_bridge.routing.pauses import PauseStore
from vital_chatwoot_bridge.routing.routes import RouteFileError, RouteTable
from vital_chatwoot_bridge.utils.jwt_verify import get_current_user

ROUTES_A = """
app: alpha
chatwoot_account_id: 3
bot: alpha-bot
inboxes:
  - inbox_id: 12
    name: support-email
    retries: 2
    agent: {agent_id: alpha-support, websocket_url: "ws://alpha-agent/ws", timeout_seconds: 5}
"""
ROUTES_B = """
app: beta
chatwoot_account_id: 4
inboxes:
  - {inbox_id: 7, name: help, agent: {agent_id: beta-support, websocket_url: "ws://beta-agent/ws"}}
"""


def settings(mode="multi", files=(), tokens=None, **extra):
    base = dict(chatwoot_account_mode=mode, routing_files=list(files), chatwoot_account_tokens=tokens or {3: "t3", 4: "t4"},
                chatwoot_user_access_token="", chatwoot_account_id="1", inbox_agent_mappings=[],
                bots={"alpha-bot": BotConfig(access_token="alpha-signing-key")})
    return SimpleNamespace(**{**base, **extra})


@pytest.fixture
def route_files(tmp_path):
    (tmp_path / "alpha").mkdir()
    (tmp_path / "beta").mkdir()
    (tmp_path / "alpha" / "chatwoot_bridge.yml").write_text(ROUTES_A)
    (tmp_path / "beta" / "chatwoot_bridge.yml").write_text(ROUTES_B)
    return tmp_path


@pytest.fixture
def multi(route_files, monkeypatch):
    """The bridge in multi mode, with fakeredis behind pauses and idempotency keys, and reports captured."""
    table = RouteTable(settings(files=[str(route_files)]))
    routes.set_route_table(table)
    redis = fakeredis.FakeAsyncRedis(decode_responses=True)
    pauses.set_pause_store(PauseStore(redis, "cw_bridge:test:"))
    idempotency.set_idempotency_store(IdempotencyStore(redis, "cw_bridge:test:", 3600))
    reports = []

    class Reporter(deliveries.DeliveryReporter):
        async def report(self, **kw):
            reports.append(kw)

    deliveries.set_reporter(Reporter(enabled=True, report_url="http://reports.test"))
    monkeypatch.setattr(get_settings(), "chatwoot_account_mode", "multi")
    app.dependency_overrides[get_current_user] = lambda: AuthenticatedUser(
        client_id="caller", subject="svc", expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        issued_at=datetime.now(timezone.utc))
    yield SimpleNamespace(table=table, redis=redis, reports=reports, files=route_files)
    app.dependency_overrides.clear()
    for reset in (routes.set_route_table, pauses.set_pause_store, idempotency.set_idempotency_store, deliveries.set_reporter):
        reset(None)


# --- the route table ----------------------------------------------------------------------------------------------

def test_route_files_give_one_route_per_account_and_inbox(route_files):
    table = RouteTable(settings(files=[str(route_files)]))
    assert table.accounts() == [3, 4]
    r = table.get(3, "12")
    assert (r.app, r.agent.agent_id, r.retries, r.inbox_name) == ("alpha", "alpha-support", 2, "support-email")
    assert table.get(4, "12") is None and table.get(None, "12") is None          # multi: the account always counts
    assert table.webhook_secret(3, "12") == "alpha-signing-key" and table.webhook_secret(4, "7") is None


def test_a_bad_route_file_is_refused_and_the_routes_stay(route_files):
    table = RouteTable(settings(files=[str(route_files)]))
    (route_files / "beta" / "chatwoot_bridge.yml").write_text(ROUTES_B.replace("chatwoot_account_id: 4", "chatwoot_account_id: 3"))
    with pytest.raises(RouteFileError, match="already alpha's"):
        table.load()
    assert table.accounts() == [3, 4] and table.get(4, "7")                      # nothing changed
    (route_files / "beta" / "chatwoot_bridge.yml").write_text("app: beta\nchatwoot_account_id: 4\ninboxes: []\n")
    with pytest.raises(RouteFileError):
        table.load()
    (route_files / "beta" / "chatwoot_bridge.yml").write_text(ROUTES_A.replace("app: alpha", "app: beta"))
    with pytest.raises(RouteFileError, match="already alpha's"):
        table.load()


def test_every_routed_account_needs_a_token(route_files):
    with pytest.raises(RouteFileError, match=r"no API token for Chatwoot account\(s\) \[4\]"):
        RouteTable(settings(files=[str(route_files)], tokens={3: "t3"}))


def test_single_mode_routes_come_from_settings_as_before():
    agent = AgentConfig(agent_id="a1", websocket_url="ws://a1/ws")
    table = RouteTable(settings(mode="single", chatwoot_account_id="9",
                                inbox_agent_mappings=[InboxMapping(inbox_id="5", inbox_name="web", agent_config=agent)]))
    assert table.accounts() == [9]
    assert table.get(None, "5").agent.agent_id == "a1" and table.get(9, "5") and table.get(8, "5") is None


# --- pauses and idempotency keys ----------------------------------------------------------------------------------

async def test_a_pause_is_kept_until_resumed():
    store = PauseStore(fakeredis.FakeAsyncRedis(decode_responses=True), "cw_bridge:t:")
    assert await store.get(3, "12") is None
    await store.pause(3, "12", "pat", "agent misfiling")
    assert (await store.get(3, "12"))["reason"] == "agent misfiling"
    assert list(await store.all()) == [(3, "12")]
    assert await store.resume(3, "12", "pat") is True
    assert await store.get(3, "12") is None and await store.all() == {}


async def test_an_idempotency_key_writes_once():
    store = IdempotencyStore(fakeredis.FakeAsyncRedis(decode_responses=True), "cw_bridge:t:", 60)
    calls = []

    async def write():
        calls.append(1)
        return {"id": len(calls)}

    assert await store.run("3:reply", "k1", write) == ({"id": 1}, False)
    assert await store.run("3:reply", "k1", write) == ({"id": 1}, True)
    assert await store.run("3:note", "k1", write) == ({"id": 2}, False)          # another scope, another write

    async def boom():
        raise RuntimeError("chatwoot down")

    with pytest.raises(RuntimeError):
        await store.run("3:reply", "k2", boom)
    assert await store.run("3:reply", "k2", write) == ({"id": 3}, False)         # a failed write can be retried

    slow = asyncio.Event()

    async def held():
        await slow.wait()
        return {"id": "held"}

    first = asyncio.create_task(store.run("3:reply", "k3", held))
    await asyncio.sleep(0)
    with pytest.raises(InProgress):
        await store.run("3:reply", "k3", write)
    slow.set()
    assert (await first)[0] == {"id": "held"}


# --- the management API, by account -------------------------------------------------------------------------------

class FakeChatwoot:
    def __init__(self):
        self.sent, self.labels, self.toggled, self.assigned = [], {}, [], []
        self.messages = {(3, 42, 900): {"id": 900, "message_type": 0, "content": "hi", "inbox_id": 12,
                                        "sender": {"id": 5, "name": "M", "email": "m@example.com"},
                                        "attachments": [{"id": 1, "data_url": "http://cw.test/rails/blob/1", "file_size": 10}],
                                        "created_at": 1_700_000_000}}

    async def list_contacts(self, account, page=1, sort=None):
        return {"payload": [{"id": 1, "account": account}], "meta": {}}

    async def filter_contacts(self, account, key, value, page=1):
        return {"payload": [{"id": 2, "account": account, key: value}], "meta": {"count": 1}}

    async def send_message_raw(self, account, conversation_id, payload, attachments=None):
        self.sent.append((account, conversation_id, payload))
        return {"id": 1000 + len(self.sent), "private": payload["private"], "echo_id": payload.get("echo_id")}

    async def conversation_labels(self, account, cid):
        return list(self.labels.get((account, cid), []))

    async def set_conversation_labels(self, account, cid, labels):
        self.labels[(account, cid)] = list(labels)
        return list(labels)

    async def toggle_conversation_status(self, account, cid, status, snoozed_until=None):
        self.toggled.append((account, cid, status))
        return {"current_status": status}

    async def assign_conversation(self, account, cid, assignee_id=None, team_id=None):
        self.assigned.append((account, cid, assignee_id, team_id))
        return {"id": assignee_id}

    async def get_message(self, account, cid, mid):
        return self.messages.get((account, cid, mid))

    async def get_conversation_raw(self, account, cid):
        return {"id": cid, "inbox_id": 12, "channel": "Channel::Email", "additional_attributes": {}}

    async def open_attachment(self, url):
        class Stream:
            status_code, headers = 200, {"content-type": "image/png", "content-length": "4"}

            async def aiter_bytes(self):
                yield b"\x89PNG"

            async def aclose(self):
                pass
        return Stream()


@pytest.fixture
def chatwoot(monkeypatch):
    fake = FakeChatwoot()

    async def get():
        return fake

    monkeypatch.setattr(mgmt, "get_chatwoot_client", get)
    import vital_chatwoot_bridge.api.routing_routes as rr
    monkeypatch.setattr(rr, "get_chatwoot_client", get)
    return fake


def test_multi_mode_needs_the_account_in_the_path(multi, chatwoot):
    c = TestClient(app)
    r = c.get("/api/v1/chatwoot/contacts")
    assert r.status_code == 400 and "account required" in r.json()["detail"]
    assert c.get("/api/v1/chatwoot/accounts/3/contacts").json()["data"][0]["account"] == 3
    assert c.get("/api/v1/chatwoot/accounts/4/contacts").json()["data"][0]["account"] == 4
    assert c.get("/api/v1/chatwoot/accounts/5/contacts").status_code == 404            # no routes for it


def test_single_mode_keeps_the_old_paths(chatwoot, monkeypatch):
    agent = AgentConfig(agent_id="a1", websocket_url="ws://a1/ws")
    routes.set_route_table(RouteTable(settings(mode="single", chatwoot_account_id="9",
                                               inbox_agent_mappings=[InboxMapping(inbox_id="5", agent_config=agent)])))
    monkeypatch.setattr(get_settings(), "chatwoot_account_mode", "single")
    monkeypatch.setattr(get_settings(), "chatwoot_account_id", "9")
    app.dependency_overrides[get_current_user] = lambda: AuthenticatedUser(
        client_id="c", subject="s", expires_at=datetime.now(timezone.utc), issued_at=datetime.now(timezone.utc))
    try:
        c = TestClient(app)
        assert c.get("/api/v1/chatwoot/contacts").json()["data"][0]["account"] == 9
        assert c.get("/api/v1/chatwoot/accounts/9/contacts").json()["data"][0]["account"] == 9
        assert c.get("/api/v1/chatwoot/accounts/3/contacts").status_code == 404
    finally:
        app.dependency_overrides.clear()
        routes.set_route_table(None)


def test_contacts_by_email_or_member_id(multi, chatwoot):
    c = TestClient(app)
    by_email = c.get("/api/v1/chatwoot/accounts/3/contacts?email=M@Example.com").json()["data"][0]
    assert by_email["email"] == "m@example.com"
    assert c.get("/api/v1/chatwoot/accounts/3/contacts?vital_member_id=abc").json()["data"][0]["vital_member_id"] == "abc"


def test_notes_and_replies_are_written_once_per_key(multi, chatwoot):
    c = TestClient(app)
    url = "/api/v1/chatwoot/accounts/3/conversations/42"
    body = {"content": "Translation: hello", "content_attributes": {"vital": {"kind": "translation", "of_message": 900}}}
    first = c.post(f"{url}/notes", json=body, headers={"Idempotency-Key": "n-1"}).json()["data"]
    again = c.post(f"{url}/notes", json=body, headers={"Idempotency-Key": "n-1"}).json()["data"]
    assert first["message"] == again["message"] and again["replayed"] is True and len(chatwoot.sent) == 1
    account, cid, payload = chatwoot.sent[0]
    assert (account, cid, payload["private"], payload["echo_id"]) == (3, 42, True, "n-1")
    assert payload["content_attributes"]["vital"]["kind"] == "translation"
    reply = c.post(f"{url}/replies", json={"content": "Hola"}, headers={"Idempotency-Key": "n-1"}).json()["data"]
    assert reply["replayed"] is False and chatwoot.sent[1][2]["private"] is False         # notes and replies apart
    c.post(f"{url}/replies", json={"content": "Hola"}, headers={"Idempotency-Key": "n-1"})
    assert len(chatwoot.sent) == 2


def test_labels_are_merged_and_removed(multi, chatwoot):
    c = TestClient(app)
    url = "/api/v1/chatwoot/accounts/3/conversations/42/labels"
    chatwoot.labels[(3, 42)] = ["tracked"]
    assert c.post(url, json={"labels": ["Spam"]}).json()["data"]["labels"] == ["tracked", "spam"]
    assert c.post(url, json={"labels": ["spam"]}).json()["data"]["labels"] == ["tracked", "spam"]
    assert c.delete(f"{url}/tracked").json()["data"]["labels"] == ["spam"]
    assert c.post(url, json={"labels": ["no spaces"]}).status_code == 422


def test_status_assignment_and_attachments(multi, chatwoot):
    c = TestClient(app)
    url = "/api/v1/chatwoot/accounts/4/conversations/42"
    assert c.post(f"{url}/status", json={"status": "resolved"}).json()["data"]["current_status"] == "resolved"
    assert c.post(f"{url}/status", json={"status": "closed"}).status_code == 422
    assert c.post(f"{url}/assignee", json={"assignee_id": 7}).status_code == 200
    assert chatwoot.toggled == [(4, 42, "resolved")] and chatwoot.assigned == [(4, 42, 7, None)]
    att = c.get("/api/v1/chatwoot/accounts/3/conversations/42/messages/900/attachments/1")
    assert att.status_code == 200 and att.content == b"\x89PNG" and att.headers["cache-control"] == "private, no-store"
    assert c.get("/api/v1/chatwoot/accounts/3/conversations/42/messages/900/attachments/2").status_code == 404
    assert c.get("/api/v1/chatwoot/accounts/4/conversations/42/messages/900/attachments/1").status_code == 404


async def test_attachment_redirects_never_carry_the_token(monkeypatch):
    seen = []

    def handler(request: httpx.Request):
        seen.append((request.url.host, request.headers.get("api_access_token")))
        if request.url.host == "cw.test":
            return httpx.Response(302, headers={"location": "https://storage.test/bucket/obj?sig=1"})
        return httpx.Response(200, content=b"data", headers={"content-type": "application/pdf"})

    s = get_settings()
    monkeypatch.setattr(s, "chatwoot_base_url", "http://cw.test")
    monkeypatch.setattr(s, "chatwoot_user_access_token", "secret-token")
    client = ChatwootAPIClient()
    client.attachment_transport = httpx.MockTransport(handler)
    stream = await client.open_attachment("http://cw.test/rails/active_storage/blobs/redirect/x/file.pdf")
    body = b"".join([chunk async for chunk in stream.aiter_bytes()])
    await stream.aclose()
    await client.close()
    assert body == b"data"
    assert seen == [("cw.test", "secret-token"), ("storage.test", None)]


def test_the_api_token_follows_the_account_in_the_url(monkeypatch):
    monkeypatch.setattr(get_settings(), "chatwoot_account_tokens", {3: "t3"})
    client = ChatwootAPIClient()
    assert client.token_for("http://cw/api/v1/accounts/3/conversations/1") == "t3"
    assert client.token_for("http://cw/api/v1/accounts/4/conversations/1") is None    # falls back to the default token
    assert client.token_for("http://cw/api/v1/accounts/31/conversations") is None


# --- the webhook: routes, pauses, retries, reports ----------------------------------------------------------------

class FakeAgent:
    def __init__(self, fail_times=0):
        self.fail_times, self.calls = fail_times, []

    async def send_message_with_responses(self, url, message, timeout=30, max_responses=5, strict=False):
        self.calls.append((url, message.content))
        if len(self.calls) <= self.fail_times:
            raise ConnectionError("agent unreachable")
        return []                        # filed silently: received, nothing to say


def event(account=3, inbox=12, message_id=900):
    return {"event": "message_created", "id": message_id, "content": "my purchase didn't restore",
            "created_at": "2026-11-07T10:00:00Z", "message_type": "incoming",
            "sender": {"id": 5, "name": "M", "email": "m@example.com", "type": "contact"},
            "conversation": {"id": 42, "inbox_id": inbox, "channel": "Channel::Email"},
            "account": {"id": account}, "inbox": {"id": inbox}}


@pytest.fixture
def handler(multi, monkeypatch):
    h = WebhookHandler(api_client=None)
    h.websocket_client = FakeAgent()
    monkeypatch.setattr(asyncio, "sleep", _no_sleep)
    return h


async def _no_sleep(*_a, **_k):
    return None


async def test_a_message_reaches_its_accounts_agent_and_is_reported(handler, multi):
    out = await handler.handle_webhook(event())
    assert out["status"] == "processed_no_response"
    assert handler.websocket_client.calls == [("ws://alpha-agent/ws", "my purchase didn't restore")]
    assert multi.reports[-1] | {} == {"app": "alpha", "account_id": 3, "inbox_id": "12", "conversation_id": 42,
                                      "message_id": 900, "agent_id": "alpha-support", "status": "delivered", "attempts": 1}
    assert deliveries.get_reporter().health["alpha-support"].delivered == 1


async def test_a_failing_agent_is_retried_then_reported_failed(handler, multi):
    handler.websocket_client = FakeAgent(fail_times=99)
    await handler.handle_webhook(event())
    assert len(handler.websocket_client.calls) == 3                                     # 1 + the route's 2 retries
    last = multi.reports[-1]
    assert (last["status"], last["attempts"]) == ("failed", 3) and "agent unreachable" in last["error"]
    health = deliveries.get_reporter().health["alpha-support"]
    assert health.consecutive_failures == 3 and health.last_error
    handler.websocket_client = FakeAgent(fail_times=1)
    await handler.handle_webhook(event(message_id=901))
    assert (multi.reports[-1]["status"], multi.reports[-1]["attempts"]) == ("delivered", 2)
    assert deliveries.get_reporter().health["alpha-support"].consecutive_failures == 0


async def test_a_paused_inbox_holds_its_messages_and_reload_doesnt_resume_it(handler, multi):
    await pauses.get_pause_store().pause(3, "12", "pat", "agent misfiling")
    multi.table.load()                                                                  # a redeploy reloads the routes
    out = await handler.handle_webhook(event())
    assert out["status"] == "ignored" and handler.websocket_client.calls == []
    assert multi.reports[-1]["status"] == "paused"
    await pauses.get_pause_store().resume(3, "12", "pat")
    await handler.handle_webhook(event(message_id=902))
    assert multi.reports[-1]["status"] == "delivered"


async def test_an_unrouted_inbox_or_account_reaches_no_agent(handler, multi):
    for e in (event(inbox=99), event(account=4, inbox=12), event(account=8, inbox=7)):
        out = await handler.handle_webhook(e)
        assert out["status"] == "ignored"
    assert handler.websocket_client.calls == [] and handler.unrouted == 3
    assert [r["status"] for r in multi.reports] == ["unrouted"] * 3


# --- the routing API ----------------------------------------------------------------------------------------------

def test_routes_pause_resume_and_reload_through_the_api(multi):
    c = TestClient(app)
    listed = c.get("/api/v1/routes").json()
    assert listed["mode"] == "multi" and [(r["account_id"], r["inbox_id"]) for r in listed["routes"]] == [(3, "12"), (4, "7")]
    assert c.post("/api/v1/routes/3/12/pause", json={"by": "pat", "reason": "misfiling"}).status_code == 200
    assert c.post("/api/v1/routes/3/99/pause", json={"by": "pat", "reason": "misfiling"}).status_code == 404
    assert c.get("/api/v1/routes").json()["routes"][0]["paused"]["by"] == "pat"
    (multi.files / "beta" / "chatwoot_bridge.yml").write_text("not: [valid")
    r = c.post("/api/v1/routes/reload")
    assert r.status_code == 422 and "nothing changed" in r.json()["detail"]
    (multi.files / "beta" / "chatwoot_bridge.yml").write_text(ROUTES_B)
    assert c.post("/api/v1/routes/reload").json() == {"reloaded": True, "routes": 2, "accounts": 2}
    assert c.get("/api/v1/routes").json()["routes"][0]["paused"]["reason"] == "misfiling"      # still paused
    assert c.post("/api/v1/routes/3/12/resume", json={"by": "pat"}).json()["was_paused"] is True
    status = c.get("/status").json()
    assert status["routing"]["mode"] == "multi" and status["routing"]["paused"] == 0
    assert all("agent_url" not in a for a in status["agents"])


def test_a_failed_message_can_be_handed_to_its_agent_again(multi, chatwoot, monkeypatch):
    import vital_chatwoot_bridge.main as main
    h = WebhookHandler(api_client=None)
    h.websocket_client = FakeAgent()
    monkeypatch.setattr(main, "webhook_handler", h)
    c = TestClient(app)
    r = c.post("/api/v1/deliveries/900/retry", json={"account_id": 3, "conversation_id": 42})
    assert r.status_code == 200 and h.websocket_client.calls == [("ws://alpha-agent/ws", "hi")]
    assert multi.reports[-1]["status"] == "delivered" and multi.reports[-1]["message_id"] == 900
    assert c.post("/api/v1/deliveries/900/retry", json={"conversation_id": 42}).status_code == 400
    assert c.post("/api/v1/deliveries/901/retry", json={"account_id": 3, "conversation_id": 42}).status_code == 422


# --- the client library -------------------------------------------------------------------------------------------

async def test_the_client_scopes_calls_to_an_account_and_sends_the_key():
    seen = []

    def handler(request: httpx.Request):
        seen.append((request.method, request.url.path, request.headers.get("idempotency-key"),
                     json.loads(request.content or b"null")))
        return httpx.Response(201, json={"success": True, "data": {"message": {"id": 1}, "replayed": False}})

    class Auth:
        async def get_token(self):
            return "tok"

    client = ChatwootBridgeClient("http://bridge.test", "http://kc", "r", "c", "s")
    client.auth = Auth()
    client._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    acct = client.for_account(3)
    await acct.add_note(42, "Translation: hi", {"vital": {"kind": "translation"}}, idempotency_key="k-1")
    await acct.reply(42, "Hola")
    await client.pause_inbox(3, 12, "pat", "misfiling")
    await client.close()
    assert seen[0][:3] == ("POST", "/api/v1/chatwoot/accounts/3/conversations/42/notes", "k-1")
    assert seen[1][:3] == ("POST", "/api/v1/chatwoot/accounts/3/conversations/42/replies", None)
    assert seen[2][1] == "/api/v1/routes/3/12/pause" and seen[2][3] == {"by": "pat", "reason": "misfiling"}
