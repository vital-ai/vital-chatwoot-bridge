"""
Tests for server-wide dry-run mode (CW_BRIDGE__app__dry_run).

Verifies that when dry-run is enabled:
- Outgoing Chatwoot messages are forced to private notes (or skipped)
- Incoming Chatwoot messages are not written
- Mailgun, Gmail, Zoom SMS and LoopMessage sends make no network calls
  and return fake dryrun-* provider IDs

See planning/testing/dry-run-mode.md.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock

from vital_chatwoot_bridge.core.config import get_settings
from vital_chatwoot_bridge.utils.dry_run import apply_dry_run_to_message_payload
from vital_chatwoot_bridge.chatwoot.api_client import ChatwootAPIClient
from vital_chatwoot_bridge.chatwoot.client_api import ChatwootClientAPI
from vital_chatwoot_bridge.chatwoot.client_models import ChatwootClientMessage
from vital_chatwoot_bridge.email.models import MailgunConfig, GmailConfig, GmailSender
from vital_chatwoot_bridge.integrations.mailgun_client import MailgunClient
from vital_chatwoot_bridge.integrations.gmail_client import GmailClient, GmailClientError
from vital_chatwoot_bridge.integrations.zoom_sms_client import ZoomSmsClient
from vital_chatwoot_bridge.integrations.loopmessage_client import LoopMessageClient, LoopMessageConfig
from vital_chatwoot_bridge.zoom.models import ZoomConfig, ZoomOAuthConfig, ZoomAccount


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def dry_run(monkeypatch):
    """Enable dry-run on the cached settings object."""
    monkeypatch.setattr(get_settings(), "dry_run", True)


@pytest.fixture
def no_dry_run(monkeypatch):
    monkeypatch.setattr(get_settings(), "dry_run", False)


def _ok_response(payload):
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = payload
    resp.content = b"{}"
    return resp


# ---------------------------------------------------------------------------
# Payload helper
# ---------------------------------------------------------------------------


class TestApplyPayload:

    def test_outgoing_forced_private(self, dry_run):
        payload = {"content": "hi", "message_type": "outgoing", "private": False}
        apply_dry_run_to_message_payload(payload)
        assert payload["private"] is True
        assert payload["content_attributes"] == {"dry_run": True}

    def test_missing_message_type_treated_as_outgoing(self, dry_run):
        payload = {"content": "hi"}
        apply_dry_run_to_message_payload(payload)
        assert payload["private"] is True

    def test_existing_content_attributes_merged(self, dry_run):
        payload = {"message_type": "outgoing", "content_attributes": {"foo": 1}}
        apply_dry_run_to_message_payload(payload)
        assert payload["content_attributes"] == {"foo": 1, "dry_run": True}

    def test_incoming_untouched(self, dry_run):
        payload = {"message_type": "incoming", "private": False}
        apply_dry_run_to_message_payload(payload)
        assert payload == {"message_type": "incoming", "private": False}

    def test_already_private_untouched(self, dry_run):
        payload = {"message_type": "outgoing", "private": True, "content_attributes": {"logged_outbound": True}}
        apply_dry_run_to_message_payload(payload)
        assert payload["content_attributes"] == {"logged_outbound": True}

    def test_disabled_is_noop(self, no_dry_run):
        payload = {"message_type": "outgoing", "private": False}
        apply_dry_run_to_message_payload(payload)
        assert payload == {"message_type": "outgoing", "private": False}


# ---------------------------------------------------------------------------
# Chatwoot clients
# ---------------------------------------------------------------------------


class TestChatwootClients:

    @pytest.mark.asyncio
    async def test_api_client_send_message_raw_forced_private(self, dry_run):
        client = ChatwootAPIClient()
        client._request = AsyncMock(return_value=_ok_response({"id": 1}))
        await client.send_message_raw(1, 2, {"content": "hi", "message_type": "outgoing", "private": False})
        sent = client._request.call_args.kwargs["json"]
        assert sent["private"] is True
        assert sent["content_attributes"]["dry_run"] is True

    @pytest.mark.asyncio
    async def test_api_client_send_message_forced_private(self, dry_run):
        client = ChatwootAPIClient()
        client._request = AsyncMock(return_value=_ok_response({
            "id": 1, "content": "hi", "message_type": 1, "created_at": 0,
            "conversation_id": 2, "private": True,
        }))
        try:
            await client.send_message(1, 2, "hi", message_type="outgoing")
        except Exception:
            pass  # response parsing is not under test
        sent = client._request.call_args.kwargs["json"]
        assert sent["private"] is True

    @pytest.mark.asyncio
    async def test_client_api_outgoing_forced_private(self, dry_run):
        client = ChatwootClientAPI()
        client._request = AsyncMock(return_value=_ok_response({"id": 1}))
        try:
            await client.send_message(2, ChatwootClientMessage(content="hi", message_type="outgoing"))
        except Exception:
            pass
        sent = client._request.call_args.kwargs["json"]
        assert sent["private"] is True

    @pytest.mark.asyncio
    async def test_client_api_incoming_skipped(self, dry_run):
        client = ChatwootClientAPI()
        client._request = AsyncMock()
        result = await client.send_message(2, ChatwootClientMessage(content="hi", message_type="incoming"))
        client._request.assert_not_called()
        assert result.id == 0
        assert result.message_type == 0

    @pytest.mark.asyncio
    async def test_api_client_incoming_skipped(self, dry_run):
        client = ChatwootAPIClient()
        client._request = AsyncMock()
        result = await client.send_message_raw(1, 2, {"content": "hi", "message_type": "incoming"})
        client._request.assert_not_called()
        assert result["dry_run"] is True
        assert result["message_type"] == 0

    @pytest.mark.asyncio
    async def test_incoming_written_when_not_dry_run(self, no_dry_run):
        client = ChatwootAPIClient()
        client._request = AsyncMock(return_value=_ok_response({"id": 5}))
        result = await client.send_message_raw(1, 2, {"content": "hi", "message_type": "incoming"})
        client._request.assert_called_once()
        assert result == {"id": 5}


# ---------------------------------------------------------------------------
# Provider clients
# ---------------------------------------------------------------------------


class TestProviders:

    @pytest.mark.asyncio
    async def test_mailgun_skipped(self, dry_run):
        client = MailgunClient(MailgunConfig(api_key="k", domain="mg.example.com", from_email="a@example.com"))
        client.client.post = AsyncMock()
        result = await client.send_email(to="b@example.com", subject="s", text="t")
        client.client.post.assert_not_called()
        assert result["id"].startswith("<dryrun-mailgun-")

    @pytest.mark.asyncio
    async def test_gmail_skipped(self, dry_run):
        client = GmailClient(GmailConfig(
            service_account_info={},
            senders={"s": GmailSender(email="a@example.com")},
        ))
        client._gmail_send_request = AsyncMock()
        result = await client.send_email(sender_email="a@example.com", to="b@example.com", subject="s", html="<p>x</p>")
        client._gmail_send_request.assert_not_called()
        assert result["id"].startswith("dryrun-gmail-")

    @pytest.mark.asyncio
    async def test_gmail_whitelist_still_enforced(self, dry_run):
        client = GmailClient(GmailConfig(service_account_info={}, senders={}))
        with pytest.raises(GmailClientError):
            await client.send_email(sender_email="x@example.com", to="b@example.com", subject="s", html="<p>x</p>")

    @pytest.mark.asyncio
    async def test_zoom_skipped(self, dry_run):
        config = ZoomConfig(
            oauth=ZoomOAuthConfig(client_id="c", client_secret="s", redirect_uri="https://x/cb"),
            accounts={"sales1": ZoomAccount(zoom_user_id="u", phone_number="+15551234567")},
        )
        oauth = MagicMock()
        oauth.get_valid_token = AsyncMock()
        client = ZoomSmsClient(config, oauth)
        result = await client.send_sms("sales1", "+15559876543", "hello")
        oauth.get_valid_token.assert_not_called()
        assert result.message_id.startswith("dryrun-zoom-")

    @pytest.mark.asyncio
    async def test_loopmessage_skipped(self, dry_run):
        client = LoopMessageClient(LoopMessageConfig(authorization_key="a", secret_key="s"))
        client.client.post = AsyncMock()
        result = await client.send_message(recipient="+15559876543", text="hi", sender_name="x")
        client.client.post.assert_not_called()
        assert result["success"] is True
        assert result["message_id"].startswith("dryrun-loopmessage-")


# ---------------------------------------------------------------------------
# dry_run_record_notes=false: skip the Chatwoot write entirely
# ---------------------------------------------------------------------------


@pytest.fixture
def dry_run_no_notes(dry_run, monkeypatch):
    monkeypatch.setattr(get_settings(), "dry_run_record_notes", False)


class TestSkipChatwootWrite:

    @pytest.mark.asyncio
    async def test_send_message_raw_skipped(self, dry_run_no_notes):
        client = ChatwootAPIClient()
        client._request = AsyncMock()
        result = await client.send_message_raw(1, 2, {"content": "hi", "message_type": "outgoing"})
        client._request.assert_not_called()
        assert result["id"] == 0
        assert result["dry_run"] is True
        assert result["conversation_id"] == 2

    @pytest.mark.asyncio
    async def test_send_message_skipped(self, dry_run_no_notes):
        client = ChatwootAPIClient()
        client._request = AsyncMock()
        result = await client.send_message(1, 2, "hi", message_type="outgoing")
        client._request.assert_not_called()
        assert result.id == 0
        assert result.content == "hi"

    @pytest.mark.asyncio
    async def test_client_api_outgoing_skipped(self, dry_run_no_notes):
        client = ChatwootClientAPI()
        client._request = AsyncMock()
        result = await client.send_message(2, ChatwootClientMessage(content="hi", message_type="outgoing"))
        client._request.assert_not_called()
        assert result.id == 0



# ---------------------------------------------------------------------------
# LoopMessage: private notes must never be delivered
# ---------------------------------------------------------------------------


class TestLoopMessagePrivateNotes:

    def _event(self, private: bool) -> dict:
        return {
            "event": "message_created",
            "id": 123,
            "content": "internal note",
            "created_at": "2026-09-21T00:00:00Z",
            "message_type": "outgoing",
            "private": private,
            "sender": {"type": "user", "name": "Agent"},
            "conversation": {"id": 7, "inbox_id": 6},
            "account": {"id": 1},
            "inbox": {"id": 6, "name": "Loop Message"},
        }

    @pytest.mark.asyncio
    async def test_private_note_ignored(self):
        from vital_chatwoot_bridge.chatwoot.models import ChatwootWebhookEvent
        from vital_chatwoot_bridge.handlers.webhook_handler import WebhookHandler

        handler = WebhookHandler(MagicMock())
        result = await handler._handle_outbound_message(
            ChatwootWebhookEvent(**self._event(private=True))
        )
        assert result["status"] == "ignored"
        assert "Private note" in result["message"]

    @pytest.mark.asyncio
    async def test_non_private_message_not_ignored_as_private(self):
        from vital_chatwoot_bridge.chatwoot.models import ChatwootWebhookEvent
        from vital_chatwoot_bridge.handlers.webhook_handler import WebhookHandler

        handler = WebhookHandler(MagicMock())
        result = await handler._handle_outbound_message(
            ChatwootWebhookEvent(**self._event(private=False))
        )
        # Proceeds past the private check (outcome depends on inbox config)
        assert result.get("message") != "Private note ignored"
