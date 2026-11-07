"""The conversation operations against a real Chatwoot, in multi-account mode.

Skipped unless CHATWOOT_CONTRACT_ENV names an env file with the bridge's multi-mode settings: the Chatwoot base URL,
an account token (CW_BRIDGE__chatwoot__accounts__<id>__token) and route files for that account. The account needs an
API inbox, and labels named ``spam`` and ``tracked``. Each run makes its own contact and conversation.

    CHATWOOT_CONTRACT_ENV=/path/to/bridge.env pytest tests/test_chatwoot_contract.py
"""

import os
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ENV_FILE = os.getenv("CHATWOOT_CONTRACT_ENV")
pytestmark = pytest.mark.skipif(not ENV_FILE, reason="no Chatwoot to test against (CHATWOOT_CONTRACT_ENV)")


def _env(path: str) -> dict:
    out = {}
    for line in Path(path).read_text().splitlines():
        if line.strip() and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            out[k.strip()] = v.strip()
    return out


@pytest.fixture(scope="module")
def bridge():
    """The app in multi mode against the real Chatwoot, with callers trusted (auth is tested elsewhere)."""
    saved = dict(os.environ)
    os.environ.update(_env(ENV_FILE))
    os.environ["CW_BRIDGE__deliveries__enabled"] = "false"
    from vital_chatwoot_bridge.core import config
    config.get_settings.cache_clear()
    from vital_chatwoot_bridge.chatwoot import api_client
    from vital_chatwoot_bridge.core.auth_models import AuthenticatedUser
    from vital_chatwoot_bridge.main import app
    from vital_chatwoot_bridge.routing import idempotency, pauses, routes
    from vital_chatwoot_bridge.utils.jwt_verify import get_current_user
    for reset in (routes.set_route_table, pauses.set_pause_store, idempotency.set_idempotency_store):
        reset(None)
    api_client._chatwoot_client = None
    app.dependency_overrides[get_current_user] = lambda: AuthenticatedUser(
        client_id="contract", subject="contract", expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        issued_at=datetime.now(timezone.utc))
    account = routes.get_route_table().accounts()[0]
    with TestClient(app) as client:
        yield client, account, api_client
    app.dependency_overrides.clear()
    os.environ.clear()
    os.environ.update(saved)
    config.get_settings.cache_clear()
    api_client._chatwoot_client = None
    for reset in (routes.set_route_table, pauses.set_pause_store, idempotency.set_idempotency_store):
        reset(None)


@pytest.fixture(scope="module")
def conversation(bridge):
    """A new contact and conversation in the account's API inbox, with one incoming message."""
    import asyncio
    c, account, api_client = bridge

    async def make():
        cw = api_client.ChatwootAPIClient()
        try:
            inboxes = (await cw.account_call(account, "GET", "inboxes"))["payload"]
            inbox = next(i for i in inboxes if i.get("channel_type") == "Channel::Api")
            tag = uuid.uuid4().hex[:10]
            contact = (await cw.account_call(account, "POST", "contacts", json={
                "name": f"contract {tag}", "email": f"contract-{tag}@example.test", "inbox_id": inbox["id"],
                "custom_attributes": {"vital_member_id": f"member-{tag}"}}))["payload"]["contact"]
            source = contact["contact_inboxes"][0]["source_id"]
            conv = await cw.account_call(account, "POST", "conversations", json={
                "source_id": source, "inbox_id": inbox["id"], "contact_id": contact["id"]})
            msg = await cw.account_call(account, "POST", f"conversations/{conv['id']}/messages", json={
                "content": "contract test: incoming", "message_type": "incoming"})
            return {"inbox": inbox["id"], "contact": contact, "id": conv["id"], "message": msg, "tag": tag}
        finally:
            await cw.close()

    return asyncio.new_event_loop().run_until_complete(make())


def test_the_account_path_is_required_and_checked(bridge):
    c, account, _ = bridge
    assert c.get("/api/v1/chatwoot/contacts").status_code == 400
    assert c.get(f"/api/v1/chatwoot/accounts/{account}/contacts").status_code == 200
    assert c.get(f"/api/v1/chatwoot/accounts/{account + 1000}/contacts").status_code == 404


def test_notes_and_replies_are_written_once(bridge, conversation):
    c, account, _ = bridge
    url = f"/api/v1/chatwoot/accounts/{account}/conversations/{conversation['id']}"
    key = f"contract-{conversation['tag']}"
    note = {"content": "Translation: incoming", "content_attributes": {"vital": {"kind": "translation"}}}
    first = c.post(f"{url}/notes", json=note, headers={"Idempotency-Key": key}).json()["data"]
    again = c.post(f"{url}/notes", json=note, headers={"Idempotency-Key": key}).json()["data"]
    assert first["message"]["id"] == again["message"]["id"] and again["replayed"] and first["message"]["private"] is True
    reply = c.post(f"{url}/replies", json={"content": "A reply"}, headers={"Idempotency-Key": key}).json()["data"]
    assert reply["replayed"] is False and reply["message"]["private"] is False
    listed = c.get(f"{url}/messages").json()["data"]
    contents = [m["content"] for m in listed]
    assert contents.count("Translation: incoming") == 1 and contents.count("A reply") == 1


def test_labels_status_and_assignment(bridge, conversation):
    c, account, api_client = bridge
    url = f"/api/v1/chatwoot/accounts/{account}/conversations/{conversation['id']}"
    assert c.post(f"{url}/labels", json={"labels": ["tracked"]}).json()["data"]["labels"] == ["tracked"]
    assert sorted(c.post(f"{url}/labels", json={"labels": ["spam"]}).json()["data"]["labels"]) == ["spam", "tracked"]
    assert c.delete(f"{url}/labels/tracked").json()["data"]["labels"] == ["spam"]
    assert sorted(c.get(f"{url}/labels").json()["data"]["labels"]) == ["spam"]
    assert c.post(f"{url}/status", json={"status": "resolved"}).status_code == 200
    assert c.get(f"/api/v1/chatwoot/accounts/{account}/conversations/{conversation['id']}").json()["data"]["status"] == "resolved"
    assert c.post(f"{url}/status", json={"status": "open"}).status_code == 200
    import asyncio

    async def me():
        cw = api_client.ChatwootAPIClient()
        try:
            r = await cw._request("GET", f"{cw.base_url}/api/v1/profile",       # the account's API user
                                  headers={"api_access_token": cw.settings.chatwoot_account_tokens[account]})
            return r.json()
        finally:
            await cw.close()
    profile = asyncio.new_event_loop().run_until_complete(me())
    r = c.post(f"{url}/assignee", json={"assignee_id": profile["id"]})
    assert r.status_code == 200 and r.json()["data"]["id"] == profile["id"]


def test_contacts_by_email_and_member_id(bridge, conversation):
    c, account, _ = bridge
    base = f"/api/v1/chatwoot/accounts/{account}/contacts"
    email = conversation["contact"]["email"]
    assert [x["id"] for x in c.get(f"{base}?email={email.upper()}").json()["data"]] == [conversation["contact"]["id"]]
    found = c.get(f"{base}?vital_member_id=member-{conversation['tag']}").json()["data"]
    assert [x["id"] for x in found] == [conversation["contact"]["id"]]
    assert c.get(f"{base}?vital_member_id=nobody-{conversation['tag']}").json()["data"] == []


def test_an_attachment_streams_back_byte_for_byte(bridge, conversation):
    import asyncio

    from vital_chatwoot_bridge.chatwoot.models import ChatwootAttachment
    c, account, api_client = bridge
    png = b"\x89PNG\r\n\x1a\n" + uuid.uuid4().bytes * 8

    async def send():
        cw = api_client.ChatwootAPIClient()
        try:
            return await cw.send_message_raw(account, conversation["id"], {"content": "with a file", "message_type": "incoming"},
                                             attachments=[ChatwootAttachment(filename="shot.png", content_type="image/png",
                                                                             file_bytes=png)])
        finally:
            await cw.close()
    msg = asyncio.new_event_loop().run_until_complete(send())
    att = msg["attachments"][0]
    r = c.get(f"/api/v1/chatwoot/accounts/{account}/conversations/{conversation['id']}/messages/{msg['id']}/attachments/{att['id']}")
    assert r.status_code == 200 and r.content == png and r.headers["cache-control"] == "private, no-store"
    other = c.get(f"/api/v1/chatwoot/accounts/{account}/conversations/{conversation['id']}/messages/{msg['id']}/attachments/{att['id'] + 99999}")
    assert other.status_code == 404


def test_inbound_messages_since(bridge, conversation):
    c, account, _ = bridge
    url = f"/api/v1/chatwoot/accounts/{account}/inboxes/{conversation['inbox']}/messages/inbound"
    recent = (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat()
    later = (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat()
    ids = [m["id"] for m in c.get(url, params={"since": recent, "limit": 200}).json()["data"]["messages"]]
    assert conversation["message"]["id"] in ids
    assert c.get(url, params={"since": later}).json()["data"]["messages"] == []
