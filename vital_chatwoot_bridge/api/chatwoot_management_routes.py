"""
Chatwoot Management API endpoints.
Proxies authenticated requests to the Chatwoot Application API.
"""

import asyncio
import base64
import logging
import re
from datetime import datetime
from typing import Any, Dict, List, Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException, status

from vital_chatwoot_bridge.core.config import get_settings
from vital_chatwoot_bridge.core.auth_models import AuthenticatedUser
from vital_chatwoot_bridge.utils.jwt_verify import get_current_user
from vital_chatwoot_bridge.chatwoot.api_client import get_chatwoot_client, ChatwootAPIError
from vital_chatwoot_bridge.chatwoot.models import ChatwootAttachment
from vital_chatwoot_bridge.chatwoot.management_models import (
    PaginatedResponse, PaginationMeta, SingleResponse, ErrorResponse,
    CreateContactRequest, UpdateContactRequest, MergeContactsRequest,
    CreateConversationRequest, UpdateConversationRequest, PostMessageRequest,
    PostMessageContact, AttachmentInput,
)
from vital_chatwoot_bridge.email.models import SendTemplatedEmailRequest
from vital_chatwoot_bridge.email.renderer import get_renderer
from vital_chatwoot_bridge.chatwoot.communication_models import (
    CommunicationSender, CommunicationMessage, CommunicationConversation,
    CommunicationContact, CommunicationSummary, CommunicationsResponse,
)
from vital_chatwoot_bridge.services.inbox_cache import get_inbox_cache

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/chatwoot", tags=["Chatwoot Management"])


def _account_id() -> int:
    """Get the configured Chatwoot account ID."""
    return int(get_settings().chatwoot_account_id)


async def _resolve_attachments(
    inputs: List[AttachmentInput],
) -> List[ChatwootAttachment]:
    """Convert AttachmentInput items to ChatwootAttachment with file bytes."""
    results: List[ChatwootAttachment] = []
    for inp in inputs:
        if inp.data:
            try:
                file_bytes = base64.b64decode(inp.data)
            except Exception as exc:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=f"Invalid base64 in attachment '{inp.filename}': {exc}",
                )
            results.append(ChatwootAttachment(
                filename=inp.filename,
                content_type=inp.content_type,
                file_bytes=file_bytes,
            ))
        elif inp.url:
            try:
                async with httpx.AsyncClient(timeout=30.0) as http:
                    resp = await http.get(inp.url)
                    resp.raise_for_status()
                    file_bytes = resp.content
            except Exception as exc:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=f"Failed to fetch attachment '{inp.filename}' from URL: {exc}",
                )
            results.append(ChatwootAttachment(
                filename=inp.filename,
                content_type=inp.content_type,
                file_bytes=file_bytes,
            ))
    return results


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
    inbox_id: Optional[int] = None,
    user: AuthenticatedUser = Depends(get_current_user),
):
    """List conversations for a contact. Optionally filter by inbox_id."""
    try:
        client = await get_chatwoot_client()
        data = await client.get_contact_conversations(_account_id(), contact_id, page=page)
        payload = data.get("payload", [])
        if inbox_id is not None:
            payload = [c for c in payload if c.get("inbox_id") == inbox_id]
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
    before: Optional[int] = None,
    user: AuthenticatedUser = Depends(get_current_user),
):
    """List messages for a conversation."""
    try:
        client = await get_chatwoot_client()
        data = await client.get_conversation_messages_raw(_account_id(), conversation_id, before=before)
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

    # Validate content_mode
    valid_modes = ("text", "markdown", "html", "template", "gmail_template")
    if body.content_mode not in valid_modes:
        detail = f"content_mode must be one of {valid_modes}"
        logger.warning(f"POST /messages 422: {detail} (got '{body.content_mode}')")
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=detail,
        )

    if body.content_mode in ("template", "gmail_template") and not body.template_name:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"template_name is required when content_mode='{body.content_mode}'",
        )

    if body.content_mode in ("html", "template"):
        from vital_chatwoot_bridge.core.config import get_settings as _get_settings
        _settings = _get_settings()
        if not _settings.mailgun:
            raise HTTPException(
                status_code=status.HTTP_501_NOT_IMPLEMENTED,
                detail="Mailgun is not configured; html/template content_mode requires Mailgun",
            )

    if body.content_mode == "gmail_template":
        from vital_chatwoot_bridge.core.config import get_settings as _get_settings
        _settings = _get_settings()
        if not _settings.google:
            raise HTTPException(
                status_code=status.HTTP_501_NOT_IMPLEMENTED,
                detail="Google/Gmail is not configured; gmail_template content_mode requires Google config",
            )
        if not body.gmail_sender:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="gmail_sender is required when content_mode='gmail_template'",
            )
        if (body.enable_open_tracking or body.enable_click_tracking) and body.content_mode != "gmail_template":
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="enable_open_tracking / enable_click_tracking only valid with content_mode='gmail_template'",
            )
        if body.enable_click_tracking and not body.cta_url:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="cta_url is required when enable_click_tracking=True",
            )
        if body.enable_open_tracking and not _settings.google.tracking.pixel_url:
            raise HTTPException(
                status_code=status.HTTP_501_NOT_IMPLEMENTED,
                detail="Open tracking requested but tracking.pixel_url is not configured",
            )
        if body.enable_click_tracking and not _settings.google.tracking.click_url:
            raise HTTPException(
                status_code=status.HTTP_501_NOT_IMPLEMENTED,
                detail="Click tracking requested but tracking.click_url is not configured",
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

        # -----------------------------------------------------------------
        # Step 3: html / template mode → send via Mailgun, record in Chatwoot
        # -----------------------------------------------------------------
        if body.content_mode in ("html", "template"):
            from vital_chatwoot_bridge.core.config import get_settings as _gs
            from vital_chatwoot_bridge.integrations.mailgun_client import MailgunClient, MailgunClientError
            from vital_chatwoot_bridge.email.renderer import get_renderer, EmailTemplateRenderer

            _cfg = _gs()
            recipient_email = body.to_emails or body.contact.email or body.contact.identifier
            subject = body.subject or ""

            # Resolve HTML content
            if body.content_mode == "template":
                renderer = get_renderer()
                if not renderer:
                    raise HTTPException(status_code=501, detail="Email template renderer is not initialized")
                if body.template_name not in renderer.template_names:
                    raise HTTPException(
                        status_code=422,
                        detail=f"Unknown template: {body.template_name}. Available: {renderer.template_names}",
                    )
                tpl_vars = dict(body.template_vars or {})
                html_content = renderer.render(body.template_name, tpl_vars)
                if not subject:
                    subject = renderer.render_subject(body.template_name, tpl_vars)
            else:
                # html mode — message.content IS the raw HTML
                html_content = body.message.content
                # Wrap bare HTML in a proper document if missing <html> tag
                if "<html" not in html_content.lower():
                    html_content = (
                        "<!DOCTYPE html>\n"
                        '<html lang="en">\n<head>\n'
                        '<meta charset="utf-8">\n'
                        '<meta name="viewport" content="width=device-width, initial-scale=1.0">\n'
                        "</head>\n<body>\n"
                        f"{html_content}\n"
                        "</body>\n</html>"
                    )

            # Send via Mailgun
            mg_client = MailgunClient(_cfg.mailgun)
            try:
                mg_result = await mg_client.send_email(
                    to=recipient_email,
                    subject=subject,
                    html=html_content,
                    from_email=body.from_email,
                    cc=body.cc_emails,
                    bcc=body.bcc_emails,
                )
            except MailgunClientError as mge:
                logger.error(f"❌ Mailgun send failed in POST /messages: {mge}")
                raise HTTPException(
                    status_code=mge.status_code or 502,
                    detail=f"Mailgun send failed: {mge}",
                )
            finally:
                await mg_client.close()

            # Record in Chatwoot as a private outgoing note.
            # - Can't use "incoming" on non-API inboxes (Chatwoot rejects it)
            # - Can't use public "outgoing" because Chatwoot would dispatch a
            #   duplicate email through its own SMTP with mangled HTML
            # - Private note is visible to agents and won't trigger delivery
            mailgun_id = mg_result.get("id", "")
            body_content = EmailTemplateRenderer.extract_body_content(html_content)
            record_content = (
                f"📧 **Email sent via Mailgun**\n\n"
                f"**To:** {recipient_email}\n"
                f"**Subject:** {subject}\n"
                f"**Mailgun ID:** {mailgun_id}\n\n"
                f"---\n\n"
                f"{body_content}"
            )
            record_payload = {
                "content": record_content,
                "content_type": "input_email",
                "message_type": "outgoing",
                "private": True,
                "content_attributes": {"mailgun_sent": True, "mailgun_id": mailgun_id},
            }

            result = await client.send_message_raw(
                account_id, conversation_id, record_payload
            )

            return SingleResponse(
                data={
                    "contact_id": contact_id,
                    "conversation_id": conversation_id,
                    "message": result,
                    "mailgun": mg_result,
                }
            )

        # -----------------------------------------------------------------
        # Step 3b: gmail_template → render, inject tracking, send via Gmail,
        #          record in Chatwoot as private outgoing note
        # -----------------------------------------------------------------
        if body.content_mode == "gmail_template":
            import uuid
            from urllib.parse import quote as _url_quote
            from vital_chatwoot_bridge.core.config import get_settings as _gs
            from vital_chatwoot_bridge.integrations.gmail_client import GmailClient, GmailClientError
            from vital_chatwoot_bridge.email.renderer import get_renderer, EmailTemplateRenderer

            _cfg = _gs()
            recipient_email = body.to_emails or body.contact.email or body.contact.identifier

            # Render template
            renderer = get_renderer()
            if not renderer:
                raise HTTPException(status_code=501, detail="Email template renderer is not initialized")
            if body.template_name not in renderer.template_names:
                raise HTTPException(
                    status_code=422,
                    detail=f"Unknown template: {body.template_name}. Available: {renderer.template_names}",
                )

            tpl_vars = dict(body.template_vars or {})

            # CTA: caller specifies destination via body.cta_url
            # Body text may contain {cta} placeholder, replaced with the link
            original_cta = body.cta_url or ""
            tracking_msg_id = str(uuid.uuid4())
            tracking = _cfg.google.tracking
            campaign = body.campaign or tracking.default_campaign or ""
            lead = body.lead_id or ""

            if original_cta:
                if body.enable_click_tracking and tracking.click_url:
                    link_url = (
                        f"{tracking.click_url}"
                        f"?m={tracking_msg_id}&c={campaign}&l={lead}"
                        f"&e=cta_click&url={_url_quote(original_cta)}"
                    )
                else:
                    link_url = original_cta
                # Replace {{CTA}}link text{{/CTA}} in body_text with <a> tag
                if "body_text" in tpl_vars:
                    def _cta_replace(m):
                        return f'<a href="{link_url}" style="color: #1a73e8; text-decoration: underline;">{m.group(1)}</a>'
                    tpl_vars["body_text"] = re.sub(
                        r"\{\{CTA\}\}(.+?)\{\{/CTA\}\}", _cta_replace, tpl_vars["body_text"]
                    )
                # Set cta_url for templates with a dedicated CTA section
                tpl_vars["cta_url"] = link_url

            html_content = renderer.render(body.template_name, tpl_vars)
            subject = renderer.render_subject(body.template_name, tpl_vars)

            # Post-render: inject open-tracking pixel
            if body.enable_open_tracking and tracking.pixel_url:
                pixel_tag = (
                    f'<img src="{tracking.pixel_url}'
                    f"?m={tracking_msg_id}&c={campaign}&l={lead}&e=open"
                    f'" width="1" height="1" style="display:none" alt="" />'
                )
                html_content = html_content.replace("<!-- TRACKING_PIXEL -->", pixel_tag)

            # Send via Gmail
            gmail_client = GmailClient(_cfg.google)
            try:
                gmail_result = await gmail_client.send_email(
                    sender_email=body.gmail_sender,
                    to=recipient_email,
                    subject=subject,
                    html=html_content,
                    cc=body.cc_emails,
                    bcc=body.bcc_emails,
                )
            except GmailClientError as ge:
                logger.error(f"❌ Gmail send failed in POST /messages: {ge}")
                raise HTTPException(
                    status_code=ge.status_code or 502,
                    detail=f"Gmail send failed: {ge}",
                )
            finally:
                await gmail_client.close()

            # Record in Chatwoot as private outgoing note
            gmail_id = gmail_result.get("id", "")
            gmail_thread_id = gmail_result.get("threadId", "")
            body_content = EmailTemplateRenderer.extract_body_content(html_content)
            cta_line = f"**CTA:** [{original_cta}]({original_cta})\n" if original_cta else ""
            record_content = (
                f"📧 **Email sent via Gmail**\n\n"
                f"**From:** {body.gmail_sender}\n"
                f"**To:** {recipient_email}\n"
                f"**Subject:** {subject}\n"
                f"{cta_line}"
                f"**Gmail Message ID:** {gmail_id}\n"
                f"**Thread ID:** {gmail_thread_id}\n\n"
                f"---\n\n"
                f"{body_content}"
            )
            record_payload = {
                "content": record_content,
                "content_type": "input_email",
                "message_type": "outgoing",
                "private": True,
                "content_attributes": {
                    "gmail_sent": True,
                    "gmail_id": gmail_id,
                    "gmail_thread_id": gmail_thread_id,
                },
            }

            result = await client.send_message_raw(
                account_id, conversation_id, record_payload
            )

            return SingleResponse(
                data={
                    "contact_id": contact_id,
                    "conversation_id": conversation_id,
                    "message": result,
                    "gmail": gmail_result,
                    "tracking_msg_id": tracking_msg_id,
                }
            )

        # -----------------------------------------------------------------
        # Step 3c (text / markdown): Build and send via Chatwoot as before
        # -----------------------------------------------------------------
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

        # Merge caller-supplied content_attributes
        if body.content_attributes:
            # email_html_content must be a top-level Chatwoot API param
            # (MessageBuilder checks @params[:email_html_content] to bypass markdown)
            email_html = body.content_attributes.pop("email_html_content", None)
            if email_html:
                msg_payload["email_html_content"] = email_html
            if body.content_attributes:
                existing = msg_payload.get("content_attributes", {})
                existing.update(body.content_attributes)
                msg_payload["content_attributes"] = existing

        # Email-specific top-level params
        if body.subject:
            msg_payload["subject"] = body.subject
        if body.to_emails:
            msg_payload["to_emails"] = body.to_emails
        if body.cc_emails:
            msg_payload["cc_emails"] = body.cc_emails
        if body.bcc_emails:
            msg_payload["bcc_emails"] = body.bcc_emails

        # Resolve attachments (base64 decode or URL fetch)
        attachments = None
        if body.attachments:
            attachments = await _resolve_attachments(body.attachments)

        result = await client.send_message_raw(
            account_id, conversation_id, msg_payload, attachments=attachments
        )

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


# ── Communications Timeline ──────────────────────────────────────────

MAX_CONVERSATIONS = 20
MAX_MESSAGES_PER_CONVERSATION = 50


def _parse_message_created_at(msg: Dict[str, Any]) -> Optional[str]:
    """Extract an ISO 8601 timestamp from a Chatwoot message dict."""
    raw = msg.get("created_at")
    if raw is None:
        return None
    if isinstance(raw, (int, float)):
        return datetime.utcfromtimestamp(raw).isoformat() + "Z"
    return str(raw)


def _message_direction(msg: Dict[str, Any]) -> str:
    mt = msg.get("message_type")
    if mt in ("incoming", 0):
        return "inbound"
    return "outbound"


def _message_sender(msg: Dict[str, Any]) -> CommunicationSender:
    sender = msg.get("sender") or {}
    name = sender.get("name") or sender.get("available_name") or "Unknown"
    stype = sender.get("type", "contact")
    if stype == "user":
        stype = "agent"
    return CommunicationSender(name=name, type=stype)


async def _resolve_contact_by_query(
    client, account_id: int, email: Optional[str], phone: Optional[str],
) -> Dict[str, Any]:
    """Search for a contact matching the given email/phone.

    If both are provided, prefer a contact matching both; otherwise
    return the first exact match. Raises HTTPException on failure.
    """
    candidates: List[Dict[str, Any]] = []
    search_terms = [t for t in (email, phone) if t]

    for term in search_terms:
        try:
            data = await client.search_contacts(account_id, q=term)
            for c in data.get("payload", []):
                if c.get("id") not in [x.get("id") for x in candidates]:
                    candidates.append(c)
        except ChatwootAPIError:
            pass

    if not candidates:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Contact not found",
        )

    # Score candidates: +1 for each field match
    def _score(c: Dict) -> int:
        s = 0
        if email and (c.get("email") or "").lower() == email.lower():
            s += 1
        if phone and c.get("phone_number") == phone:
            s += 1
        return s

    candidates.sort(key=_score, reverse=True)
    best = candidates[0]
    if _score(best) == 0:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Contact not found",
        )
    if len(candidates) > 1:
        logger.warning(
            f"Ambiguous contact match for email={email} phone={phone}: "
            f"returning contact {best.get('id')} (score={_score(best)})"
        )
    return best


@router.get("/communications", response_model=CommunicationsResponse)
async def get_communications(
    email: Optional[str] = None,
    phone: Optional[str] = None,
    inbox_id: Optional[int] = None,
    since: Optional[str] = None,
    until: Optional[str] = None,
    user: AuthenticatedUser = Depends(get_current_user),
):
    """Get unified communications timeline for a contact.

    Resolve the contact by ``email`` and/or ``phone``, then return up to
    20 most recent conversations with up to 50 most recent messages each.
    Optionally filter by ``inbox_id`` and ``since``/``until`` (ISO 8601).
    """
    if not email and not phone:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="At least one of 'email' or 'phone' is required",
        )

    # Parse date filters
    since_dt: Optional[datetime] = None
    until_dt: Optional[datetime] = None
    try:
        if since:
            since_dt = datetime.fromisoformat(since.replace("Z", "+00:00"))
        if until:
            until_dt = datetime.fromisoformat(until.replace("Z", "+00:00"))
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid date format: {exc}",
        )

    try:
        client = await get_chatwoot_client()
        account_id = _account_id()
        inbox_cache = get_inbox_cache()

        # Step 1: Resolve contact
        contact = await _resolve_contact_by_query(client, account_id, email, phone)
        contact_id = int(contact["id"])

        # Step 2: Fetch conversations (cap at MAX_CONVERSATIONS)
        convs_data = await client.get_contact_conversations(account_id, contact_id)
        all_convs = convs_data.get("payload", [])

        # Filter by inbox_id if specified
        if inbox_id is not None:
            all_convs = [c for c in all_convs if c.get("inbox_id") == inbox_id]

        # Sort by last_activity_at (newest first) and cap
        all_convs.sort(
            key=lambda c: c.get("last_activity_at") or c.get("created_at") or 0,
            reverse=True,
        )
        capped_convs = all_convs[:MAX_CONVERSATIONS]

        # Step 3: Fetch messages for each conversation in parallel
        async def _fetch_messages(conv: Dict) -> List[Dict]:
            cid = int(conv["id"])
            try:
                data = await client.get_conversation_messages_raw(account_id, cid)
                msgs = data.get("payload", [])
                # Sort newest first, cap at MAX_MESSAGES_PER_CONVERSATION
                msgs.sort(
                    key=lambda m: m.get("created_at") or 0,
                    reverse=True,
                )
                return msgs[:MAX_MESSAGES_PER_CONVERSATION]
            except ChatwootAPIError:
                logger.warning(f"Failed to fetch messages for conversation {cid}")
                return []

        message_lists = await asyncio.gather(
            *[_fetch_messages(c) for c in capped_convs]
        )

        # Step 4: Build enriched response
        result_conversations: List[CommunicationConversation] = []
        all_channels: set = set()
        total_messages = 0
        all_timestamps: List[str] = []

        for conv, msgs in zip(capped_convs, message_lists):
            conv_inbox_id = int(conv.get("inbox_id", 0))
            channel = await inbox_cache.get_channel(conv_inbox_id)
            inbox_name = await inbox_cache.get_inbox_name(conv_inbox_id)
            all_channels.add(channel)

            enriched_msgs: List[CommunicationMessage] = []
            for m in msgs:
                ts = _parse_message_created_at(m)
                if ts is None:
                    continue

                # Date filtering
                if since_dt or until_dt:
                    try:
                        msg_dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                    except ValueError:
                        continue
                    if since_dt and msg_dt < since_dt:
                        continue
                    if until_dt and msg_dt > until_dt:
                        continue

                # Extract subject from content_attributes if present
                ca = m.get("content_attributes") or {}
                subject = ca.get("email", {}).get("subject") if isinstance(ca.get("email"), dict) else None

                enriched_msgs.append(CommunicationMessage(
                    id=int(m.get("id", 0)),
                    direction=_message_direction(m),
                    content=m.get("content") or "",
                    content_type=m.get("content_type", "text"),
                    channel=channel,
                    subject=subject,
                    sender=_message_sender(m),
                    created_at=ts,
                ))
                all_timestamps.append(ts)

            total_messages += len(enriched_msgs)

            conv_created = conv.get("created_at")
            if isinstance(conv_created, (int, float)):
                conv_created = datetime.utcfromtimestamp(conv_created).isoformat() + "Z"

            result_conversations.append(CommunicationConversation(
                id=int(conv["id"]),
                inbox_id=conv_inbox_id,
                inbox_name=inbox_name,
                channel=channel,
                status=conv.get("status", "unknown"),
                created_at=str(conv_created or ""),
                messages=enriched_msgs,
            ))

        # Build summary
        date_range = {}
        if all_timestamps:
            sorted_ts = sorted(all_timestamps)
            date_range = {"earliest": sorted_ts[0], "latest": sorted_ts[-1]}

        summary = CommunicationSummary(
            total_conversations=len(result_conversations),
            total_messages=total_messages,
            channels=sorted(all_channels),
            date_range=date_range,
        )

        contact_out = CommunicationContact(
            id=contact_id,
            name=contact.get("name"),
            email=contact.get("email"),
            phone_number=contact.get("phone_number"),
        )

        return CommunicationsResponse(
            success=True,
            data={
                "contact": contact_out.model_dump(),
                "conversations": [c.model_dump() for c in result_conversations],
                "summary": summary.model_dump(),
            },
        )

    except HTTPException:
        raise
    except ChatwootAPIError as e:
        raise _handle_api_error(e)
    except Exception as e:
        logger.error(f"Error in get_communications: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Communications lookup failed: {str(e)}",
        )


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


# ---------------------------------------------------------------------------
# Templated Email
# ---------------------------------------------------------------------------

@router.post("/email/send-template", response_model=SingleResponse)
async def send_templated_email(
    body: SendTemplatedEmailRequest,
    user: AuthenticatedUser = Depends(get_current_user),
):
    """
    Render a Jinja2 email template and send via Chatwoot.

    The template is rendered with the provided variables, then delivered
    as an HTML email using ``content_type="input_email"``.
    """
    renderer = get_renderer()
    if renderer is None:
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail="Email templates are not configured (missing CW_BRIDGE__email_templates__* env vars)",
        )

    if body.template_name not in renderer.template_names:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Unknown template: {body.template_name}. "
                   f"Available: {renderer.template_names}",
        )

    # Merge reserved keys into template vars for subject rendering
    all_vars = {**body.template_vars, "to": body.to}
    if body.subject:
        all_vars["subject"] = body.subject

    try:
        full_html = renderer.render(body.template_name, all_vars)
        # Chatwoot wraps emails in its own layout (base.liquid) which provides
        # <!DOCTYPE>, <html>, <head>, <body>.  Extract only the inner body
        # content so it nests cleanly inside Chatwoot's layout.
        html = renderer.extract_body_content(full_html)
        subject = body.subject or renderer.render_subject(body.template_name, all_vars)
    except Exception as e:
        logger.error(f"Template render error: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Template render failed: {e}",
        )

    # Build a PostMessageRequest-compatible call through the existing pipeline
    try:
        client = await get_chatwoot_client()
        account_id = _account_id()
        inbox_id = body.inbox_id

        # Resolve contact
        contact_info = {"identifier": body.to, "email": body.to}
        if body.contact_name:
            contact_info["name"] = body.contact_name

        contact = await _resolve_contact(client, account_id, inbox_id, PostMessageContact(**contact_info))

        contact_id = contact.get("id") or contact.get("payload", {}).get("contact", {}).get("id")
        if not contact_id:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to resolve contact ID",
            )

        conversation_id = await _resolve_conversation(
            client, account_id, inbox_id, contact_id, "reuse_newest"
        )

        # Body-only HTML (outer document wrapper stripped) goes in content.
        # CommonMarker with :DEFAULT preserves raw HTML, and Chatwoot's
        # base.liquid layout provides the outer document structure.
        msg_payload = {
            "content": html,
            "content_type": "input_email",
            "message_type": "outgoing",
            "private": body.suppress_delivery,
        }
        if body.suppress_delivery:
            msg_payload["content_attributes"] = {"logged_outbound": True}
        if subject:
            msg_payload["subject"] = subject
        if body.to:
            msg_payload["to_emails"] = body.to
        if body.cc:
            msg_payload["cc_emails"] = body.cc
        if body.bcc:
            msg_payload["bcc_emails"] = body.bcc

        result = await client.send_message_raw(account_id, conversation_id, msg_payload)

        return SingleResponse(
            data={
                "contact_id": contact_id,
                "conversation_id": conversation_id,
                "template_name": body.template_name,
                "subject": subject,
                "message": result,
            }
        )

    except ChatwootAPIError as e:
        raise _handle_api_error(e)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in send_templated_email: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )
