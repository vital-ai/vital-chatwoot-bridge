"""
API Inbox Service for processing messages from different inbox types.
Handles the complete flow from external systems to Chatwoot via Client API.
"""

import logging
from typing import Dict, Any, Optional
from datetime import datetime

from vital_chatwoot_bridge.core.config import get_settings, APIInboxConfig
from vital_chatwoot_bridge.chatwoot.client_api import ChatwootClientAPI, ChatwootClientAPIError
from vital_chatwoot_bridge.chatwoot.client_models import (
    ChatwootContact, ChatwootClientMessage,
    LoopMessageInboundRequest, LoopMessageOutboundRequest,
    AttentiveWebhookRequest, AttentiveEmailReplyRequest, AttentiveInboundRequest,
    APIInboxMessageRequest
)
from vital_chatwoot_bridge.integrations.loopmessage_client import (
    create_loopmessage_client, LoopMessageClientError
)

logger = logging.getLogger(__name__)


class APIInboxServiceError(Exception):
    """Exception raised for API inbox service errors."""
    pass


class APIInboxService:
    """Service for handling API inbox message operations."""
    
    def __init__(self):
        self.settings = get_settings()
    
    async def process_loopmessage_inbound(
        self, 
        request: LoopMessageInboundRequest
    ) -> Dict[str, Any]:
        """
        Process inbound iMessage from LoopMessage app.
        
        Args:
            request: LoopMessage inbound request
            
        Returns:
            Dictionary with processing results
            
        Raises:
            APIInboxServiceError: If processing fails
        """
        try:
            # Get LoopMessage inbox configuration
            inbox_config = self.settings.get_api_inbox_config("loopmessage")
            if not inbox_config:
                raise APIInboxServiceError("LoopMessage inbox not configured")
            
            # Convert to Chatwoot models
            contact = ChatwootContact(
                identifier=request.contact.phone_number,
                name=request.contact.name,
                phone_number=request.contact.phone_number
            )
            
            message = ChatwootClientMessage(
                content=request.message_content,
                message_type="incoming"
            )
            
            # Post to Chatwoot
            async with ChatwootClientAPI() as client:
                result = await client.post_message_to_inbox(
                    inbox_identifier=inbox_config.inbox_identifier,
                    contact=contact,
                    message=message,
                    conversation_id=request.conversation_id
                )
            
            logger.info(f"✅ LoopMessage inbound message processed successfully")
            return {
                "status": "success",
                "inbox_type": "loopmessage",
                "direction": "inbound",
                "chatwoot_result": result
            }
            
        except ChatwootClientAPIError as e:
            error_msg = f"Chatwoot API error processing LoopMessage: {str(e)}"
            logger.error(error_msg)
            raise APIInboxServiceError(error_msg)
        except Exception as e:
            error_msg = f"Unexpected error processing LoopMessage: {str(e)}"
            logger.error(error_msg)
            raise APIInboxServiceError(error_msg)
    
    async def process_attentive_webhook(
        self,
        webhook_payload: AttentiveWebhookRequest
    ) -> Dict[str, Any]:
        """
        Process Attentive webhook and convert to Chatwoot message.
        
        Args:
            webhook_payload: Attentive webhook payload
            
        Returns:
            Dictionary with processing results
            
        Raises:
            APIInboxServiceError: If processing fails
        """
        try:
            # Get Attentive inbox configuration
            inbox_config = self.settings.get_api_inbox_config("attentive")
            if not inbox_config:
                raise APIInboxServiceError("Attentive inbox not configured")
            
            # Parse webhook payload
            event_type = webhook_payload.type
            subscriber = webhook_payload.subscriber
            message_data = webhook_payload.message
            
            # Determine sender direction
            sender_type = "business" if event_type in ["sms.sent", "email.sent"] else "customer"
            message_type = "sms" if "sms" in event_type else "email"
            
            # Extract contact information
            # Convert external_id to string if it's an integer (Attentive sends it as int)
            external_id = subscriber.get("external_id")
            if external_id is not None:
                external_id = str(external_id)
            
            contact = ChatwootContact(
                identifier=external_id or subscriber.get("phone") or subscriber.get("email") or "unknown",
                name=subscriber.get("name"),
                email=subscriber.get("email"),
                phone_number=subscriber.get("phone")
            )
            
            # Extract message content (handle both test format and real Attentive API format)
            message_content = (
                message_data.get("text") or           # Test script format
                message_data.get("content") or        # Real Attentive API format
                message_data.get("subject") or        # Email fallback
                "No content"
            )
            
            # Create Chatwoot message
            message = ChatwootClientMessage(
                content=message_content,
                message_type="incoming" if sender_type == "customer" else "outgoing"
            )
            
            # Post to Chatwoot
            async with ChatwootClientAPI() as client:
                result = await client.post_message_to_inbox(
                    inbox_identifier=inbox_config.inbox_identifier,
                    contact=contact,
                    message=message,
                    custom_attributes={
                        "attentive_event_type": event_type,
                        "attentive_message_id": message_data.get("id"),
                        "attentive_timestamp": int(webhook_payload.timestamp / 1000) if webhook_payload.timestamp else None,  # Convert ms to seconds
                        "sender_type": sender_type,
                        "message_type": message_type
                    }
                )
            
            logger.info(f"✅ Attentive webhook processed successfully: {event_type}")
            return {
                "status": "success",
                "inbox_type": "attentive",
                "direction": "webhook",
                "event_type": event_type,
                "sender_type": sender_type,
                "chatwoot_result": result
            }
            
        except ChatwootClientAPIError as e:
            error_msg = f"Chatwoot API error processing Attentive webhook: {str(e)}"
            logger.error(error_msg)
            raise APIInboxServiceError(error_msg)
        except Exception as e:
            error_msg = f"Unexpected error processing Attentive webhook: {str(e)}"
            logger.error(error_msg)
            raise APIInboxServiceError(error_msg)
    
    async def process_attentive_email_reply(
        self,
        email_reply: AttentiveEmailReplyRequest
    ) -> Dict[str, Any]:
        """
        Process email reply (outside Attentive webhooks) and convert to Chatwoot message.
        
        Args:
            email_reply: Email reply request
            
        Returns:
            Dictionary with processing results
            
        Raises:
            APIInboxServiceError: If processing fails
        """
        try:
            # Get Attentive inbox configuration
            inbox_config = self.settings.get_api_inbox_config("attentive")
            if not inbox_config:
                raise APIInboxServiceError("Attentive inbox not configured")
            
            # Convert to Chatwoot models
            contact = ChatwootContact(
                identifier=email_reply.contact.email or email_reply.from_email,
                name=email_reply.contact.name,
                email=email_reply.contact.email or email_reply.from_email,
                phone_number=email_reply.contact.phone_number
            )
            
            # Format message content with subject if available
            message_content = email_reply.message_content
            if email_reply.subject:
                message_content = f"Subject: {email_reply.subject}\n\n{message_content}"
            
            message = ChatwootClientMessage(
                content=message_content,
                message_type="incoming"  # Email replies are always from customers
            )
            
            # Post to Chatwoot
            async with ChatwootClientAPI() as client:
                result = await client.post_message_to_inbox(
                    inbox_identifier=inbox_config.inbox_identifier,
                    contact=contact,
                    message=message,
                    custom_attributes={
                        "message_type": "email",
                        "sender_type": "customer",
                        "from_email": email_reply.from_email,
                        "to_email": email_reply.to_email,
                        "reply_to_message_id": email_reply.reply_to_message_id,
                        "email_headers": email_reply.email_headers
                    }
                )
            
            logger.info(f"✅ Attentive email reply processed successfully")
            return {
                "status": "success",
                "inbox_type": "attentive",
                "direction": "email_reply",
                "sender_type": "customer",
                "chatwoot_result": result
            }
            
        except ChatwootClientAPIError as e:
            error_msg = f"Chatwoot API error processing Attentive email reply: {str(e)}"
            logger.error(error_msg)
            raise APIInboxServiceError(error_msg)
        except Exception as e:
            error_msg = f"Unexpected error processing Attentive email reply: {str(e)}"
            logger.error(error_msg)
            raise APIInboxServiceError(error_msg)
    
    async def process_loopmessage_outbound(
        self,
        request: LoopMessageOutboundRequest
    ) -> Dict[str, Any]:
        """
        Process outbound iMessage from Chatwoot to LoopMessage.
        
        Args:
            request: LoopMessage outbound request
            
        Returns:
            Dictionary with processing results
            
        Raises:
            APIInboxServiceError: If processing fails
        """
        try:
            # Get LoopMessage inbox configuration
            inbox_config = self.settings.get_api_inbox_config("loopmessage")
            if not inbox_config:
                raise APIInboxServiceError("LoopMessage inbox not configured")
            
            if not inbox_config.supports_outbound:
                raise APIInboxServiceError("LoopMessage inbox does not support outbound messages")
            
            # Check for required API credentials
            if not self.settings.loopmessage_authorization_key or not self.settings.loopmessage_secret_key:
                raise APIInboxServiceError("LoopMessage API credentials not configured")
            
            # Create LoopMessage client and send message
            from vital_chatwoot_bridge.integrations.loopmessage_client import LoopMessageConfig, LoopMessageClient
            
            config = LoopMessageConfig(
                authorization_key=self.settings.loopmessage_authorization_key,
                secret_key=self.settings.loopmessage_secret_key,
                base_url=self.settings.loopmessage_api_url
            )
            client = LoopMessageClient(config)
            
            async with client:
                result = await client.send_message(
                    recipient=request.phone_number,
                    text=request.message_content,
                    sender_name=self.settings.loopmessage_sender_name,
                    passthrough=f"chatwoot_conversation_id:{request.conversation_id},chatwoot_message_id:{request.chatwoot_message_id}"
                )
            
            logger.info(f"📤 LoopMessage outbound message sent successfully: {request.phone_number}")
            return {
                "status": "success",
                "inbox_type": "loopmessage",
                "direction": "outbound",
                "phone_number": request.phone_number,
                "message_content": request.message_content,
                "loopmessage_result": result,
                "delivery_status": "sent"
            }
            
        except LoopMessageClientError as e:
            error_msg = f"LoopMessage API error: {str(e)}"
            logger.error(error_msg)
            raise APIInboxServiceError(error_msg)
        except Exception as e:
            error_msg = f"Error processing LoopMessage outbound: {str(e)}"
            logger.error(error_msg)
            raise APIInboxServiceError(error_msg)
    
    def _get_inbox_config(self, inbox_type: str) -> APIInboxConfig:
        """
        Get configuration for specific inbox type.
        
        Args:
            inbox_type: Type of API inbox
            
        Returns:
            APIInboxConfig for the specified inbox type
            
        Raises:
            APIInboxServiceError: If inbox type is not configured
        """
        config = self.settings.get_api_inbox_config(inbox_type)
        if not config:
            raise APIInboxServiceError(f"API inbox '{inbox_type}' not configured")
        return config
