"""
Chatwoot Management API endpoints.
Proxies authenticated requests to the Chatwoot Application API.
"""

import asyncio
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status

from vital_chatwoot_bridge.core.config import get_settings
from vital_chatwoot_bridge.core.auth_models import AuthenticatedUser
from vital_chatwoot_bridge.utils.jwt_verify import get_current_user
from vital_chatwoot_bridge.chatwoot.api_client import get_chatwoot_client, ChatwootAPIError
from vital_chatwoot_bridge.chatwoot.management_models import (
    PaginatedResponse, PaginationMeta, SingleResponse, ErrorResponse,
    CreateContactRequest, UpdateContactRequest, MergeContactsRequest,
    CreateConversationRequest, UpdateConversationRequest, PostMessageRequest,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/chatwoot", tags=["Chatwoot Management"])


def _account_id() -> int:
    """Get the configured Chatwoot account ID."""
    return int(get_settings().chatwoot_account_id)


def _handle_api_error(e: ChatwootAPIError) -> HTTPException:
    """Convert ChatwootAPIError to HTTPException."""
    sc = e.status_code or 502
    logger.error(f"Chatwoot API error: HTTP {sc} — {e}")
    if e.response_data:
        logger.error(f"Chatwoot API response body: {e.response_data}")
    return HTTPException(status_code=sc, detail=str(e))


# ── Contacts ─────────────────────────────────────────────────────────

@router.get("/contacts", response_model=PaginatedResponse)
async def list_contacts(
    page: int = 1,
    sort: Optional[str] = None,
    user: AuthenticatedUser = Depends(get_current_user),
):
    """List contacts (paginated)."""
    try:
        client = await get_chatwoot_client()
        data = await client.list_contacts(_account_id(), page=page, sort=sort)
        payload = data.get("payload", [])
        meta_raw = data.get("meta", {})
        return PaginatedResponse(
            data=payload,
            meta=PaginationMeta(
                page=page,
                total_count=meta_raw.get("count"),
                total_pages=meta_raw.get("all_count"),
            ),
        )
    except ChatwootAPIError as e:
        raise _handle_api_error(e)


@router.get("/contacts/search", response_model=PaginatedResponse)
async def search_contacts(
    q: str,
    page: int = 1,
    user: AuthenticatedUser = Depends(get_current_user),
):
    """Search contacts by name, email, or phone."""
    try:
        client = await get_chatwoot_client()
        data = await client.search_contacts(_account_id(), q=q, page=page)
        payload = data.get("payload", [])
        meta_raw = data.get("meta", {})
        return PaginatedResponse(
            data=payload,
            meta=PaginationMeta(
                page=page,
                total_count=meta_raw.get("count"),
                total_pages=meta_raw.get("all_count"),
            ),
        )
    except ChatwootAPIError as e:
        raise _handle_api_error(e)


@router.get("/contacts/count", response_model=SingleResponse)
async def contact_count(
    user: AuthenticatedUser = Depends(get_current_user),
):
    """Get total contact count."""
    try:
        client = await get_chatwoot_client()
        data = await client.list_contacts(_account_id(), page=1)
        meta_raw = data.get("meta", {})
        return SingleResponse(data={
            "count": meta_raw.get("count", 0),
            "all_count": meta_raw.get("all_count", 0),
        })
    except ChatwootAPIError as e:
        raise _handle_api_error(e)


@router.post("/contacts/merge", response_model=SingleResponse)
async def merge_contacts(
    body: MergeContactsRequest,
    user: AuthenticatedUser = Depends(get_current_user),
):
    """Merge two contacts. The mergee is merged into the base contact."""
    try:
        client = await get_chatwoot_client()
        data = await client.merge_contacts_raw(
            _account_id(), body.base_contact_id, body.mergee_contact_id
        )
        return SingleResponse(data=data)
    except ChatwootAPIError as e:
        raise _handle_api_error(e)


@router.get("/contacts/{contact_id}", response_model=SingleResponse)
async def get_contact(
    contact_id: int,
    user: AuthenticatedUser = Depends(get_current_user),
):
    """Get contact details."""
    try:
        client = await get_chatwoot_client()
        data = await client.get_contact(_account_id(), contact_id)
        return SingleResponse(data=data)
    except ChatwootAPIError as e:
        raise _handle_api_error(e)


@router.get("/contacts/{contact_id}/conversations", response_model=PaginatedResponse)
async def get_contact_conversations(
    contact_id: int,
    page: int = 1,
    user: AuthenticatedUser = Depends(get_current_user),
):
    """List conversations for a contact."""
    try:
        client = await get_chatwoot_client()
        data = await client.get_contact_conversations(_account_id(), contact_id, page=page)
        payload = data.get("payload", [])
        return PaginatedResponse(
            data=payload,
            meta=PaginationMeta(page=page),
        )
    except ChatwootAPIError as e:
        raise _handle_api_error(e)


@router.delete("/contacts/{contact_id}", response_model=SingleResponse)
async def delete_contact(
    contact_id: int,
    user: AuthenticatedUser = Depends(get_current_user),
):
    """Delete a contact."""
    try:
        client = await get_chatwoot_client()
        data = await client.delete_contact_raw(_account_id(), contact_id)
        return SingleResponse(data=data)
    except ChatwootAPIError as e:
        raise _handle_api_error(e)


@router.post("/contacts", response_model=SingleResponse, status_code=201)
async def create_contact(
    body: CreateContactRequest,
    user: AuthenticatedUser = Depends(get_current_user),
):
    """Create a new contact."""
    try:
        client = await get_chatwoot_client()
        payload = {"name": body.name}
        if body.email:
            payload["email"] = body.email
        if body.phone_number:
            payload["phone_number"] = body.phone_number
        if body.identifier:
            payload["identifier"] = body.identifier
        if body.inbox_id:
            payload["inbox_id"] = body.inbox_id
        if body.custom_attributes:
            payload["custom_attributes"] = body.custom_attributes
        data = await client.create_contact_raw(_account_id(), payload)
        return SingleResponse(data=data)
    except ChatwootAPIError as e:
        raise _handle_api_error(e)


@router.post("/contacts/{contact_id}", response_model=SingleResponse)
async def update_contact(
    contact_id: int,
    body: UpdateContactRequest,
    user: AuthenticatedUser = Depends(get_current_user),
):
    """Update an existing contact."""
    try:
        client = await get_chatwoot_client()
        payload = {}
        if body.name is not None:
            payload["name"] = body.name
        if body.email is not None:
            payload["email"] = body.email
        if body.phone_number is not None:
            payload["phone_number"] = body.phone_number
        if body.identifier is not None:
            payload["identifier"] = body.identifier
        if body.custom_attributes is not None:
            payload["custom_attributes"] = body.custom_attributes
        if not payload:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="No fields to update",
            )
        data = await client.update_contact_raw(_account_id(), contact_id, payload)
        return SingleResponse(data=data)
    except ChatwootAPIError as e:
        raise _handle_api_error(e)


# ── Conversations ────────────────────────────────────────────────────

@router.get("/conversations", response_model=PaginatedResponse)
async def list_conversations(
    page: int = 1,
    status: Optional[str] = None,
    assignee_type: Optional[str] = None,
    user: AuthenticatedUser = Depends(get_current_user),
):
    """List conversations (paginated, filterable by status)."""
    try:
        client = await get_chatwoot_client()
        data = await client.list_conversations_raw(
            _account_id(), page=page, status=status, assignee_type=assignee_type
        )
        conv_data = data.get("data", {})
        payload = conv_data.get("payload", [])
        meta_raw = conv_data.get("meta", {})
        return PaginatedResponse(
            data=payload,
            meta=PaginationMeta(
                page=page,
                total_count=meta_raw.get("all_count"),
            ),
        )
    except ChatwootAPIError as e:
        raise _handle_api_error(e)


@router.get("/conversations/count", response_model=SingleResponse)
async def conversation_count(
    user: AuthenticatedUser = Depends(get_current_user),
):
    """Get conversation counts by status."""
    try:
        client = await get_chatwoot_client()
        counts = await client.get_conversation_counts_raw(_account_id())
        return SingleResponse(data=counts)
    except ChatwootAPIError as e:
        raise _handle_api_error(e)


@router.get("/conversations/{conversation_id}", response_model=SingleResponse)
async def get_conversation(
    conversation_id: int,
    user: AuthenticatedUser = Depends(get_current_user),
):
    """Get conversation details."""
    try:
        client = await get_chatwoot_client()
        data = await client.get_conversation_raw(_account_id(), conversation_id)
        return SingleResponse(data=data)
    except ChatwootAPIError as e:
        raise _handle_api_error(e)


@router.delete("/conversations/{conversation_id}", response_model=SingleResponse)
async def delete_conversation(
    conversation_id: int,
    user: AuthenticatedUser = Depends(get_current_user),
):
    """Delete a conversation."""
    try:
        client = await get_chatwoot_client()
        data = await client.delete_conversation_raw(_account_id(), conversation_id)
        return SingleResponse(data=data)
    except ChatwootAPIError as e:
        raise _handle_api_error(e)


@router.post("/conversations/{conversation_id}", response_model=SingleResponse)
async def update_conversation(
    conversation_id: int,
    body: UpdateConversationRequest,
    user: AuthenticatedUser = Depends(get_current_user),
):
    """Update a conversation (status, assignee, etc.)."""
    try:
        client = await get_chatwoot_client()
        payload = {}
        if body.status is not None:
            payload["status"] = body.status
        if body.assignee_id is not None:
            payload["assignee_id"] = body.assignee_id
        if body.team_id is not None:
            payload["team_id"] = body.team_id
        if body.label is not None:
            payload["label"] = body.label
        if body.custom_attributes is not None:
            payload["custom_attributes"] = body.custom_attributes
        if not payload:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="No fields to update",
            )
        data = await client.update_conversation_raw(_account_id(), conversation_id, payload)
        return SingleResponse(data=data)
    except ChatwootAPIError as e:
        raise _handle_api_error(e)


@router.post("/conversations", response_model=SingleResponse, status_code=201)
async def create_conversation(
    body: CreateConversationRequest,
    user: AuthenticatedUser = Depends(get_current_user),
):
    """Create a new conversation."""
    try:
        client = await get_chatwoot_client()
        payload = {
            "inbox_id": body.inbox_id,
            "contact_id": body.contact_id,
        }
        if body.source_id:
            payload["source_id"] = body.source_id
        if body.custom_attributes:
            payload["custom_attributes"] = body.custom_attributes
        data = await client.create_conversation_raw(_account_id(), payload)
        return SingleResponse(data=data)
    except ChatwootAPIError as e:
        raise _handle_api_error(e)


# ── Messages ─────────────────────────────────────────────────────────

@router.get("/conversations/{conversation_id}/messages", response_model=SingleResponse)
async def list_messages(
    conversation_id: int,
    user: AuthenticatedUser = Depends(get_current_user),
):
    """List messages for a conversation."""
    try:
        client = await get_chatwoot_client()
        data = await client.get_conversation_messages_raw(_account_id(), conversation_id)
        return SingleResponse(data=data.get("payload", []))
    except ChatwootAPIError as e:
        raise _handle_api_error(e)


@router.delete(
    "/conversations/{conversation_id}/messages/{message_id}",
    response_model=SingleResponse,
)
async def delete_message(
    conversation_id: int,
    message_id: int,
    user: AuthenticatedUser = Depends(get_current_user),
):
    """Delete a message."""
    try:
        client = await get_chatwoot_client()
        data = await client.delete_message_raw(_account_id(), conversation_id, message_id)
        return SingleResponse(data=data)
    except ChatwootAPIError as e:
        raise _handle_api_error(e)


@router.get(
    "/conversations/{conversation_id}/messages/{message_id}",
    response_model=SingleResponse,
)
async def get_message(
    conversation_id: int,
    message_id: int,
    user: AuthenticatedUser = Depends(get_current_user),
):
    """Get a single message with delivery status."""
    try:
        client = await get_chatwoot_client()
        data = await client.get_message(_account_id(), conversation_id, message_id)
        return SingleResponse(data=data)
    except ChatwootAPIError as e:
        raise _handle_api_error(e)


@router.post("/messages", response_model=SingleResponse, status_code=201)
async def post_message(
    body: PostMessageRequest,
    user: AuthenticatedUser = Depends(get_current_user),
):
    """
    Post a message (inbound or outbound) to any inbox.
    Auto-resolves contact and conversation.
    """
    # Validate direction
    if body.direction not in ("inbound", "outbound"):
        detail = "direction must be 'inbound' or 'outbound'"
        logger.warning(f"POST /messages 422: {detail} (got '{body.direction}')")
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=detail,
        )

    # Validate conversation_mode
    if body.conversation_mode not in ("reuse_newest", "create_new"):
        detail = "conversation_mode must be 'reuse_newest' or 'create_new'"
        logger.warning(f"POST /messages 422: {detail} (got '{body.conversation_mode}')")
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=detail,
        )

    # suppress_delivery only valid for outbound
    if body.suppress_delivery and body.direction != "outbound":
        detail = "suppress_delivery is only valid for outbound messages"
        logger.warning(f"POST /messages 422: {detail}")
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=detail,
        )

    try:
        client = await get_chatwoot_client()
        account_id = _account_id()

        inbox_id = body.inbox_id

        # Step 1: Find or create contact
        contact = await _resolve_contact(client, account_id, inbox_id, body.contact)

        contact_id = contact.get("id")
        if not contact_id:
            # Contact nested in payload
            contact_id = contact.get("payload", {}).get("contact", {}).get("id")
        if not contact_id:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to resolve contact ID",
            )

        # Step 2: Find or create conversation
        conversation_id = body.conversation_id
        if not conversation_id:
            conversation_id = await _resolve_conversation(
                client, account_id, inbox_id, contact_id, body.conversation_mode
            )

        # Step 3: Build and send message
        msg_payload = {
            "content": body.message.content,
            "content_type": body.message.content_type,
            "private": False,
        }

        if body.direction == "inbound":
            msg_payload["message_type"] = "incoming"
        elif body.suppress_delivery:
            # Log only: use private note with marker
            msg_payload["message_type"] = "outgoing"
            msg_payload["private"] = True
            msg_payload["content_attributes"] = {"logged_outbound": True}
        else:
            msg_payload["message_type"] = "outgoing"

        # Email-specific top-level params
        if body.to_emails:
            msg_payload["to_emails"] = body.to_emails
        if body.cc_emails:
            msg_payload["cc_emails"] = body.cc_emails
        if body.bcc_emails:
            msg_payload["bcc_emails"] = body.bcc_emails

        result = await client.send_message_raw(account_id, conversation_id, msg_payload)

        return SingleResponse(
            data={
                "contact_id": contact_id,
                "conversation_id": conversation_id,
                "message": result,
            }
        )

    except ChatwootAPIError as e:
        raise _handle_api_error(e)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in post_message: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Message posting failed: {str(e)}",
        )


# ── Account Summary ─────────────────────────────────────────────

@router.get("/account/summary", response_model=SingleResponse)
async def account_summary(
    user: AuthenticatedUser = Depends(get_current_user),
):
    """Get account summary: contact count, conversation counts, agent count, inbox count."""
    try:
        client = await get_chatwoot_client()
        account_id = _account_id()

        contacts_data, conv_counts, agents, inboxes = await asyncio.gather(
            client.list_contacts(account_id, page=1),
            client.get_conversation_counts_raw(account_id),
            client.list_agents(account_id),
            client.list_inboxes(account_id),
        )

        contact_meta = contacts_data.get("meta", {})

        return SingleResponse(data={
            "contacts": {
                "count": contact_meta.get("count", 0),
                "all_count": contact_meta.get("all_count", 0),
            },
            "conversations": conv_counts,
            "agents": len(agents) if isinstance(agents, list) else 0,
            "inboxes": len(inboxes.get("payload", [])) if isinstance(inboxes, dict) else 0,
        })
    except ChatwootAPIError as e:
        raise _handle_api_error(e)


# ── Agents ───────────────────────────────────────────────────────────

@router.get("/agents", response_model=SingleResponse)
async def list_agents(
    user: AuthenticatedUser = Depends(get_current_user),
):
    """List all agents."""
    try:
        client = await get_chatwoot_client()
        data = await client.list_agents(_account_id())
        return SingleResponse(data=data)
    except ChatwootAPIError as e:
        raise _handle_api_error(e)


# ── Inboxes ──────────────────────────────────────────────────────────

@router.get("/inboxes", response_model=SingleResponse)
async def list_inboxes(
    user: AuthenticatedUser = Depends(get_current_user),
):
    """List all inboxes in the account."""
    try:
        client = await get_chatwoot_client()
        data = await client.list_inboxes(_account_id())
        return SingleResponse(data=data.get("payload", []))
    except ChatwootAPIError as e:
        raise _handle_api_error(e)


# ── Helpers ──────────────────────────────────────────────────────────

async def _resolve_contact(client, account_id: int, inbox_id: int, contact_info) -> dict:
    """Find existing contact or create a new one."""
    search_key = contact_info.phone_number or contact_info.email or contact_info.identifier
    if search_key:
        try:
            search_data = await client.search_contacts(account_id, q=search_key)
            contacts = search_data.get("payload", [])
            for c in contacts:
                if (c.get("phone_number") == contact_info.phone_number or
                        c.get("email") == contact_info.email or
                        c.get("identifier") == contact_info.identifier):
                    logger.info(f"Found existing contact: {c['id']}")
                    return c
        except ChatwootAPIError:
            pass

    # Create new contact
    payload = {"inbox_id": inbox_id, "identifier": contact_info.identifier}
    if contact_info.name:
        payload["name"] = contact_info.name
    if contact_info.email:
        payload["email"] = contact_info.email
    if contact_info.phone_number:
        payload["phone_number"] = contact_info.phone_number
    data = await client.create_contact_raw(account_id, payload)
    return data.get("payload", {}).get("contact", data)


async def _resolve_conversation(
    client, account_id: int, inbox_id: int, contact_id: int,
    mode: str = "reuse_newest",
) -> int:
    """Find or create a conversation based on mode.

    Modes:
        reuse_newest — reuse the most recently active open/pending conversation
                       on this inbox, or create one if none exist.
        create_new   — always create a new conversation.
    """
    if mode == "reuse_newest":
        try:
            convs_data = await client.get_contact_conversations(account_id, contact_id)
            # Chatwoot returns newest first; pick the first open match
            for conv in convs_data.get("payload", []):
                if conv.get("inbox_id") == inbox_id and conv.get("status") in ("open", "pending"):
                    logger.info(f"Reusing conversation {conv['id']}")
                    return conv["id"]
        except ChatwootAPIError:
            pass

    # create_new  — or no reusable conversation found
    conv_payload = {
        "inbox_id": inbox_id,
        "contact_id": contact_id,
        "source_id": f"contact_{contact_id}",
    }
    result = await client.create_conversation_raw(account_id, conv_payload)
    conv_id = result.get("id") or result.get("payload", {}).get("id")
    if not conv_id:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create conversation",
        )
    logger.info(f"Created new conversation {conv_id}")
    return conv_id
