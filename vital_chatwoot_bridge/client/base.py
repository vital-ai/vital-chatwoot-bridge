"""
Base HTTP client for the Chatwoot Bridge client library.
Handles session management, authentication headers, and error mapping.
"""

import copy
import logging
from typing import Any, Dict, Optional

import httpx

from vital_chatwoot_bridge.client.auth import KeycloakAuth
from vital_chatwoot_bridge.client.exceptions import (
    AuthenticationError,
    BridgeClientError,
    NotFoundError,
    ServerError,
    ValidationError,
)

logger = logging.getLogger(__name__)

CHATWOOT_PREFIX = "/api/v1/chatwoot/"


class BaseClient:
    """Async HTTP client with auth and error handling."""

    def __init__(
        self,
        base_url: str,
        auth: KeycloakAuth,
        timeout: float = 30.0,
    ):
        self.base_url = base_url.rstrip("/")
        self.auth = auth
        self.timeout = timeout
        self._client = httpx.AsyncClient(timeout=httpx.Timeout(timeout))
        self.account_id: Optional[int] = None

    def for_account(self, account_id: int):
        """The same client, for one Chatwoot account: every /api/v1/chatwoot/... call goes to
        /api/v1/chatwoot/accounts/{account_id}/... (required when the bridge runs in multi-account mode). Shares the
        HTTP connection and the token; closing either closes both."""
        view = copy.copy(self)
        view.account_id = int(account_id)
        return view

    async def _headers(self, extra: Optional[Dict[str, str]] = None) -> Dict[str, str]:
        token = await self.auth.get_token()
        return {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            **(extra or {}),
        }

    def _url(self, path: str) -> str:
        if self.account_id is not None and path.startswith(CHATWOOT_PREFIX) and \
                not path.startswith(f"{CHATWOOT_PREFIX}accounts/"):
            path = f"{CHATWOOT_PREFIX}accounts/{self.account_id}/{path[len(CHATWOOT_PREFIX):]}"
        return f"{self.base_url}{path}"

    def _handle_response(self, resp: httpx.Response) -> Dict[str, Any]:
        """Parse response and raise typed exceptions on errors."""
        if resp.status_code == 401:
            raise AuthenticationError(
                "Authentication failed", status_code=401,
                response_data=self._safe_json(resp),
            )
        if resp.status_code == 404:
            raise NotFoundError(
                "Resource not found", status_code=404,
                response_data=self._safe_json(resp),
            )
        if resp.status_code == 422:
            data = self._safe_json(resp)
            detail = data.get("detail", "") if data else ""
            raise ValidationError(
                f"Validation error: {detail}", status_code=422,
                response_data=data,
            )
        if resp.status_code >= 500:
            raise ServerError(
                f"Server error: HTTP {resp.status_code}", status_code=resp.status_code,
                response_data=self._safe_json(resp),
            )
        if resp.status_code >= 400:
            raise BridgeClientError(
                f"Request failed: HTTP {resp.status_code}", status_code=resp.status_code,
                response_data=self._safe_json(resp),
            )
        if resp.status_code == 204 or not resp.content:
            return {"success": True}
        return resp.json()

    @staticmethod
    def _safe_json(resp: httpx.Response) -> Optional[Dict[str, Any]]:
        try:
            return resp.json()
        except Exception:
            return None

    async def get(self, path: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Make an authenticated GET request."""
        headers = await self._headers()
        resp = await self._client.get(
            self._url(path), headers=headers, params=params,
        )
        return self._handle_response(resp)

    async def post(self, path: str, json: Optional[Dict[str, Any]] = None,
                   headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
        """Make an authenticated POST request."""
        resp = await self._client.post(
            self._url(path), headers=await self._headers(headers), json=json,
        )
        return self._handle_response(resp)

    async def stream(self, path: str) -> httpx.Response:
        """An authenticated GET, streamed; the caller reads ``aiter_bytes()`` and closes it."""
        request = self._client.build_request("GET", self._url(path), headers=await self._headers())
        resp = await self._client.send(request, stream=True)
        if resp.status_code >= 400:
            await resp.aread()
            await resp.aclose()
            self._handle_response(resp)
        return resp

    async def delete(self, path: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Make an authenticated DELETE request."""
        headers = await self._headers()
        resp = await self._client.delete(
            self._url(path), headers=headers, params=params,
        )
        return self._handle_response(resp)

    async def close(self) -> None:
        """Close the underlying HTTP client."""
        await self._client.aclose()

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()
