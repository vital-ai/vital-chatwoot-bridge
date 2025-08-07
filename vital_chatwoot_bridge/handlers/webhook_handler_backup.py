"""
Webhook handlers for processing Chatwoot events.
"""

import asyncio
import logging
import uuid
from typing import Dict, Any, Optional
from datetime import datetime

from fastapi import HTTPException
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
    """Handles incoming Chatwoot webhook events."""
    
    def __init__(self, websocket_manager: WebSocketManager, chatwoot_client: ChatwootAPIClient):
        self.websocket_manager = websocket_manager
        self.chatwoot_client = chatwoot_client
        self.settings = get_settings()
        
        # Track pending synchronous responses
        self.pending_sync_responses: Dict[str, asyncio.Future] = {}
    
    async def handle_webhook(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Main webhook handler that routes events to specific handlers.
        
        Args:
            payload: Raw webhook payload from Chatwoot
            
        Returns:
            Webhook response or error response
        """
        try:
            # Extract event type
            event_type = payload.get("event")
            if not event_type:
                raise ValueError("Missing 'event' field in webhook payload")
            
            logger.info(f"Received webhook event: {event_type}")
            
            # Route to specific handler
            if event_type == "message_created":
                return await self._handle_message_created(payload)
            elif event_type == "conversation_created":
                return await self._handle_conversation_created(payload)
            elif event_type == "webwidget_triggered":
                return await self._handle_webwidget_triggered(payload)
            else:
                logger.warning(f"Unhandled webhook event type: {event_type}")
                return WebhookResponse(
                    status="ignored",
                    error_code="unsupported_event_type"
                ).dict()
        
        except Exception as e:
            logger.error(f"Webhook handling error: {str(e)}", exc_info=True)
            return ErrorResponse(
                error=f"Failed to process webhook: {str(e)}",
                error_code="webhook_processing_error"
            ).dict()
    
    async def _handle_message_created(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Handle message_created webhook event."""
        try:
            # Parse the webhook event data
            event_data = ChatwootWebhookMessageData(**payload)
            
            # Check if this is an incoming message (from customer)
            if event_data.message_type != "incoming":
                logger.debug(f"Ignoring outgoing message {event_data.id}")
                return WebhookResponse(
                    status="ignored",
                    message="Outgoing message ignored"
                ).dict()
            
            # Find agent configuration for this inbox
            inbox_id = event_data.conversation.get("inbox_id")
            agent_config = self.settings.get_agent_for_inbox(inbox_id)
            if not agent_config:
                logger.warning(f"No agent configured for inbox {event.inbox.id}")
                return WebhookResponse(
                    status="ignored",
                    message=f"No agent configured for inbox {event.inbox.id}"
                ).dict()
            
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
                    account_id=event_data.account.get("id"),
                    channel=event_data.conversation.get("channel", "web_widget"),
                    timestamp=datetime.fromisoformat(event_data.created_at.replace('Z', '+00:00')),
                    conversation_status=event_data.conversation.get("status"),
                    additional_attributes=event_data.conversation.get("additional_attributes", {})
                ),
                response_mode=ResponseMode.SYNC  # Always use sync for now
            )
            
            logger.info(f"Sending message {message_id} to agent {agent_config.agent_id}")
            
            # Send to AI agent
            if bridge_message.response_mode == ResponseMode.SYNC:
                # Synchronous response - wait for agent reply
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
            else:
                # Asynchronous response - send and don't wait
                asyncio.create_task(
                    self._send_message_async(agent_config, bridge_message, event_data.account.get("id"), event_data.conversation.get("id"))
                )
                
                return WebhookResponse(
                    status="processing_async",
                    message="Message sent to agent for async processing"
                ).dict()
        
        except ValidationError as e:
            logger.error(f"Invalid message_created payload: {e}")
            return ErrorResponse(
                error="invalid_payload",
                error_code="invalid_payload"
            ).dict()
        
        except Exception as e:
            logger.error(f"Error handling message_created: {e}", exc_info=True)
            return ErrorResponse(
                error="processing_error",
                error_code="message_processing_failed"
            ).dict()
    
    async def _handle_conversation_created(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Handle conversation_created webhook event."""
        try:
            event = ChatwootConversationCreatedEvent(**payload)
            
            logger.info(f"New conversation created: {event.id} in inbox {event.inbox_id}")
            
            # For now, just acknowledge the event
            # In the future, we might want to send a welcome message or initialize agent context
            
            return WebhookResponse(
                status="acknowledged",
                message=f"Conversation {event.id} created"
            ).dict()
        
        except ValidationError as e:
            logger.error(f"Invalid conversation_created payload: {e}")
            return ErrorResponse(
                error="invalid_payload",
                error_code="invalid_payload"
            ).dict()
        
        except Exception as e:
            logger.error(f"Error handling conversation_created: {e}", exc_info=True)
            return ErrorResponse(
                error="processing_error",
                error_code="conversation_creation_failed"
            ).dict()
    
    async def _handle_webwidget_triggered(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Handle webwidget_triggered webhook event."""
        try:
            event = ChatwootWebWidgetTriggeredEvent(**payload)
            
            logger.info(f"Web widget triggered for contact {event.contact.id} in inbox {event.inbox.id}")
            
            # Find agent configuration for this inbox
            agent_config = self.settings.get_agent_for_inbox(event.inbox.id)
            if not agent_config:
                logger.warning(f"No agent configured for inbox {event.inbox.id}")
                return WebhookResponse(
                    status="ignored",
                    message=f"No agent configured for inbox {event.inbox.id}"
                ).dict()
            
            # Send welcome message if configured
            if agent_config.send_welcome_message:
                welcome_msg = agent_config.welcome_message or "Hello! How can I help you today?"
                
                # Create a conversation if one doesn't exist
                if not event.current_conversation:
                    # This would typically be handled by Chatwoot automatically
                    logger.info("Web widget triggered without existing conversation")
                
                return WebhookResponse(
                    status="welcome_ready",
                    message="Web widget triggered, ready to send welcome message"
                ).dict()
            
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
            logger.error(f"Error handling webwidget_triggered: {e}", exc_info=True)
            return ErrorResponse(
                error="processing_error",
                error_code="webwidget_processing_failed"
            ).dict()
    
    async def _send_message_sync(self, agent_config, bridge_message: BridgeToAgentMessage) -> Optional[str]:
        """Send message to agent and wait for synchronous response."""
        try:
            # Send message to agent via WebSocket
            response = await self.websocket_manager.send_message_sync(
                agent_config.websocket_url,
                bridge_message,
                timeout=self.settings.default_response_timeout
            )
            
            if response and response.content:
                return response.content
            
            return None
        
        except Exception as e:
            logger.error(f"Error sending sync message to agent: {e}")
            return None
    
    async def _send_message_async(self, agent_config, bridge_message: BridgeToAgentMessage, account_id: int, conversation_id: int):
        """Send message to agent asynchronously and handle response separately."""
        try:
            # Send message to agent via WebSocket
            response = await self.websocket_manager.send_message_async(
                agent_config.websocket_url,
                bridge_message
            )
            
            if response and response.content:
                # Post response back to Chatwoot
                await self._post_response_to_chatwoot(
                    account_id,
                    conversation_id,
                    response.content,
                    private=False
                )
                
                logger.info(f"Async response posted for conversation {conversation_id}")
            else:
                logger.warning(f"No response received from agent for message {bridge_message.message_id}")
        
        except Exception as e:
            logger.error(f"Error in async message processing: {e}")
            
            # Send error message to Chatwoot
            error_msg = "I apologize, but I encountered an error processing your message. Please try again."
            try:
                await self._post_response_to_chatwoot(
                    account_id,
                    conversation_id,
                    error_msg,
                    private=False
                )
            except Exception as post_error:
                logger.error(f"Failed to post error message to Chatwoot: {post_error}")
    
    async def _post_response_to_chatwoot(self, account_id: int, conversation_id: int, content: str, private: bool = False):
        """Post a response back to Chatwoot."""
        try:
            await self.chatwoot_client.send_message(
                account_id=account_id,
                conversation_id=conversation_id,
                content=content,
                message_type="outgoing",
                private=private
            )
            
            logger.info(f"Response posted to Chatwoot conversation {conversation_id}")
        
        except Exception as e:
            logger.error(f"Failed to post response to Chatwoot: {e}")
            raise
