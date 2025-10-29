"""
AIMP message client for communicating with AI agents using vital-agent-container-client.
Handles per-message connections and AIMP message protocol.
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
from vital_agent_container_client.aimp_message_handler_inf import AIMPMessageHandlerInf
from vital_agent_container_client.vital_agent_container_client import VitalAgentContainerClient

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
            
            # Open WebSocket connection
            logger.info(f"🔗 AIMP: Opening WebSocket connection")
            await client.open_websocket()
            
            # Send AIMP message
            logger.info(f"📤 AIMP: Sending AIMP message")
            logger.info(f"🔍 DEBUG: Full AIMP message being sent: {message_list}")
            await client.send_message(message_list)
            
            # Wait for response with timeout
            logger.info(f"👂 AIMP: Waiting for responses (timeout: {timeout}s)")
            await client.wait_for_close_or_timeout(timeout)
            
            # Get responses from handler
            raw_responses = handler.get_responses()
            
            # Convert AIMP responses to AgentChatResponse format
            responses = []
            for raw_response in raw_responses:
                agent_response = self._parse_aimp_response(raw_response, message)
                if agent_response:
                    responses.append(agent_response)
            
            return responses
            
        except Exception as e:
            logger.error(f"❌ AIMP: Error in AIMP communication: {e}")
            return []
            
        finally:
            # Clean up WebSocket connection
            try:
                await client.close_websocket()
                logger.info(f"✅ AIMP: WebSocket connection closed")
            except Exception as e:
                logger.warning(f"⚠️ AIMP: Error closing WebSocket: {e}")
    
    async def _create_aimp_message(self, message: BridgeToAgentMessage) -> List:
        """Create AIMP message from bridge message."""
        # Create AIMP Intent
        aimp_msg = AIMPIntent()
        aimp_msg.URI = URIGenerator.generate_uri()
        aimp_msg.aIMPIntentType = "http://vital.ai/ontology/vital-aimp#AIMPIntentType_CHAT"
        aimp_msg.accountURI = f"urn:account_{message.inbox_id}"
        aimp_msg.username = message.sender.name or "chatwoot_user"
        aimp_msg.userID = message.sender.id
        aimp_msg.sessionID = f"session_{message.message_id}"
        aimp_msg.authSessionID = f"session_{message.message_id}"
        
        # Create user message content
        user_content = UserMessageContent()
        user_content.URI = URIGenerator.generate_uri()
        user_content.text = message.content
        
        logger.info(f"🔍 DEBUG: Sending message content to agent: '{message.content}'")
        logger.info(f"🔍 DEBUG: Session ID: {aimp_msg.sessionID}")
        
        return [aimp_msg, user_content]
    
    def _parse_aimp_response(self, raw_response, message: BridgeToAgentMessage) -> Optional[AgentChatResponse]:
        """Parse AIMP response into AgentChatResponse format."""
        try:
            if isinstance(raw_response, list):
                # Extract agent message content from the response
                agent_text = None
                for component in raw_response:
                    if isinstance(component, dict):
                        component_type = component.get('type', '')
                        if 'AgentMessageContent' in component_type:
                            agent_text = component.get('http://vital.ai/ontology/vital-aimp#hasText', '')
                            break
                
                if agent_text:
                    from vital_chatwoot_bridge.core.models import ResponseMode, AgentResponseMetadata
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
