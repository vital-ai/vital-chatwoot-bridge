"""The routing API: what the bridge routes where, pausing an inbox, reloading the route files, retrying a message.

    GET  /api/v1/routes                                   every route, with its pause state and where it came from
    POST /api/v1/routes/reload                            read the route files again (multi mode); a bad file changes nothing
    POST /api/v1/routes/{account_id}/{inbox_id}/pause     {by, reason}: stop handing this inbox's messages to its agent
    POST /api/v1/routes/{account_id}/{inbox_id}/resume    {by}
    POST /api/v1/deliveries/{message_id}/retry            {account_id, conversation_id}: hand one message to its agent again

Callers are checked like every other API call (a token whose ``azp`` is in CW_BRIDGE__keycloak__allowed_azps). The
service calling these is expected to keep its own audit of who asked; the bridge logs each change with the ``by`` it was
given.
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from vital_chatwoot_bridge.chatwoot.api_client import ChatwootAPIError, get_chatwoot_client
from vital_chatwoot_bridge.chatwoot.models import ChatwootWebhookEvent
from vital_chatwoot_bridge.core.auth_models import AuthenticatedUser
from vital_chatwoot_bridge.routing.pauses import get_pause_store, paused_list
from vital_chatwoot_bridge.routing.routes import RouteFileError, get_route_table
from vital_chatwoot_bridge.utils.jwt_verify import get_current_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1", tags=["Routing"])


class PauseIn(BaseModel):
    by: str = Field(min_length=1, max_length=200)
    reason: str = Field(min_length=3, max_length=500)


class ResumeIn(BaseModel):
    by: str = Field(min_length=1, max_length=200)


class RetryIn(BaseModel):
    account_id: Optional[int] = None          # required in multi mode
    conversation_id: int


def _route_or_404(account_id: int, inbox_id: str):
    route = get_route_table().get(account_id, inbox_id)
    if route is None:
        raise HTTPException(status_code=404, detail=f"no route for account {account_id} inbox {inbox_id}")
    return route


@router.get("/routes")
async def list_routes(user: AuthenticatedUser = Depends(get_current_user)):
    table = get_route_table()
    pauses = await get_pause_store().all()
    return {"mode": table.mode, "loaded_from": table.loaded_from, "accounts": table.accounts(),
            "routes": [{**r.describe(), "paused": pauses.get(r.key)} for r in table.all()],
            "paused": paused_list(pauses)}


@router.post("/routes/reload")
async def reload_routes(user: AuthenticatedUser = Depends(get_current_user)):
    try:
        loaded = get_route_table().load()
    except RouteFileError as e:
        logger.error(f"🧭 ROUTES: reload refused, keeping the routes already loaded: {e}")
        raise HTTPException(status_code=422, detail=f"route files refused, nothing changed: {e}")
    return {"reloaded": True, **loaded}


@router.post("/routes/{account_id}/{inbox_id}/pause")
async def pause_route(account_id: int, inbox_id: str, body: PauseIn, user: AuthenticatedUser = Depends(get_current_user)):
    _route_or_404(account_id, inbox_id)
    state = await get_pause_store().pause(account_id, inbox_id, body.by, body.reason)
    return {"account_id": account_id, "inbox_id": inbox_id, "paused": state}


@router.post("/routes/{account_id}/{inbox_id}/resume")
async def resume_route(account_id: int, inbox_id: str, body: ResumeIn, user: AuthenticatedUser = Depends(get_current_user)):
    _route_or_404(account_id, inbox_id)
    was = await get_pause_store().resume(account_id, inbox_id, body.by)
    return {"account_id": account_id, "inbox_id": inbox_id, "paused": None, "was_paused": was}


@router.post("/deliveries/{message_id}/retry")
async def retry_delivery(message_id: int, body: RetryIn, user: AuthenticatedUser = Depends(get_current_user)):
    """Fetch the message from Chatwoot and hand it to its inbox's agent again, as if its webhook had just arrived: the
    route, the pause and the delivery report all apply. Only incoming messages from a contact are retried."""
    from vital_chatwoot_bridge.main import webhook_handler
    table = get_route_table()
    if body.account_id is None and table.mode == "multi":
        raise HTTPException(status_code=400, detail="account_id is required")
    account_id = body.account_id or table.accounts()[0]
    if account_id not in table.accounts():
        raise HTTPException(status_code=404, detail="unknown account")
    try:
        client = await get_chatwoot_client()
        conversation = await client.get_conversation_raw(account_id, body.conversation_id)
        message = await client.get_message(account_id, body.conversation_id, message_id)
    except ChatwootAPIError as e:
        raise HTTPException(status_code=e.status_code if e.status_code in (404, 403) else 502, detail=str(e))
    if not message or message.get("message_type") not in (0, "incoming"):
        raise HTTPException(status_code=422, detail="only a contact's incoming message can be retried")
    if webhook_handler is None:
        raise HTTPException(status_code=503, detail="webhook handler not initialized")
    created = message.get("created_at")
    event = ChatwootWebhookEvent(
        event="message_created", id=message["id"], content=message.get("content") or "",
        created_at=created if isinstance(created, str) else _iso(created),
        message_type="incoming", content_type=message.get("content_type") or "text",
        content_attributes=message.get("content_attributes") or {}, source_id=message.get("source_id") or "",
        sender={**(message.get("sender") or {}), "type": "contact"},
        conversation={**conversation, "inbox_id": conversation.get("inbox_id") or message.get("inbox_id")},
        account={"id": account_id}, inbox={"id": conversation.get("inbox_id") or message.get("inbox_id")},
    )
    logger.info(f"🔁 DELIVERY: retry of message {message_id} (account {account_id}, conversation {body.conversation_id})")
    return await webhook_handler._handle_message_created(event)


def _iso(ts) -> str:
    from datetime import datetime, timezone
    return datetime.fromtimestamp(int(ts or 0), tz=timezone.utc).isoformat().replace("+00:00", "Z")
