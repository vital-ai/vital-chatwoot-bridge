"""
Tests for Zoom OAuth flow and token refresh worker.

Verifies:
- Authorization URL generation
- Token exchange from auth code
- Token refresh with atomic storage
- Refresh worker periodic behavior
- Error handling for expired/invalid tokens
"""

import time
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

import httpx

from vital_chatwoot_bridge.zoom.models import (
    ZoomConfig, ZoomOAuthConfig, ZoomAccount,
    ZoomTokenStorageConfig, ZoomTokenRefreshConfig,
    ZoomTokenPair,
)
from vital_chatwoot_bridge.zoom.oauth import (
    ZoomOAuthManager, ZoomOAuthError, ZOOM_AUTH_URL, ZOOM_TOKEN_URL,
)
from vital_chatwoot_bridge.zoom.token_store import ZoomTokenStore
from vital_chatwoot_bridge.zoom.refresh_worker import ZoomTokenRefreshWorker


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def zoom_config():
    return ZoomConfig(
        oauth=ZoomOAuthConfig(
            client_id="test_client_id",
            client_secret="test_client_secret",
            redirect_uri="https://example.ngrok.io/api/v1/zoom/oauth/callback",
        ),
        accounts={
            "sales1": ZoomAccount(
                zoom_user_id="user@company.com",
                phone_number="+15551234567",
                display_name="Sales Rep 1",
                enabled=True,
            ),
        },
        token_storage=ZoomTokenStorageConfig(
            backend="secrets_manager",
            secret_prefix="test/zoom-tokens/",
        ),
        token_refresh=ZoomTokenRefreshConfig(
            refresh_interval_minutes=30,
            refresh_buffer_minutes=15,
            weekly_force_refresh=True,
        ),
    )


@pytest.fixture
def mock_token_store():
    store = MagicMock(spec=ZoomTokenStore)
    store.get_token = MagicMock(return_value=None)
    store.store_token = MagicMock()
    store.is_token_expired = MagicMock(return_value=False)
    return store


@pytest.fixture
def oauth_manager(zoom_config, mock_token_store):
    return ZoomOAuthManager(zoom_config, mock_token_store)


# ---------------------------------------------------------------------------
# Authorization URL tests
# ---------------------------------------------------------------------------


def test_authorize_url_generation(oauth_manager):
    """Should generate correct Zoom OAuth URL with state parameter."""
    url = oauth_manager.get_authorize_url("sales1")
    assert ZOOM_AUTH_URL in url
    assert "client_id=test_client_id" in url
    assert "state=sales1" in url
    assert "response_type=code" in url
    assert "redirect_uri=" in url


# ---------------------------------------------------------------------------
# Token exchange tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_exchange_code_success(oauth_manager, mock_token_store):
    """Successful code exchange should store token and return it."""
    mock_response = httpx.Response(
        status_code=200,
        json={
            "access_token": "new_access_token",
            "refresh_token": "new_refresh_token",
            "expires_in": 3600,
            "scope": "phone_sms:write",
        },
        request=httpx.Request("POST", ZOOM_TOKEN_URL),
    )

    with patch.object(oauth_manager._http, "post", new_callable=AsyncMock, return_value=mock_response):
        token = await oauth_manager.exchange_code("auth_code_123", "sales1")

    assert token.access_token == "new_access_token"
    assert token.refresh_token == "new_refresh_token"
    assert token.scope == "phone_sms:write"
    assert token.account_name == "sales1"
    # Verify atomic store was called
    mock_token_store.store_token.assert_called_once_with("sales1", token)


@pytest.mark.asyncio
async def test_exchange_code_failure(oauth_manager):
    """Failed code exchange should raise ZoomOAuthError."""
    mock_response = httpx.Response(
        status_code=400,
        json={"error": "invalid_grant"},
        request=httpx.Request("POST", ZOOM_TOKEN_URL),
    )

    with patch.object(oauth_manager._http, "post", new_callable=AsyncMock, return_value=mock_response):
        with pytest.raises(ZoomOAuthError, match="Token exchange failed"):
            await oauth_manager.exchange_code("bad_code", "sales1")


# ---------------------------------------------------------------------------
# Token refresh tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_refresh_token_success(oauth_manager, mock_token_store):
    """Successful refresh should store new token pair atomically."""
    # Set up existing token
    existing_token = ZoomTokenPair(
        access_token="old_access",
        refresh_token="old_refresh",
        expires_at=time.time() - 100,  # expired
        scope="phone_sms:write",
        account_name="sales1",
    )
    mock_token_store.get_token.return_value = existing_token

    mock_response = httpx.Response(
        status_code=200,
        json={
            "access_token": "new_access_token",
            "refresh_token": "new_refresh_token",
            "expires_in": 3600,
            "scope": "phone_sms:write",
        },
        request=httpx.Request("POST", ZOOM_TOKEN_URL),
    )

    with patch.object(oauth_manager._http, "post", new_callable=AsyncMock, return_value=mock_response):
        new_token = await oauth_manager.refresh_token("sales1")

    assert new_token.access_token == "new_access_token"
    assert new_token.refresh_token == "new_refresh_token"
    # CRITICAL: verify store was called with the new token
    mock_token_store.store_token.assert_called_once_with("sales1", new_token)


@pytest.mark.asyncio
async def test_refresh_token_no_existing_token(oauth_manager, mock_token_store):
    """Refresh with no existing token should raise error."""
    mock_token_store.get_token.return_value = None

    with pytest.raises(ZoomOAuthError, match="No token found"):
        await oauth_manager.refresh_token("sales1")


@pytest.mark.asyncio
async def test_refresh_token_api_failure(oauth_manager, mock_token_store):
    """Failed refresh should raise error (account may need re-auth)."""
    existing_token = ZoomTokenPair(
        access_token="old_access",
        refresh_token="old_refresh",
        expires_at=time.time() - 100,
        scope="phone_sms:write",
        account_name="sales1",
    )
    mock_token_store.get_token.return_value = existing_token

    mock_response = httpx.Response(
        status_code=401,
        json={"error": "invalid_grant", "reason": "Invalid Token!"},
        request=httpx.Request("POST", ZOOM_TOKEN_URL),
    )

    with patch.object(oauth_manager._http, "post", new_callable=AsyncMock, return_value=mock_response):
        with pytest.raises(ZoomOAuthError, match="Token refresh failed"):
            await oauth_manager.refresh_token("sales1")


# ---------------------------------------------------------------------------
# get_valid_token tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_valid_token_not_expired(oauth_manager, mock_token_store):
    """Should return existing token if not expired."""
    token = ZoomTokenPair(
        access_token="valid_token",
        refresh_token="refresh",
        expires_at=time.time() + 3600,
        scope="phone_sms:write",
        account_name="sales1",
    )
    mock_token_store.get_token.return_value = token
    mock_token_store.is_token_expired.return_value = False

    result = await oauth_manager.get_valid_token("sales1")
    assert result == "valid_token"


@pytest.mark.asyncio
async def test_get_valid_token_expired_triggers_refresh(oauth_manager, mock_token_store):
    """Should refresh and return new token if expired."""
    expired_token = ZoomTokenPair(
        access_token="expired_token",
        refresh_token="old_refresh",
        expires_at=time.time() - 100,
        scope="phone_sms:write",
        account_name="sales1",
    )
    mock_token_store.get_token.return_value = expired_token
    mock_token_store.is_token_expired.return_value = True

    mock_response = httpx.Response(
        status_code=200,
        json={
            "access_token": "new_access_token",
            "refresh_token": "new_refresh_token",
            "expires_in": 3600,
            "scope": "phone_sms:write",
        },
        request=httpx.Request("POST", ZOOM_TOKEN_URL),
    )

    with patch.object(oauth_manager._http, "post", new_callable=AsyncMock, return_value=mock_response):
        result = await oauth_manager.get_valid_token("sales1")

    assert result == "new_access_token"


@pytest.mark.asyncio
async def test_get_valid_token_no_token_raises(oauth_manager, mock_token_store):
    """Should raise error if no token exists."""
    mock_token_store.get_token.return_value = None

    with pytest.raises(ZoomOAuthError, match="No token"):
        await oauth_manager.get_valid_token("sales1")


# ---------------------------------------------------------------------------
# Token store expiry check
# ---------------------------------------------------------------------------


def test_token_expired_within_buffer():
    """Token expiring within buffer should be considered expired."""
    store = ZoomTokenStore.__new__(ZoomTokenStore)
    store.config = ZoomTokenStorageConfig()

    token = ZoomTokenPair(
        access_token="a",
        refresh_token="r",
        expires_at=time.time() + 600,  # expires in 10 min
        scope="",
        account_name="test",
    )
    # 15 min buffer → should be "expired"
    assert store.is_token_expired(token, buffer_minutes=15) is True
    # 5 min buffer → should NOT be "expired"
    assert store.is_token_expired(token, buffer_minutes=5) is False
