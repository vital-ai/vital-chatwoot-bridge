"""
AIMP message client for communicating with AI agents using vital-agent-container-client.
Handles per-message connections and AIMP message protocol (contract v2, vital-agent.v2).
"""

import asyncio
import json
import logging
from typing import List, Optional, Dict, Any
from datetime import datetime

from com_vitalai_aimp_domain.model.AIMPIntent import AIMPIntent
from com_vitalai_aimp_domain.model.UserMessageContent import UserMessageContent
from vital_ai_vitalsigns.utils.uri_generator import URIGenerator
from vital_ai_vitalsigns.vitalsigns import VitalSigns
from vital_agent_container_client import (
    SUBPROTOCOL,
    AIMPMessageHandlerInf,
    AuthenticationError,
    InteractionResult,
    ProtocolMismatchError,
    VitalAgentContainerClient,
)

from vital_chatwoot_bridge.core.config import get_settings
from vital_chatwoot_bridge.core.models import BridgeToAgentMessage
from vital_chatwoot_bridge.agents.models import AgentChatResponse
from vital_chatwoot_bridge.utils.jwt_auth import create_jwt_manager_from_config

logger = logging.getLogger(__name__)

# Initialize VitalSigns
vs = VitalSigns()


class AimpMessageHandler(AIMPMessageHandlerInf):
    """Message handler to receive and store responses from the agent"""
    
    def __init__(self):
        self.response_list = []
    
    async def receive_message(self, message):
        logger.info(f"📥 AIMP: Received message from agent")
        self.response_list.append(message)
    
    def get_responses(self):
        responses = self.response_list.copy()
        self.response_list.clear()  # Clear responses after retrieving them
        return responses


class AimpMessageClient:
    """Handles per-message connections to AI agents using AIMP protocol."""
    
    def __init__(self):
        self.settings = get_settings()
        self.jwt_manager = create_jwt_manager_from_config(self.settings)
    
    async def send_message_with_responses(
        self,
        agent_url: str,
        message: BridgeToAgentMessage,
        timeout: int = 30,
        max_responses: int = 5
    ) -> List[AgentChatResponse]:
        """
        Connect to agent, send AIMP message, collect all responses, then disconnect.
        
        Args:
            agent_url: HTTP URL of the agent (e.g., http://localhost:6006)
            message: Bridge message to convert to AIMP format
            timeout: Total timeout for the entire interaction
            max_responses: Maximum number of responses to collect
            
        Returns:
            List of responses from agent (can be multiple)
        """
        logger.info(f"🔌 AIMP: Connecting to agent at {agent_url}")
        logger.info(f"📤 AIMP: Sending message {message.message_id}")
        
        try:
            responses = await self._send_aimp_message(
                agent_url, message, timeout
            )
            
            logger.info(f"✅ AIMP: Received {len(responses)} responses from agent")
            return responses
            
        except Exception as e:
            logger.error(f"❌ AIMP: Error communicating with agent: {e}")
            return []
    
    async def _send_aimp_message(
        self,
        agent_url: str,
        message: BridgeToAgentMessage,
        timeout: int
    ) -> List[AgentChatResponse]:
        """Send AIMP message to agent and collect responses."""
        handler = AimpMessageHandler()
        
        # Get JWT token if available
        jwt_token = None
        if self.jwt_manager:
            logger.info("🔑 AIMP: JWT manager configured, attempting to get token")
            jwt_token = self.jwt_manager.get_keycloak_token()
            if jwt_token:
                logger.info(f"🔑 AIMP: Successfully obtained JWT token (length: {len(jwt_token)})")
                # Log first and last few characters for debugging (never log full token)
                logger.info(f"🔑 AIMP: Token preview: {jwt_token[:20]}...{jwt_token[-20:]}")
            else:
                logger.error("🔑 AIMP: Failed to obtain JWT token, proceeding without authentication")
        else:
            logger.warning("🔑 AIMP: No JWT manager configured, proceeding without authentication")
        
        client = VitalAgentContainerClient(base_url=agent_url, handler=handler, jwt_token=jwt_token)

        try:
            # Test health endpoint
            logger.info(f"🏥 AIMP: Testing agent health at {agent_url}")
            health = await client.check_health()
            if not health:
                logger.warning(f"⚠️ AIMP: Agent health check failed")

            # Create AIMP message from bridge message
            aimp_message_list = await self._create_aimp_message(message)

            # Serialize AIMP message
            message_json = vs.to_json(aimp_message_list)
            message_list = json.loads(message_json)

            # One connection per message: request() returns on the agent's "done";
            # close_after asks the server to close once the handler returns.
            # A timeout interrupts the agent's run, so it must exceed the longest
            # legitimate run.
            logger.info(f"🔗 AIMP: Opening WebSocket connection")
            async with client:
                logger.info(f"📤 AIMP: Sending AIMP message (timeout: {timeout}s)")
                logger.info(f"🔍 DEBUG: Full AIMP message being sent: {message_list}")
                result = await client.request(message_list, timeout=timeout, close_after=True)
            logger.info(f"✅ AIMP: WebSocket connection closed")

            self._log_interaction_result(result, message)

            # Get responses from handler (kept even if the interaction didn't end ok:
            # anything the agent sent before an error or timeout is still delivered)
            raw_responses = handler.get_responses()

            # Convert AIMP responses to AgentChatResponse format
            responses = []
            for raw_response in raw_responses:
                agent_response = self._parse_aimp_response(raw_response, message)
                if agent_response:
                    responses.append(agent_response)

            return responses

        except AuthenticationError as e:
            logger.error(f"❌ AIMP: Agent rejected JWT at handshake: {e}")
            return []

        except ProtocolMismatchError as e:
            logger.error(
                f"❌ AIMP: Agent at {agent_url} does not speak {SUBPROTOCOL} "
                f"(needs vital-agent-container-sdk>=0.2.0): {e}"
            )
            return []

        except Exception as e:
            logger.error(f"❌ AIMP: Error in AIMP communication: {e}")
            return []

    def _log_interaction_result(self, result: InteractionResult, message: BridgeToAgentMessage) -> None:
        """Log how the agent interaction ended."""
        if result.handler_error is not None:
            logger.error(f"❌ AIMP: Response handler raised for message {message.message_id}: {result.handler_error!r}")

        if result.ok:
            logger.info(f"✅ AIMP: Interaction {result.status} for message {message.message_id} ({result.messages_received} messages)")
            return

        if result.status == "timed_out":
            detail = "client timeout; agent run interrupted"
        elif result.close is not None and result.close.is_handler_timeout:
            detail = "agent handler timeout (4008)"
        elif result.close is not None and result.close.is_internal_error:
            detail = "agent handler error (1011)"
        elif result.close is not None and result.close.is_server_shutdown:
            detail = "agent shutting down (1001)"
        elif result.reconnect_suggested:
            detail = "agent busy cancelling earlier runs; request not run"
        else:
            detail = f"close={result.close}"
        logger.warning(
            f"⚠️ AIMP: Interaction for message {message.message_id} ended {result.status}: "
            f"{detail} ({result.messages_received} messages received)"
        )
    
    async def _create_aimp_message(self, message: BridgeToAgentMessage) -> List:
        """Create AIMP message from bridge message."""
        # Create AIMP Intent
        aimp_msg = AIMPIntent()
        aimp_msg.URI = URIGenerator.generate_uri()
        aimp_msg.aIMPIntentType = message.aimp_intent_type
        aimp_msg.accountURI = f"urn:account_{message.inbox_id}"
        # username = sender identifier (phone or email) — used for manager detection
        aimp_msg.username = message.sender.phone or message.sender.email or message.sender.name or "chatwoot_user"
        aimp_msg.userID = message.sender.id
        aimp_msg.sessionID = f"session_{message.message_id}"
        aimp_msg.authSessionID = f"session_{message.message_id}"

        # Sender identity & channel context on AIMPIntent
        if message.sender.email:
            aimp_msg.senderIdentity = message.sender.email
        aimp_msg.channelURI = message.context.channel
        aimp_msg.threadURI = f"urn:conversation_{message.conversation_id}"
        if message.context.created_at:
            aimp_msg.timestamp = int(message.context.created_at.timestamp() * 1000)
        
        # Create user message content
        user_content = UserMessageContent()
        user_content.URI = URIGenerator.generate_uri()

        # Normalize Chatwoot channel string to short form expected by agent
        channel_map = {
            "Channel::Email": "email",
            "Channel::TwilioSms": "sms",
            "Channel::Sms": "sms",
            "Channel::WebWidget": "web",
            "Channel::Api": "api",
            "Channel::Whatsapp": "whatsapp",
            "Channel::Telegram": "telegram",
            "Channel::Line": "line",
            "Channel::Facebook": "facebook",
            "Channel::Twitter": "twitter",
        }
        raw_channel = message.context.channel or ""
        channel = channel_map.get(raw_channel, raw_channel.lower())

        # Pack context into messageContentJSON — only fields the agent needs.
        # SMS:   sender_phone, message_body, channel
        # Email: sender_email, message_body, subject (if present), channel
        content_json: dict = {
            "message_body": message.content,
            "channel": channel,
        }

        if channel == "sms":
            if message.sender.phone:
                content_json["sender_phone"] = message.sender.phone
        elif channel == "email":
            if message.sender.email:
                content_json["sender_email"] = message.sender.email
            if message.subject:
                content_json["subject"] = message.subject

        # assigned_personality — only for named agent inboxes (e.g. "CarlyAgent" → "carly")
        if "agent" in message.inbox_name.lower():
            personality = message.inbox_name.lower().replace("agent", "").strip()
            if personality:
                content_json["assigned_personality"] = personality
        user_content.messageContentJSON = json.dumps(content_json)
        
        logger.info(f"🔍 DEBUG: Sending message content to agent: '{message.content}'")
        logger.info(f"🔍 DEBUG: Session ID: {aimp_msg.sessionID}")
        logger.info(f"🔍 DEBUG: messageContentJSON: {user_content.messageContentJSON}")
        
        return [aimp_msg, user_content]
    
    def _parse_aimp_response(self, raw_response, message: BridgeToAgentMessage) -> Optional[AgentChatResponse]:
        """Parse AIMP response into AgentChatResponse format."""
        try:
            # Large agent replies (> ~768 KB) arrive as {"aimp_chunk": ...} objects.
            # Chat replies are far smaller, so the bridge doesn't reassemble them.
            if isinstance(raw_response, dict) and "aimp_chunk" in raw_response:
                logger.warning(f"AIMP: Dropping chunked agent reply part for message {message.message_id} (not supported)")
                return None

            if isinstance(raw_response, list):
                # Extract agent message content and intent flags from the response
                agent_text = None
                deliver_to_chatwoot = False
                for component in raw_response:
                    if isinstance(component, dict):
                        component_type = component.get('type', '')
                        if 'AIMPIntent' in component_type:
                            deliver_to_chatwoot = bool(component.get(
                                'http://vital.ai/ontology/vital-aimp#isDirectMessageResponse', False
                            ))
                        if 'AgentMessageContent' in component_type:
                            mcj = component.get('http://vital.ai/ontology/vital-aimp#hasMessageContentJSON', '')
                            if mcj:
                                try:
                                    mcj_data = json.loads(mcj) if isinstance(mcj, str) else mcj
                                    logger.info(f"📨 AIMP: messageContentJSON: {mcj}")
                                    # message_body may be at top level or nested inside
                                    # a response wrapper (e.g. nurture_lead_response)
                                    agent_text = mcj_data.get('message_body', '')
                                    if not agent_text:
                                        for val in mcj_data.values():
                                            if isinstance(val, dict) and 'message_body' in val:
                                                agent_text = val['message_body']
                                                break
                                except (json.JSONDecodeError, AttributeError) as e:
                                    logger.warning(f"📨 AIMP: Failed to parse hasMessageContentJSON: {e}")
                
                if agent_text:
                    from vital_chatwoot_bridge.core.models import ResponseMode, AgentResponseMetadata
                    logger.info(f"📨 AIMP: deliver_to_chatwoot={deliver_to_chatwoot} for message {message.message_id}")
                    return AgentChatResponse(
                        message_id=message.message_id,
                        inbox_id=message.inbox_id,
                        conversation_id=int(message.conversation_id),
                        content=agent_text,
                        response_type=ResponseMode.SYNC,
                        metadata=AgentResponseMetadata(
                            agent_id=f"aimp_agent_{message.inbox_id}",
                            source="aimp_agent",
                            processing_time_ms=0
                        ),
                        deliver_to_chatwoot=deliver_to_chatwoot,
                        success=True
                    )
            
            logger.warning(f"Could not extract agent text from response: {raw_response}")
            return None
            
        except Exception as e:
            logger.error(f"Error parsing AIMP response: {e}")
            return None
    
    async def test_agent_connectivity(self, agent_url: str, timeout: int = 10) -> bool:
        """Test if an agent is reachable and responsive."""
        try:
            logger.info(f"🧪 AIMP: Testing connectivity to {agent_url}")
            
            # Create a temporary handler and client
            handler = AimpMessageHandler()
            
            # Get JWT token if available
            jwt_token = None
            if self.jwt_manager:
                jwt_token = self.jwt_manager.get_keycloak_token()
            
            client = VitalAgentContainerClient(base_url=agent_url, handler=handler, jwt_token=jwt_token)
            
            # Test health endpoint
            health = await client.check_health()
            logger.info(f"✅ AIMP: Agent health check: {health}")
            return health
                
        except Exception as e:
            logger.error(f"❌ AIMP: Connectivity test failed: {e}")
            return False
