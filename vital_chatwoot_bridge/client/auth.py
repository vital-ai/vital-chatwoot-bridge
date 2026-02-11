"""
Keycloak JWT token acquisition and caching for the bridge client.
Supports both client_credentials and password grant types.
"""

import logging
import time
from typing import Optional

import httpx

from vital_chatwoot_bridge.client.exceptions import AuthenticationError

logger = logging.getLogger(__name__)


class KeycloakAuth:
    """Acquires and caches Keycloak JWT tokens for authenticating with the bridge."""

    def __init__(
        self,
        keycloak_url: str,
        realm: str,
        client_id: str,
        client_secret: Optional[str] = None,
        username: Optional[str] = None,
        password: Optional[str] = None,
        scope: str = "openid profile email",
    ):
        self.token_url = (
            f"{keycloak_url.rstrip('/')}/realms/{realm}/protocol/openid-connect/token"
        )
        self.client_id = client_id
        self.client_secret = client_secret
        self.username = username
        self.password = password
        self.scope = scope

        self._access_token: Optional[str] = None
        self._expires_at: float = 0

    async def get_token(self) -> str:
        """Get a valid access token, refreshing if expired."""
        if self._access_token and time.time() < self._expires_at - 30:
            return self._access_token
        await self._refresh_token()
        return self._access_token

    async def _refresh_token(self) -> None:
        """Acquire a new token from Keycloak."""
        if self.username and self.password:
            data = {
                "grant_type": "password",
                "client_id": self.client_id,
                "username": self.username,
                "password": self.password,
                "scope": self.scope,
            }
        else:
            data = {
                "grant_type": "client_credentials",
                "client_id": self.client_id,
                "scope": self.scope,
            }

        if self.client_secret:
            data["client_secret"] = self.client_secret

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(self.token_url, data=data)

            if resp.status_code != 200:
                raise AuthenticationError(
                    f"Keycloak token request failed: HTTP {resp.status_code} — {resp.text}",
                    status_code=resp.status_code,
                )

            body = resp.json()
            self._access_token = body["access_token"]
            expires_in = body.get("expires_in", 300)
            self._expires_at = time.time() + expires_in
            logger.debug(f"Acquired Keycloak token (expires in {expires_in}s)")

        except httpx.RequestError as e:
            raise AuthenticationError(f"Keycloak token request error: {e}")

    def clear(self) -> None:
        """Clear the cached token."""
        self._access_token = None
        self._expires_at = 0
