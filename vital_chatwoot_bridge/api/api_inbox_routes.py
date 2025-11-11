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


@api_inbox_router.post("/attentive/webhook")
async def handle_attentive_webhook(
    request: Request,
    service: APIInboxService = Depends(get_api_inbox_service)
) -> Dict[str, Any]:
    """
    Receive Attentive webhook and process for Chatwoot aggregation.
    
    This endpoint receives webhook events from Attentive for message
    aggregation in Chatwoot. Supports sms.sent, email.sent, and 
    sms.inbound_message event types.
    
    Args:
        request: Raw HTTP request
        service: API inbox service dependency
        
    Returns:
        Processing result with Chatwoot conversation details
        
    Raises:
        HTTPException: If processing fails
    """
    try:
        # Get raw JSON payload for debugging
        raw_payload = await request.json()
        logger.info(f"📨 Raw Attentive webhook payload: {raw_payload}")
        
        # Try to validate the payload
        try:
            validated_request = AttentiveWebhookRequest(**raw_payload)
            logger.info(f"📨 Received Attentive webhook: {validated_request.type}")
        except Exception as validation_error:
            logger.error(f"❌ Attentive webhook validation failed: {validation_error}")
            logger.error(f"❌ Raw payload that failed validation: {raw_payload}")
            raise HTTPException(
                status_code=422,
                detail={
                    "success": False,
                    "error": "Validation failed",
                    "message": str(validation_error),
                    "payload": raw_payload
                }
            )
        
        result = await service.process_attentive_webhook(validated_request)
        
        logger.info(f"✅ Attentive webhook processed successfully: {validated_request.type}")
        return {
            "success": True,
            "message": f"Attentive {validated_request.type} webhook processed successfully",
            "data": result
        }
        
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


# Note: Exception handlers are handled in individual endpoint try/catch blocks
# since APIRouter doesn't support exception_handler decorators
