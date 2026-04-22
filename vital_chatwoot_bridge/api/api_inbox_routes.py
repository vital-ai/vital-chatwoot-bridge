"""
API Inbox Routes for handling external system integrations.
Provides REST endpoints for LoopMessage and Attentive inbox operations.
"""

import logging
from typing import Dict, Any
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, Request
from fastapi.responses import JSONResponse

from vital_chatwoot_bridge.services.api_inbox_service import APIInboxService, APIInboxServiceError
from vital_chatwoot_bridge.chatwoot.client_models import (
    LoopMessageInboundRequest, LoopMessageOutboundRequest,
    AttentiveWebhookRequest, AttentiveEmailReplyRequest
)
from vital_chatwoot_bridge.email.models import MailgunSendEmailRequest, GmailSendEmailRequest

logger = logging.getLogger(__name__)

# Create API router for inbox operations
api_inbox_router = APIRouter(prefix="/api/v1/inboxes", tags=["API Inboxes"])


def get_api_inbox_service() -> APIInboxService:
    """Dependency to get API inbox service instance."""
    return APIInboxService()


@api_inbox_router.post("/loopmessage/messages/inbound")
async def post_loopmessage_inbound(
    request: LoopMessageInboundRequest,
    service: APIInboxService = Depends(get_api_inbox_service)
) -> Dict[str, Any]:
    """
    Receive iMessage from webhook server and post to Chatwoot.
    
    This endpoint is called by your webhook server when it receives
    an iMessage from LoopMessage that should be forwarded to Chatwoot.
    
    Flow: LoopMessage → Your Webhook Server → This Bridge → Chatwoot
    
    Args:
        request: LoopMessage inbound message request
        service: API inbox service dependency
        
    Returns:
        Processing result with Chatwoot conversation details
        
    Raises:
        HTTPException: If processing fails
    """
    try:
        logger.info(f"📨 Received LoopMessage inbound from webhook server: {request.contact.phone_number}")
        
        result = await service.process_loopmessage_inbound(request)
        
        logger.info(f"✅ LoopMessage inbound processed successfully")
        return {
            "success": True,
            "message": "LoopMessage inbound processed successfully",
            "data": result
        }
        
    except APIInboxServiceError as e:
        logger.error(f"❌ LoopMessage inbound processing failed: {str(e)}")
        raise HTTPException(
            status_code=400,
            detail={
                "success": False,
                "error": "Processing failed",
                "message": str(e)
            }
        )
    except Exception as e:
        logger.error(f"❌ Unexpected error in LoopMessage inbound: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail={
                "success": False,
                "error": "Internal server error",
                "message": "An unexpected error occurred"
            }
        )


@api_inbox_router.post("/loopmessage/messages/outbound")
async def post_loopmessage_outbound(
    request: Request,
    background_tasks: BackgroundTasks,
    service: APIInboxService = Depends(get_api_inbox_service)
) -> Dict[str, Any]:
    """
    Receive outbound message from Chatwoot webhook and send to LoopMessage.
    
    This endpoint is called by Chatwoot webhooks when an agent sends
    a reply that should be forwarded to LoopMessage as an iMessage.
    
    Args:
        request: Raw FastAPI request (Chatwoot webhook payload)
        background_tasks: FastAPI background tasks
        service: API inbox service dependency
        
    Returns:
        Processing acknowledgment
        
    Raises:
        HTTPException: If processing fails
    """
    try:
        # Parse the webhook payload
        webhook_data = await request.json()
        logger.info(f"📤 Received LoopMessage outbound webhook")
        logger.info(f"🔍 DEBUG: Webhook payload keys: {list(webhook_data.keys())}")
        
        # Validate this is for LoopMessage inbox
        conversation = webhook_data.get("conversation", {})
        chatwoot_inbox_id = str(conversation.get("inbox_id"))
        
        # Check if this is the LoopMessage inbox
        from vital_chatwoot_bridge.core.config import get_settings
        settings = get_settings()
        api_inbox_config = settings.get_api_inbox_by_chatwoot_id(chatwoot_inbox_id)
        
        if not api_inbox_config:
            logger.info(f"🔍 DEBUG: Inbox {chatwoot_inbox_id} is not an API inbox, ignoring")
            return {"success": True, "message": "Not an API inbox, ignored"}
        
        # Check if it's LoopMessage inbox
        loopmessage_config = settings.get_api_inbox_config("loopmessage")
        if not loopmessage_config or api_inbox_config.inbox_identifier != loopmessage_config.inbox_identifier:
            logger.info(f"🔍 DEBUG: Not LoopMessage inbox, ignoring")
            return {"success": True, "message": "Not LoopMessage inbox, ignored"}
        
        # Process outbound message in background to avoid webhook timeout
        background_tasks.add_task(
            _process_loopmessage_outbound_webhook,
            service,
            webhook_data
        )
        
        logger.info(f"✅ LoopMessage outbound webhook queued for processing")
        return {
            "success": True,
            "message": "LoopMessage outbound webhook queued for processing",
            "conversation_id": conversation.get("id")
        }
        
    except Exception as e:
        logger.error(f"❌ Error queuing LoopMessage outbound: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail={
                "success": False,
                "error": "Internal server error",
                "message": "Failed to queue outbound message"
            }
        )


@api_inbox_router.post("/attentive/webhook", status_code=202)
async def handle_attentive_webhook(
    request: Request,
    service: APIInboxService = Depends(get_api_inbox_service)
) -> Dict[str, Any]:
    """
    Receive Attentive webhook and process for Chatwoot aggregation.
    
    This endpoint receives webhook events from Attentive for message
    aggregation in Chatwoot. Supports sms.sent, email.sent, and 
    sms.inbound_message event types.

    Processing is asynchronous — the webhook is enqueued and a 202 Accepted
    response is returned immediately.  If the queue is full, 429 is returned
    so Attentive can retry later.
    
    Args:
        request: Raw HTTP request
        service: API inbox service dependency
        
    Returns:
        202 Accepted with queue position info
        
    Raises:
        HTTPException: If enqueue fails or event is filtered
    """
    from vital_chatwoot_bridge.core.config import get_settings
    from vital_chatwoot_bridge.services.webhook_queue import get_worker_pool

    settings = get_settings()

    try:
        raw_payload = await request.json()

        # ---- Event-type filtering ----------------------------------------
        event_type = raw_payload.get("type", "")
        if event_type not in settings.rl_attentive_allowed_events:
            logger.debug(
                f"� Attentive event filtered (not in allowlist): {event_type}"
            )
            return {
                "success": True,
                "message": f"Event type '{event_type}' filtered by allowlist",
                "filtered": True,
            }

        # ---- Validate payload --------------------------------------------
        try:
            validated_request = AttentiveWebhookRequest(**raw_payload)
            logger.info(f"📨 Received Attentive webhook: {validated_request.type}")
        except Exception as validation_error:
            logger.error(f"❌ Attentive webhook validation failed: {validation_error}")
            raise HTTPException(
                status_code=422,
                detail={
                    "success": False,
                    "error": "Validation failed",
                    "message": str(validation_error),
                }
            )

        # ---- Enqueue for async processing --------------------------------
        pool = get_worker_pool()
        if pool is not None:
            ok = await pool.enqueue(raw_payload)
            if not ok:
                logger.warning("🚦 Attentive webhook queue full — returning 429")
                raise HTTPException(
                    status_code=429,
                    detail={
                        "success": False,
                        "error": "Queue full",
                        "message": "Too many pending webhooks, please retry later",
                    }
                )
            depth = await pool.queue.depth()
            logger.info(f"📨 Attentive webhook enqueued ({event_type}), queue depth={depth}")
            return {
                "success": True,
                "message": f"Attentive {event_type} webhook accepted for processing",
                "queued": True,
                "queue_depth": depth,
            }

        # ---- Fallback: inline processing (pool not started) ---------------
        logger.warning("⚠️ Worker pool not available, processing Attentive webhook inline")
        result = await service.process_attentive_webhook(validated_request)
        return {
            "success": True,
            "message": f"Attentive {event_type} webhook processed (inline)",
            "data": result,
        }

    except HTTPException:
        raise
    except APIInboxServiceError as e:
        logger.error(f"❌ Attentive webhook processing failed: {str(e)}")
        raise HTTPException(
            status_code=400,
            detail={
                "success": False,
                "error": "Processing failed",
                "message": str(e)
            }
        )
    except Exception as e:
        logger.error(f"❌ Unexpected error in Attentive webhook: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail={
                "success": False,
                "error": "Internal server error",
                "message": "An unexpected error occurred"
            }
        )


@api_inbox_router.post("/attentive/email/inbound")
async def handle_attentive_email_reply(
    request: AttentiveEmailReplyRequest,
    service: APIInboxService = Depends(get_api_inbox_service)
) -> Dict[str, Any]:
    """
    Receive email reply (outside Attentive webhooks) and post to Chatwoot for aggregation.
    
    This endpoint handles customer email replies that are captured outside
    of Attentive's webhook system and need to be aggregated in Chatwoot.
    
    Args:
        request: Email reply request
        service: API inbox service dependency
        
    Returns:
        Processing result with Chatwoot conversation details
        
    Raises:
        HTTPException: If processing fails
    """
    try:
        logger.info(f"📨 Received Attentive email reply from {request.from_email}")
        
        result = await service.process_attentive_email_reply(request)
        
        logger.info(f"✅ Attentive email reply processed successfully")
        return {
            "success": True,
            "message": "Attentive email reply processed successfully",
            "data": result
        }
        
    except APIInboxServiceError as e:
        logger.error(f"❌ Attentive email reply processing failed: {str(e)}")
        raise HTTPException(
            status_code=400,
            detail={
                "success": False,
                "error": "Processing failed",
                "message": str(e)
            }
        )
    except Exception as e:
        logger.error(f"❌ Unexpected error in Attentive email reply: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail={
                "success": False,
                "error": "Internal server error",
                "message": "An unexpected error occurred"
            }
        )


@api_inbox_router.get("/health")
async def health_check() -> Dict[str, Any]:
    """
    Health check endpoint for API inbox functionality.
    
    Returns:
        Health status information and integration flow details
    """
    return {
        "success": True,
        "message": "API Inbox service is healthy",
        "integration_flows": {
            "loopmessage_inbound": "LoopMessage → Webhook Server → Bridge → Chatwoot",
            "loopmessage_outbound": "Chatwoot → Bridge → LoopMessage API",
            "attentive_webhook": "Attentive → Another Service → Bridge → Chatwoot",
            "attentive_email": "Email System → Bridge → Chatwoot"
        },
        "endpoints": {
            "loopmessage_inbound": "/api/v1/inboxes/loopmessage/messages/inbound",
            "loopmessage_outbound": "/api/v1/inboxes/loopmessage/messages/outbound",
            "attentive_webhook": "/api/v1/inboxes/attentive/webhook",
            "attentive_email": "/api/v1/inboxes/attentive/email/inbound"
        }
    }


async def _process_loopmessage_outbound_background(
    service: APIInboxService,
    request: LoopMessageOutboundRequest
) -> None:
    """
    Background task to process LoopMessage outbound messages.
    
    This runs in the background to avoid webhook timeout issues
    when calling the LoopMessage API.
    
    Args:
        service: API inbox service instance
        request: LoopMessage outbound request
    """
    try:
        logger.info(f"🔄 Processing LoopMessage outbound in background: {request.phone_number}")
        
        result = await service.process_loopmessage_outbound(request)
        
        logger.info(f"✅ Background LoopMessage outbound completed: {result.get('delivery_status', 'unknown')}")
        
    except APIInboxServiceError as e:
        logger.error(f"❌ Background LoopMessage outbound failed: {str(e)}")
    except Exception as e:
        logger.error(f"❌ Unexpected error in background LoopMessage outbound: {str(e)}")


async def _process_loopmessage_outbound_webhook(
    service: APIInboxService,
    webhook_data: Dict[str, Any]
) -> None:
    """
    Background task to process LoopMessage outbound messages from Chatwoot webhook.
    
    This runs in the background to avoid webhook timeout issues
    when calling the LoopMessage API.
    
    Args:
        service: API inbox service instance
        webhook_data: Chatwoot webhook payload
    """
    try:
        logger.info(f"🔄 Processing LoopMessage outbound webhook in background")
        
        # Check event type - only process message_created events
        event_type = webhook_data.get("event")
        if event_type != "message_created":
            logger.info(f"🔍 DEBUG: Ignoring non-message event: {event_type}")
            return
        
        # Use the existing _handle_outbound_message logic from webhook handler
        from vital_chatwoot_bridge.handlers.webhook_handler import WebhookHandler
        from vital_chatwoot_bridge.chatwoot.models import ChatwootWebhookEvent
        from vital_chatwoot_bridge.core.config import get_settings
        
        # Convert webhook data to ChatwootWebhookEvent
        event_data = ChatwootWebhookEvent(**webhook_data)
        
        # Create webhook handler instance
        settings = get_settings()
        webhook_handler = WebhookHandler(settings)
        
        # Process the outbound message
        result = await webhook_handler._handle_outbound_message(event_data)
        
        logger.info(f"✅ Background LoopMessage outbound webhook completed: {result}")
        
    except Exception as e:
        logger.error(f"❌ Unexpected error in background LoopMessage outbound webhook: {str(e)}")


# ---------------------------------------------------------------------------
# Mailgun direct email send
# ---------------------------------------------------------------------------

@api_inbox_router.post("/mailgun/email/send")
async def post_mailgun_email_send(
    request: MailgunSendEmailRequest,
) -> Dict[str, Any]:
    """
    Send an email directly via Mailgun API.

    This is a standalone endpoint for ad-hoc / testing Mailgun sends.
    It does NOT create Chatwoot contacts or conversations.

    Requires CW_BRIDGE__mailgun__* config to be set.
    """
    from vital_chatwoot_bridge.core.config import get_settings
    from vital_chatwoot_bridge.integrations.mailgun_client import MailgunClient, MailgunClientError

    settings = get_settings()
    if not settings.mailgun:
        raise HTTPException(status_code=501, detail="Mailgun is not configured")

    if not request.html and not request.text:
        raise HTTPException(status_code=422, detail="At least one of 'html' or 'text' must be provided")

    client = MailgunClient(settings.mailgun)
    try:
        result = await client.send_email(
            to=request.to,
            subject=request.subject,
            html=request.html,
            text=request.text,
            from_email=request.from_email,
            cc=request.cc,
            bcc=request.bcc,
            reply_to=request.reply_to,
        )
        return {
            "success": True,
            "message": "Email sent via Mailgun",
            "data": result,
        }
    except MailgunClientError as e:
        logger.error(f"❌ Mailgun send failed: {e}")
        raise HTTPException(
            status_code=e.status_code or 502,
            detail={"success": False, "error": str(e), "response": e.response_data},
        )
    except Exception as e:
        logger.error(f"❌ Unexpected error in Mailgun send: {e}")
        raise HTTPException(status_code=500, detail={"success": False, "error": str(e)})
    finally:
        await client.close()


# ---------------------------------------------------------------------------
# Gmail direct email send
# ---------------------------------------------------------------------------

@api_inbox_router.post("/gmail/email/send")
async def post_gmail_email_send(
    request: GmailSendEmailRequest,
) -> Dict[str, Any]:
    """
    Send an email directly via Gmail API (service account impersonation).

    This is a standalone endpoint for ad-hoc / testing Gmail sends.
    It does NOT create Chatwoot contacts or conversations.
    It does NOT inject tracking (use POST /messages with content_mode='gmail_template' for that).

    Requires CW_BRIDGE__google__* config to be set.
    Sender must be in the allowed senders whitelist.
    """
    from vital_chatwoot_bridge.core.config import get_settings
    from vital_chatwoot_bridge.integrations.gmail_client import GmailClient, GmailClientError

    settings = get_settings()
    if not settings.google:
        raise HTTPException(status_code=501, detail="Google/Gmail is not configured")

    if not request.html and not request.text:
        raise HTTPException(status_code=422, detail="At least one of 'html' or 'text' must be provided")

    client = GmailClient(settings.google)
    try:
        result = await client.send_email(
            sender_email=request.sender,
            to=request.to,
            subject=request.subject,
            html=request.html or "",
            text=request.text,
            cc=request.cc,
            bcc=request.bcc,
        )
        return {
            "success": True,
            "message": "Email sent via Gmail",
            "data": result,
        }
    except GmailClientError as e:
        logger.error(f"❌ Gmail send failed: {e}")
        raise HTTPException(
            status_code=e.status_code or 502,
            detail={"success": False, "error": str(e), "response": e.response_data},
        )
    except Exception as e:
        logger.error(f"❌ Unexpected error in Gmail send: {e}")
        raise HTTPException(status_code=500, detail={"success": False, "error": str(e)})
    finally:
        await client.close()


# Note: Exception handlers are handled in individual endpoint try/catch blocks
# since APIRouter doesn't support exception_handler decorators
