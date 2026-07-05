"""
Zoom OAuth 2.0 Authorization Code flow for user-level SMS access.

Key facts:
- Access tokens expire after 1 hour
- Refresh tokens expire after 90 days of non-use
- Zoom rotates the refresh token on EVERY refresh call
- The old refresh token is immediately invalidated
- We must atomically store the new pair before using it
"""

import logging
import time
from typing import Optional
from urllib.parse import urlencode

import httpx

from vital_chatwoot_bridge.zoom.models import (
    ZoomConfig, ZoomOAuthConfig, ZoomTokenPair,
)
from vital_chatwoot_bridge.zoom.token_store import ZoomTokenStore

logger = logging.getLogger(__name__)

ZOOM_AUTH_URL = "https://zoom.us/oauth/authorize"
ZOOM_TOKEN_URL = "https://zoom.us/oauth/token"


class ZoomOAuthError(Exception):
    """Raised when OAuth operations fail."""

    def __init__(self, message: str, status_code: Optional[int] = None):
        super().__init__(message)
        self.status_code = status_code


class ZoomOAuthManager:
    """
    Manages the Zoom OAuth lifecycle:
    - Generates authorization URLs for initial consent
    - Exchanges authorization codes for token pairs
    - Refreshes expired access tokens (with atomic storage)
    """

    def __init__(self, config: ZoomConfig, token_store: ZoomTokenStore):
        self.oauth_config: ZoomOAuthConfig = config.oauth
        self.token_store = token_store
        self._http = httpx.AsyncClient(timeout=30.0)

    async def close(self):
        await self._http.aclose()

    # ------------------------------------------------------------------
    # Authorization URL (step 1 of OAuth flow)
    # ------------------------------------------------------------------

    def get_authorize_url(self, account_name: str) -> str:
        """
        Generate the Zoom OAuth consent URL for a user to authorize.
        The account_name is passed as the `state` parameter for CSRF protection
        and to identify which account to store tokens for on callback.
        """
        params = {
            "response_type": "code",
            "client_id": self.oauth_config.client_id,
            "redirect_uri": self.oauth_config.redirect_uri,
            "state": account_name,
        }
        return f"{ZOOM_AUTH_URL}?{urlencode(params)}"

    # ------------------------------------------------------------------
    # Token exchange (step 2 — after user consents)
    # ------------------------------------------------------------------

    async def exchange_code(self, code: str, account_name: str) -> ZoomTokenPair:
        """
        Exchange an authorization code for access + refresh tokens.
        Stores the token pair atomically in Secrets Manager.
        """
        response = await self._http.post(
            ZOOM_TOKEN_URL,
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": self.oauth_config.redirect_uri,
            },
            auth=(self.oauth_config.client_id, self.oauth_config.client_secret),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )

        if response.status_code != 200:
            logger.error(
                f"Zoom token exchange failed for '{account_name}': "
                f"{response.status_code} {response.text}"
            )
            raise ZoomOAuthError(
                f"Token exchange failed: {response.text}",
                status_code=response.status_code,
            )

        data = response.json()
        token = ZoomTokenPair(
            access_token=data["access_token"],
            refresh_token=data["refresh_token"],
            expires_at=time.time() + data["expires_in"],
            scope=data.get("scope", ""),
            account_name=account_name,
        )

        # Store atomically BEFORE returning
        self.token_store.store_token(account_name, token)
        logger.info(f"✅ Zoom OAuth complete for account '{account_name}'")
        return token

    # ------------------------------------------------------------------
    # Token refresh
    # ------------------------------------------------------------------

    async def refresh_token(self, account_name: str) -> ZoomTokenPair:
        """
        Refresh the access token for an account.

        CRITICAL: Zoom rotates the refresh token on every refresh.
        The old refresh token is immediately invalidated.
        We MUST store the new pair before doing anything else.
        """
        current = self.token_store.get_token(account_name)
        if current is None:
            raise ZoomOAuthError(
                f"No token found for account '{account_name}' — needs initial authorization"
            )

        response = await self._http.post(
            ZOOM_TOKEN_URL,
            data={
                "grant_type": "refresh_token",
                "refresh_token": current.refresh_token,
            },
            auth=(self.oauth_config.client_id, self.oauth_config.client_secret),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )

        if response.status_code != 200:
            logger.error(
                f"❌ Zoom token refresh failed for '{account_name}': "
                f"{response.status_code} {response.text}"
            )
            raise ZoomOAuthError(
                f"Token refresh failed for '{account_name}': {response.text}",
                status_code=response.status_code,
            )

        data = response.json()
        new_token = ZoomTokenPair(
            access_token=data["access_token"],
            refresh_token=data["refresh_token"],
            expires_at=time.time() + data["expires_in"],
            scope=data.get("scope", ""),
            account_name=account_name,
        )

        # ATOMIC STORE — must succeed before we use the new token
        self.token_store.store_token(account_name, new_token)
        logger.info(
            f"🔄 Zoom token refreshed for '{account_name}' "
            f"(new expiry in {data['expires_in']}s)"
        )
        return new_token

    # ------------------------------------------------------------------
    # Get valid token (refresh if needed)
    # ------------------------------------------------------------------

    async def get_valid_token(self, account_name: str, buffer_minutes: int = 15) -> str:
        """
        Get a valid access token for an account, refreshing if necessary.
        Returns the access_token string ready for Authorization header.
        """
        token = self.token_store.get_token(account_name)
        if token is None:
            raise ZoomOAuthError(
                f"No token for account '{account_name}' — needs authorization"
            )

        if self.token_store.is_token_expired(token, buffer_minutes):
            logger.info(f"Token for '{account_name}' expired/expiring — refreshing")
            token = await self.refresh_token(account_name)

        return token.access_token
