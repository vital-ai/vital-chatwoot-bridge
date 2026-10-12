"""
Tests for Zoom SMS message length validation.

Verifies that the ZoomSmsClient correctly:
- Accepts messages up to 500 characters
- Rejects messages over 500 characters with clear error
- Handles empty/whitespace messages
- Handles unicode/emoji correctly (char count, not byte count)
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from vital_chatwoot_bridge.integrations.zoom_sms_client import (
    ZoomSmsClient, ZoomSmsError, MAX_MESSAGE_LENGTH,
)
from vital_chatwoot_bridge.zoom.models import (
    ZoomConfig, ZoomOAuthConfig, ZoomAccount,
    ZoomTokenStorageConfig, ZoomTokenRefreshConfig,
    generate_session_id,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def zoom_config():
    """Create a test ZoomConfig."""
    return ZoomConfig(
        oauth=ZoomOAuthConfig(
            client_id="test_client_id",
            client_secret="test_client_secret",
            redirect_uri="https://example.ngrok.io/callback",
        ),
        accounts={
            "sales1": ZoomAccount(
                zoom_user_id="user@company.com",
                phone_number="+15551234567",
                display_name="Sales Rep 1",
                default_inbox_id="5",
                enabled=True,
            ),
            "disabled_acct": ZoomAccount(
                zoom_user_id="disabled@company.com",
                phone_number="+15559999999",
                display_name="Disabled",
                enabled=False,
            ),
        },
        token_storage=ZoomTokenStorageConfig(),
        token_refresh=ZoomTokenRefreshConfig(),
    )


@pytest.fixture
def mock_oauth_manager():
    """Create a mock OAuth manager that returns a valid token."""
    manager = AsyncMock()
    manager.get_valid_token = AsyncMock(return_value="mock_access_token")
    manager.refresh_token = AsyncMock()
    manager.close = AsyncMock()
    return manager


@pytest.fixture
def zoom_client(zoom_config, mock_oauth_manager):
    """Create a ZoomSmsClient with mocked dependencies."""
    return ZoomSmsClient(zoom_config, mock_oauth_manager)


# ---------------------------------------------------------------------------
# Valid message length tests
# ---------------------------------------------------------------------------


MESSAGES_VALID = {
    "short_50": "A" * 50,
    "boundary_160": "B" * 160,
    "multi_segment_161": "C" * 161,
    "mid_300": "D" * 300,
    "near_max_499": "E" * 499,
    "exact_max_500": "F" * 500,
    "unicode_emoji_100": "\U0001f389" * 100,  # 100 chars, 400 bytes UTF-8
    "mixed_emoji": "Hello " + "\U0001f389" * 50 + " world",
    "single_char": "X",
}


@pytest.mark.parametrize("label,message", MESSAGES_VALID.items())
@pytest.mark.asyncio
async def test_valid_message_lengths_accepted(zoom_client, label, message):
    """Messages up to 500 chars should pass validation (not be rejected by client)."""
    # Mock the HTTP response
    import httpx

    mock_response = httpx.Response(
        status_code=201,
        json={
            "message_id": "TEST-MSG-ID",
            "session_id": "test_session_id",
            "date_time": "2024-01-01T12:00:00Z",
        },
        request=httpx.Request("POST", "https://api.zoom.us/v2/phone/sms/messages"),
    )

    with patch.object(zoom_client._http, "post", new_callable=AsyncMock, return_value=mock_response):
        result = await zoom_client.send_sms(
            account_name="sales1",
            to="+15559876543",
            message=message,
        )
        assert result.message_id == "TEST-MSG-ID"
        assert result.session_id == "test_session_id"


# ---------------------------------------------------------------------------
# Invalid message length tests
# ---------------------------------------------------------------------------


MESSAGES_OVER_LIMIT = {
    "over_by_one_501": "G" * 501,
    "way_over_1000": "H" * 1000,
    "very_long_2000": "I" * 2000,
}


@pytest.mark.parametrize("label,message", MESSAGES_OVER_LIMIT.items())
@pytest.mark.asyncio
async def test_over_limit_messages_rejected(zoom_client, label, message):
    """Messages over 500 chars should be rejected before hitting the API."""
    with pytest.raises(ZoomSmsError, match="exceeds"):
        await zoom_client.send_sms(
            account_name="sales1",
            to="+15559876543",
            message=message,
        )


@pytest.mark.asyncio
async def test_empty_message_rejected(zoom_client):
    """Empty messages should be rejected."""
    with pytest.raises(ZoomSmsError, match="empty"):
        await zoom_client.send_sms(
            account_name="sales1",
            to="+15559876543",
            message="",
        )


@pytest.mark.asyncio
async def test_whitespace_only_rejected(zoom_client):
    """Whitespace-only messages should be rejected."""
    with pytest.raises(ZoomSmsError, match="empty"):
        await zoom_client.send_sms(
            account_name="sales1",
            to="+15559876543",
            message="     ",
        )


# ---------------------------------------------------------------------------
# Account validation tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_unknown_account_rejected(zoom_client):
    """Non-existent account should raise error."""
    with pytest.raises(ZoomSmsError, match="not found"):
        await zoom_client.send_sms(
            account_name="nonexistent",
            to="+15559876543",
            message="test",
        )


@pytest.mark.asyncio
async def test_disabled_account_rejected(zoom_client):
    """Disabled account should raise error."""
    with pytest.raises(ZoomSmsError, match="disabled"):
        await zoom_client.send_sms(
            account_name="disabled_acct",
            to="+15559876543",
            message="test",
        )


# ---------------------------------------------------------------------------
# Session ID tests
# ---------------------------------------------------------------------------


def test_session_id_deterministic():
    """Same sender+recipient should always produce same session ID."""
    id1 = generate_session_id("+15551234567", "+15559876543")
    id2 = generate_session_id("+15551234567", "+15559876543")
    assert id1 == id2


def test_session_id_different_for_different_pairs():
    """Different pairs should produce different session IDs."""
    id1 = generate_session_id("+15551234567", "+15559876543")
    id2 = generate_session_id("+15551234567", "+15550000000")
    assert id1 != id2


def test_session_id_format():
    """Session ID should be 32-char hex (MD5 digest)."""
    session_id = generate_session_id("+15551234567", "+15559876543")
    assert len(session_id) == 32
    assert all(c in "0123456789abcdef" for c in session_id)


def test_max_message_length_constant():
    """Verify the constant matches Zoom's documented limit."""
    assert MAX_MESSAGE_LENGTH == 500
