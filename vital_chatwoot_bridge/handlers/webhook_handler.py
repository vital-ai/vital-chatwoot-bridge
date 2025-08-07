"""
Clean webhook handler with simplified models - temporary file for reference.
"""

import asyncio
import json
import logging
import uuid
from datetime import datetime
from typing import Dict, Any, Optional
from pydantic import ValidationError

from vital_chatwoot_bridge.core.config import get_settings
from vital_chatwoot_bridge.core.models import (
    BridgeToAgentMessage, MessageSender, MessageContext, ResponseMode,
    WebhookResponse, ErrorResponse
)
from vital_chatwoot_bridge.chatwoot.models import (
    ChatwootWebhookEvent, ChatwootWebhookMessageData
)
from vital_chatwoot_bridge.agents.websocket_manager import WebSocketManager
from vital_chatwoot_bridge.chatwoot.api_client import ChatwootAPIClient

logger = logging.getLogger(__name__)


class WebhookHandler:
    """Handle Chatwoot webhook events."""
    
    def __init__(self, websocket_manager: WebSocketManager, api_client: ChatwootAPIClient):
        self.websocket_manager = websocket_manager
        self.api_client = api_client
        self.settings = get_settings()
    
    async def handle_webhook(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Handle incoming webhook from Chatwoot."""
        try:
            logger.info(f"📨 REST: Received Chatwoot webhook")
            logger.info(f"📨 REST: Webhook payload keys: {list(payload.keys())}")
            
            # Parse the webhook event
            webhook_event = ChatwootWebhookEvent(**payload)
            event_type = webhook_event.event
            
            logger.info(f"📨 REST: Processing webhook event type: {event_type}")
            
            # Route based on event type
            if webhook_event.event == "message_created":
                return await self._handle_message_created(webhook_event)
            else:
                logger.info(f"📨 REST: Ignoring event type: {webhook_event.event}")
                return WebhookResponse(
                    status="ignored",
                    message=f"Event type {webhook_event.event} not handled"
                ).dict()
        
        except Exception as e:
            logger.error(f"Webhook handling error: {str(e)}", exc_info=True)
            return ErrorResponse(
                error=f"Failed to process webhook: {str(e)}",
                error_code="webhook_processing_error"
            ).dict()
    
    async def _handle_message_created(self, event_data: ChatwootWebhookEvent) -> Dict[str, Any]:
        """Handle message_created webhook event."""
        try:
            
            # Check if this is an incoming message (from customer)
            if event_data.message_type != "incoming":
                logger.debug(f"Ignoring outgoing message {event_data.id}")
                return WebhookResponse(
                    status="ignored",
                    message="Outgoing message ignored"
                ).dict()
            
            # Find agent configuration for this inbox
            inbox_id = None
            if "inbox_id" in event_data.conversation:
                inbox_id = str(event_data.conversation.get("inbox_id"))
            elif hasattr(event_data, 'inbox') and event_data.inbox:
                inbox_id = str(event_data.inbox.get("id")) if isinstance(event_data.inbox, dict) else None
            
            if not inbox_id:
                logger.error(f"Could not extract inbox_id from webhook payload")
                return WebhookResponse(
                    status="error",
                    message="Could not extract inbox_id from payload"
                ).dict()
            
            logger.info(f"🎯 WEBHOOK: Extracted inbox_id: '{inbox_id}' from webhook payload")
            
            agent_config = self.settings.get_agent_for_inbox(inbox_id)
            if not agent_config:
                logger.warning(f"No agent configured for inbox {inbox_id}")
                # Debug: show available inbox mappings
                available_inboxes = [mapping.inbox_id for mapping in self.settings.inbox_agent_mappings]
                logger.warning(f"Available inbox mappings: {available_inboxes}")
                return WebhookResponse(
                    status="ignored",
                    message=f"No agent configured for inbox {inbox_id}"
                ).dict()
            
            logger.info(f"🎯 WEBHOOK: Selected agent '{agent_config.agent_id}' for inbox '{inbox_id}'")
            
            # Create bridge message
            message_id = str(uuid.uuid4())
            bridge_message = BridgeToAgentMessage(
                message_id=message_id,
                inbox_id=inbox_id,
                conversation_id=event_data.conversation.get("id"),
                content=event_data.content,
                sender=MessageSender(
                    id=str(event_data.sender.get("id", "unknown")),
                    name=event_data.sender.get("name", "Unknown"),
                    email=event_data.sender.get("email"),
                    type=event_data.sender.get("type", "contact")
                ),
                context=MessageContext(
                    channel=event_data.conversation.get("channel", "web_widget"),
                    created_at=datetime.fromisoformat(event_data.created_at.replace('Z', '+00:00')),
                    additional_attributes=event_data.conversation.get("additional_attributes", {})
                ),
                response_mode=ResponseMode.SYNC
            )
            
            logger.info(f"Sending message {message_id} to agent {agent_config.agent_id}")
            
            # Send message to agent and get response
            response = await self._send_message_sync(agent_config, bridge_message)
            
            if response:
                # Post response back to Chatwoot immediately
                await self._post_response_to_chatwoot(
                    event_data.account.get("id"),
                    event_data.conversation.get("id"),
                    response,
                    private=False
                )
                
                return WebhookResponse(
                    status="processed_sync",
                    message="Message processed and response sent",
                    data={"response_content": response}
                ).dict()
            else:
                # Fallback response if agent doesn't respond in time
                fallback_msg = "I apologize, but I'm experiencing technical difficulties. Please try again in a moment."
                await self._post_response_to_chatwoot(
                    event_data.account.get("id"),
                    event_data.conversation.get("id"),
                    fallback_msg,
                    private=False
                )
                
                return WebhookResponse(
                    status="processed_fallback",
                    message="Fallback response sent due to agent timeout"
                ).dict()
        
        except ValidationError as e:
            logger.error(f"Invalid message_created payload: {e}")
            return ErrorResponse(
                error="invalid_payload",
                error_code="invalid_payload"
            ).dict()
        
        except Exception as e:
            logger.error(f"Error processing message: {str(e)}", exc_info=True)
            return ErrorResponse(
                error="processing_error",
                error_code="message_processing_failed"
            ).dict()
    
    async def _handle_conversation_created(self, event_data: ChatwootWebhookMessageData) -> Dict[str, Any]:
        """Handle conversation_created webhook event."""
        try:
            logger.info(f"New conversation created: {event_data.conversation.get('id')} in inbox {event_data.conversation.get('inbox_id')}")
            
            return WebhookResponse(
                status="acknowledged",
                message=f"Conversation {event_data.conversation.get('id')} created"
            ).dict()
        
        except ValidationError as e:
            logger.error(f"Invalid conversation_created payload: {e}")
            return ErrorResponse(
                error="invalid_payload",
                error_code="invalid_payload"
            ).dict()
        
        except Exception as e:
            logger.error(f"Error processing conversation creation: {str(e)}", exc_info=True)
            return ErrorResponse(
                error="processing_error",
                error_code="conversation_creation_failed"
            ).dict()
    
    async def _handle_webwidget_triggered(self, event_data: ChatwootWebhookMessageData) -> Dict[str, Any]:
        """Handle webwidget_triggered webhook event."""
        try:
            logger.info(f"Web widget triggered for contact {event_data.sender.get('id')} in inbox {event_data.conversation.get('inbox_id')}")
            
            return WebhookResponse(
                status="acknowledged",
                message="Web widget triggered"
            ).dict()
        
        except ValidationError as e:
            logger.error(f"Invalid webwidget_triggered payload: {e}")
            return ErrorResponse(
                error="invalid_payload",
                error_code="invalid_payload"
            ).dict()
        
        except Exception as e:
            logger.error(f"Error processing web widget trigger: {str(e)}", exc_info=True)
            return ErrorResponse(
                error="processing_error",
                error_code="webwidget_processing_failed"
            ).dict()
    
    async def _send_message_sync(self, agent_config, bridge_message: BridgeToAgentMessage) -> Optional[str]:
        """Send message to agent synchronously and wait for response."""
        try:
            response = await self.websocket_manager.send_message_sync(
                agent_config.websocket_url,
                bridge_message,
                timeout=agent_config.timeout_seconds
            )
            
            if response and response.success:
                return response.content
            else:
                logger.warning(f"Agent response failed or empty: {response}")
                return None
        
        except Exception as e:
            logger.error(f"Error sending sync message to agent: {str(e)}")
            return None
    
    async def _post_response_to_chatwoot(self, account_id: int, conversation_id: int, content: str, private: bool = False):
        """Post response back to Chatwoot."""
        try:
            await self.api_client.send_message(
                account_id=account_id,
                conversation_id=conversation_id,
                content=content,
                message_type="outgoing",
                private=private
            )
            logger.info(f"Posted response to Chatwoot conversation {conversation_id}")
        
        except Exception as e:
            logger.error(f"Failed to post response to Chatwoot: {str(e)}")
