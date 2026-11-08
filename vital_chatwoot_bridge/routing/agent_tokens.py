"""Tokens a route's agent expects: client credentials from the route file's ``agent_auth`` (the token URL, the client
id, and the environment variable holding its secret). Cached until shortly before they expire. Sent inside each AIMP
message (payload mode), which is how agents that check their callers per message expect them."""

from __future__ import annotations

import logging
import os
import time
from typing import Dict, Optional, Tuple

import httpx

logger = logging.getLogger(__name__)

_cache: Dict[Tuple[str, str], Tuple[str, float]] = {}


async def token_for(auth: Optional[dict]) -> Optional[str]:
    """None when the route names no agent_auth. Raises when it does and no token can be had: the delivery fails and
    is retried and reported, rather than reaching the agent unauthenticated."""
    if not auth:
        return None
    key = (auth["token_url"], auth["client_id"])
    cached = _cache.get(key)
    if cached and time.time() < cached[1] - 30:
        return cached[0]
    secret = os.environ.get(auth["client_secret_env"], "")
    async with httpx.AsyncClient(timeout=10) as http:
        r = await http.post(auth["token_url"], data={"grant_type": "client_credentials", "client_id": auth["client_id"],
                                                     "client_secret": secret})
    if r.status_code != 200:
        raise RuntimeError(f"agent token for {auth['client_id']}: HTTP {r.status_code}")
    body = r.json()
    _cache[key] = (body["access_token"], time.time() + int(body.get("expires_in", 60)))
    return body["access_token"]


def clear() -> None:
    _cache.clear()
