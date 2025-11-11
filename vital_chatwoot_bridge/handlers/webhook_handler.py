"""
Clean webhook handler with simplified models - temporary file for reference.
"""

import asyncio
import json
import logging
import uuid
from datetime import datetime
from typing import Dict, Any, Optional, List
from pydantic import ValidationError

from vital_chatwoot_bridge.core.config import get_settings
from vital_chatwoot_bridge.core.models import (
    BridgeToAgentMessage, MessageSender, MessageContext, ResponseMode,
    WebhookResponse, ErrorResponse
)
from vital_chatwoot_bridge.chatwoot.models import (
    ChatwootWebhookEvent, ChatwootWebhookMessageData
)
from vital_chatwoot_bridge.agents.aimp_message_client import AimpMessageClient
from vital_chatwoot_bridge.agents.models import AgentChatResponse
from vital_chatwoot_bridge.chatwoot.api_client import ChatwootAPIClient
from vital_chatwoot_bridge.services.api_inbox_service import APIInboxService
from vital_chatwoot_bridge.chatwoot.client_models import LoopMessageOutboundRequest

logger = logging.getLogger(__name__)


class WebhookHandler:
    """Handle Chatwoot webhook events."""
    
    def __init__(self, api_client: ChatwootAPIClient):
        self.websocket_client = AimpMessageClient()
        self.api_client = api_client
        self.settings = get_settings()
        self.api_inbox_service = APIInboxService()
    
    async def handle_webhook(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Handle incoming webhook from Chatwoot."""
        try:
            logger.info(f"📨 REST: Received Chatwoot webhook")
            logger.info(f"📨 REST: Webhook payload keys: {list(payload.keys())}")
            
            # First, determine the event type without parsing the full payload
            event_type = payload.get("event", "unknown")
            logger.info(f"📨 REST: Processing webhook event type: {event_type}")
            
            # Route based on event type
            if event_type == "message_created":
                # Only parse as ChatwootWebhookEvent for message_created events
                webhook_event = ChatwootWebhookEvent(**payload)
                return await self._handle_message_created(webhook_event)
            else:
                logger.info(f"📨 REST: Ignoring event type: {event_type}")
                return WebhookResponse(
                    status="ignored",
                    message=f"Event type {event_type} not handled"
                ).model_dump()
        
        except Exception as e:
            logger.error(f"Webhook handling error: {str(e)}", exc_info=True)
            return ErrorResponse(
                error=f"Failed to process webhook: {str(e)}",
                error_code="webhook_processing_error"
            ).model_dump()
    
    async def _handle_message_created(self, event_data: ChatwootWebhookEvent) -> Dict[str, Any]:
        """Handle message_created webhook event."""
        try:
            # Convert integer message_type to string if needed
            message_type_str = self._normalize_message_type(event_data.message_type)
            
            # Main webhook only handles inbound messages for agent processing
            # Outbound messages are handled by separate endpoint: /api/v1/inboxes/loopmessage/messages/outbound
            
            # Check if this is an incoming message (from customer)
            if message_type_str != "incoming":
                logger.debug(f"Ignoring message type {message_type_str} ({event_data.message_type}) for message {event_data.id}")
                return WebhookResponse(
                    status="ignored",
                    message=f"Message type {message_type_str} ignored"
                ).model_dump()
            
            # Check if sender is an agent (not a contact) to prevent responding to our own messages
            sender_type = event_data.sender.get("type", "").lower()
            if sender_type == "user" or sender_type == "agent":
                logger.debug(f"Ignoring message from agent/user {event_data.id}")
                return WebhookResponse(
                    status="ignored",
                    message="Agent/user message ignored"
                ).model_dump()
            
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
                ).model_dump()
            
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
                ).model_dump()
            
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
            
            # Send message to agent and get responses
            responses = await self._send_message_to_agent(agent_config, bridge_message)
            
            if responses:
                # Post all responses to Chatwoot
                account_id = event_data.account.get("id")
                conversation_id = event_data.conversation.get("id")
                
                for response in responses:
                    if response.success:
                        await self._post_response_to_chatwoot(
                            account_id,
                            conversation_id,
                            response.content,
                            private=False
                        )
                
                # Return first response content in webhook response
                first_response = responses[0]
                return WebhookResponse(
                    status="processed_sync",
                    message=f"Message processed and {len(responses)} response(s) sent",
                    data={
                        "response_content": first_response.content,
                        "total_responses": len(responses)
                    }
                ).model_dump()
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
                ).model_dump()
        
        except ValidationError as e:
            logger.error(f"Invalid message_created payload: {e}")
            return ErrorResponse(
                error="invalid_payload",
                error_code="invalid_payload"
            ).model_dump()
        
        except Exception as e:
            logger.error(f"Error processing message: {str(e)}", exc_info=True)
            return ErrorResponse(
                error="processing_error",
                error_code="message_processing_failed"
            ).model_dump()
    
    async def _handle_outbound_message(self, event_data: ChatwootWebhookEvent) -> Dict[str, Any]:
        """Handle outbound message for LoopMessage integration."""
        try:
            # Extract inbox information - use internal inbox ID from conversation
            chatwoot_inbox_id = None
            if "inbox_id" in event_data.conversation:
                chatwoot_inbox_id = str(event_data.conversation.get("inbox_id"))
            elif hasattr(event_data, 'inbox') and event_data.inbox:
                chatwoot_inbox_id = str(event_data.inbox.get("id")) if isinstance(event_data.inbox, dict) else None
            
            if not chatwoot_inbox_id:
                logger.error(f"Could not extract chatwoot_inbox_id from outbound message webhook")
                return WebhookResponse(
                    status="error",
                    message="Could not extract chatwoot_inbox_id from payload"
                ).model_dump()
            
            logger.info(f"📤 WEBHOOK: Processing outbound message for Chatwoot inbox ID: {chatwoot_inbox_id}")
            
            # Check if this is an API inbox by looking up the internal Chatwoot inbox ID
            logger.info(f"🔍 DEBUG: Looking up API inbox config for Chatwoot inbox ID: {chatwoot_inbox_id}")
            api_inbox_config = self.settings.get_api_inbox_by_chatwoot_id(chatwoot_inbox_id)
            logger.info(f"🔍 DEBUG: API inbox config result: {api_inbox_config}")
            if not api_inbox_config:
                logger.info(f"🔍 DEBUG: Chatwoot inbox ID {chatwoot_inbox_id} is not an API inbox, ignoring outbound message")
                return WebhookResponse(
                    status="ignored",
                    message="Not an API inbox"
                ).model_dump()
            
            # Check if it's specifically a LoopMessage inbox that supports outbound
            logger.info(f"🔍 DEBUG: Found API inbox config: {api_inbox_config.name}")
            logger.info(f"🔍 DEBUG: API inbox identifier: {api_inbox_config.inbox_identifier}")
            
            # Check if this is the LoopMessage inbox by comparing with known LoopMessage config
            loopmessage_config = self.settings.get_api_inbox_config("loopmessage")
            if not loopmessage_config or api_inbox_config.inbox_identifier != loopmessage_config.inbox_identifier:
                logger.info(f"🔍 DEBUG: This is not the LoopMessage inbox (found: {api_inbox_config.name}), ignoring outbound message")
                return WebhookResponse(
                    status="ignored",
                    message="Not a LoopMessage inbox"
                ).model_dump()
            
            if not api_inbox_config.supports_outbound:
                logger.debug(f"LoopMessage inbox does not support outbound messages")
                return WebhookResponse(
                    status="ignored",
                    message="LoopMessage inbox does not support outbound"
                ).model_dump()
            
            # Check sender type - only allow agent/bot responses, NOT customer messages
            sender_type = event_data.sender.get("type", "").lower()
            logger.info(f"🔍 DEBUG: Sender type: {sender_type}")
            
            # Only process outbound messages from agents/bots, NOT from customers
            if sender_type in ["contact"]:
                logger.info(f"🔍 DEBUG: Ignoring outbound message from {sender_type} - customer messages should not be sent back to customer")
                return WebhookResponse(
                    status="ignored",
                    message=f"Customer message ignored - not sending back to customer"
                ).model_dump()
            
            # Only exclude system messages and customer messages
            if sender_type in ["system"]:
                logger.info(f"🔍 DEBUG: Ignoring outbound message from {sender_type} - system messages not sent to LoopMessage")
                return WebhookResponse(
                    status="ignored",
                    message=f"System message ignored"
                ).model_dump()
            
            # Only allow agent/bot responses to be sent outbound
            if sender_type in ["user", "agent", "agent_bot", "bot"]:
                logger.info(f"🔍 DEBUG: Processing outbound message from {sender_type}")
            else:
                logger.info(f"🔍 DEBUG: Unknown sender type {sender_type} - ignoring to be safe")
                return WebhookResponse(
                    status="ignored",
                    message=f"Unknown sender type {sender_type} ignored"
                ).model_dump()
            
            # For outbound webhooks, try to extract phone number from conversation metadata first
            contact_phone = None
            
            # Check if phone number is available in conversation meta or other fields
            logger.info(f"🔍 DEBUG: Checking webhook payload for phone number")
            logger.info(f"🔍 DEBUG: Full conversation data: {event_data.conversation}")
            
            # Try to get phone from conversation meta if available
            if "meta" in event_data.conversation:
                meta = event_data.conversation["meta"]
                logger.info(f"🔍 DEBUG: Conversation meta: {meta}")
                if "sender" in meta:
                    sender_info = meta["sender"]
                    contact_phone = sender_info.get("phone_number") or sender_info.get("phone")
                    logger.info(f"🔍 DEBUG: Phone from conversation meta.sender: {contact_phone}")
            
            # If no phone number found, try API call as fallback (will fail with bot token)
            if not contact_phone:
                try:
                    conversation_id = event_data.conversation.get("id")
                    logger.info(f"🔍 DEBUG: No phone in webhook payload, trying Chatwoot API for conversation {conversation_id}")
                    
                    # Create Chatwoot API client instance
                    from vital_chatwoot_bridge.chatwoot.api_client import ChatwootAPIClient
                    api_client = ChatwootAPIClient()
                    
                    conversation_data = await api_client.get_conversation(
                        account_id=self.settings.chatwoot_account_id,
                        conversation_id=conversation_id
                    )
                    
                    if conversation_data:
                        logger.info(f"🔍 DEBUG: Fetched conversation data from API")
                        
                        # Convert Pydantic model to dict if needed
                        if hasattr(conversation_data, 'model_dump'):
                            conversation_dict = conversation_data.model_dump()
                        elif hasattr(conversation_data, 'dict'):
                            conversation_dict = conversation_data.dict()
                        else:
                            conversation_dict = conversation_data
                        
                        # Try to get contact phone from the API response
                        if "contact" in conversation_dict:
                            contact_info = conversation_dict["contact"]
                            contact_phone = contact_info.get("phone_number") or contact_info.get("phone")
                            logger.info(f"🔍 DEBUG: Phone from API contact: {contact_phone}")
                        
                        # Try meta sender if available
                        if not contact_phone and "meta" in conversation_dict and "sender" in conversation_dict["meta"]:
                            sender_info = conversation_dict["meta"]["sender"]
                            contact_phone = sender_info.get("phone_number") or sender_info.get("phone")
                            logger.info(f"🔍 DEBUG: Phone from API meta.sender: {contact_phone}")
                    else:
                        logger.warning(f"🔍 DEBUG: No conversation data returned from API")
                        
                except Exception as e:
                    logger.warning(f"🔍 DEBUG: Error fetching conversation from API: {e}")
            
            logger.info(f"🔍 DEBUG: Final phone number: {contact_phone}")
            if not contact_phone:
                logger.warning(f"🔍 DEBUG: Could not extract phone number for LoopMessage outbound message - ignoring this webhook call")
                return WebhookResponse(
                    status="ignored",
                    message="Could not extract phone number - likely duplicate webhook call"
                ).model_dump()
            
            # Get agent information
            agent_name = "Chatwoot Agent"
            if event_data.sender.get("type") in ["user", "agent"]:
                agent_name = event_data.sender.get("name", "Chatwoot Agent")
            
            logger.info(f"🔍 DEBUG: Agent name: {agent_name}")
            logger.info(f"🔍 DEBUG: Message content: {event_data.content}")
            
            # Create LoopMessage outbound request
            outbound_request = LoopMessageOutboundRequest(
                phone_number=contact_phone,
                message_content=event_data.content,
                conversation_id=str(event_data.conversation.get("id")),
                chatwoot_message_id=str(event_data.id),
                agent_name=agent_name
            )
            
            logger.info(f"📤 WEBHOOK: Sending LoopMessage to {contact_phone}: {event_data.content[:50]}...")
            logger.info(f"🔍 DEBUG: About to call process_loopmessage_outbound")
            
            # Process the outbound message via API inbox service
            result = await self.api_inbox_service.process_loopmessage_outbound(outbound_request)
            logger.info(f"🔍 DEBUG: LoopMessage API result: {result}")
            
            logger.info(f"✅ WEBHOOK: LoopMessage outbound processed successfully")
            return WebhookResponse(
                status="processed",
                message="LoopMessage outbound sent successfully",
                data={
                    "phone_number": contact_phone,
                    "delivery_status": result.get("delivery_status", "unknown"),
                    "loopmessage_message_id": result.get("loopmessage_result", {}).get("message_id")
                }
            ).model_dump()
            
        except Exception as e:
            logger.error(f"Error processing LoopMessage outbound: {str(e)}", exc_info=True)
            return WebhookResponse(
                status="error",
                message=f"Failed to process LoopMessage outbound: {str(e)}"
            ).model_dump()
    
    async def _handle_conversation_created(self, event_data: ChatwootWebhookMessageData) -> Dict[str, Any]:
        """Handle conversation_created webhook event."""
        try:
            logger.info(f"New conversation created: {event_data.conversation.get('id')} in inbox {event_data.conversation.get('inbox_id')}")
            
            return WebhookResponse(
                status="acknowledged",
                message=f"Conversation {event_data.conversation.get('id')} created"
            ).model_dump()
        
        except ValidationError as e:
            logger.error(f"Invalid conversation_created payload: {e}")
            return ErrorResponse(
                error="invalid_payload",
                error_code="invalid_payload"
            ).model_dump()
        
        except Exception as e:
            logger.error(f"Error processing conversation creation: {str(e)}", exc_info=True)
            return ErrorResponse(
                error="processing_error",
                error_code="conversation_creation_failed"
            ).model_dump()
    
    async def _handle_webwidget_triggered(self, event_data: ChatwootWebhookMessageData) -> Dict[str, Any]:
        """Handle webwidget_triggered webhook event."""
        try:
            logger.info(f"Web widget triggered for contact {event_data.sender.get('id')} in inbox {event_data.conversation.get('inbox_id')}")
            
            return WebhookResponse(
                status="acknowledged",
                message="Web widget triggered"
            ).model_dump()
        
        except ValidationError as e:
            logger.error(f"Invalid webwidget_triggered payload: {e}")
            return ErrorResponse(
                error="invalid_payload",
                error_code="invalid_payload"
            ).model_dump()
        
        except Exception as e:
            logger.error(f"Error processing web widget trigger: {str(e)}", exc_info=True)
            return ErrorResponse(
                error="processing_error",
                error_code="webwidget_processing_failed"
            ).model_dump()
    
    async def _send_message_to_agent(self, agent_config, bridge_message: BridgeToAgentMessage) -> List[AgentChatResponse]:
        """Send message to agent and handle multiple responses."""
        try:
            # Send message and get all responses
            responses = await self.websocket_client.send_message_with_responses(
                agent_config.websocket_url,
                bridge_message,
                timeout=agent_config.timeout_seconds,
                max_responses=getattr(agent_config, 'max_responses', 5)
            )
            
            return responses
        
        except Exception as e:
            logger.error(f"Error sending message to agent: {str(e)}")
            return []
    
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
    
    def _normalize_message_type(self, message_type) -> str:
        """Convert integer message_type to string format."""
        if isinstance(message_type, int):
            # Chatwoot integer message types: 0=incoming, 1=outgoing, 2=activity/template
            if message_type == 0:
                return "incoming"
            elif message_type == 1:
                return "outgoing"
            elif message_type == 2:
                return "activity"
            else:
                return "unknown"
        elif isinstance(message_type, str):
            return message_type.lower()
        else:
            return "unknown"
