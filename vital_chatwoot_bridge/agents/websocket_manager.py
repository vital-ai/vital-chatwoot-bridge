"""
WebSocket manager for communicating with AI agents.
"""

import asyncio
import json
import logging
import time
from typing import Dict, Optional, Set
from datetime import datetime, timedelta

import websockets
from websockets.exceptions import ConnectionClosed, InvalidURI
from pydantic import ValidationError

from vital_chatwoot_bridge.core.config import get_settings
from vital_chatwoot_bridge.core.models import BridgeToAgentMessage, AgentConnectionStatus
from vital_chatwoot_bridge.agents.models import (
    AgentChatResponse, AgentStatus, AgentConnectionInfo
)

logger = logging.getLogger(__name__)


class AgentConnection:
    """Represents a connection to an AI agent."""
    
    def __init__(self, agent_id: str, websocket_url: str):
        self.agent_id = agent_id
        self.websocket_url = websocket_url
        self.websocket: Optional[websockets.WebSocketServerProtocol] = None
        self.status = AgentStatus.DISCONNECTED
        self.last_ping = None
        self.last_pong = None
        self.connection_attempts = 0
        self.last_connection_attempt = None
        self.pending_messages: Dict[str, asyncio.Future] = {}
        self.lock = asyncio.Lock()
    
    @property
    def is_connected(self) -> bool:
        """Check if the connection is active."""
        return self.websocket is not None and not self.websocket.closed
    
    @property
    def connection_info(self) -> AgentConnectionInfo:
        """Get connection information."""
        return AgentConnectionInfo(
            agent_id=self.agent_id,
            websocket_url=self.websocket_url,
            status=self.status,
            last_ping=self.last_ping,
            last_pong=self.last_pong,
            connection_attempts=self.connection_attempts,
            last_connection_attempt=self.last_connection_attempt,
            pending_messages=len(self.pending_messages)
        )


class WebSocketManager:
    """Manages WebSocket connections to AI agents."""
    
    def __init__(self):
        self.settings = get_settings()
        self.connections: Dict[str, AgentConnection] = {}
        self.running = False
        self.health_check_task: Optional[asyncio.Task] = None
        self.reconnect_task: Optional[asyncio.Task] = None
    
    async def start(self):
        """Start the WebSocket manager."""
        if self.running:
            return
        
        self.running = True
        logger.info("Starting WebSocket manager")
        
        # Initialize connections for all configured agents
        connection_tasks = []
        for mapping in self.settings.inbox_agent_mappings:
            agent_config = mapping.agent_config
            await self._add_agent_connection(agent_config.agent_id, agent_config.websocket_url)
            
            # Attempt initial connection (non-blocking, failures will be retried by reconnect loop)
            connection = self.connections[agent_config.agent_id]
            connection_task = asyncio.create_task(self._connect_agent_safely(connection))
            connection_tasks.append(connection_task)
        
        # Start background tasks
        self.health_check_task = asyncio.create_task(self._health_check_loop())
        self.reconnect_task = asyncio.create_task(self._reconnect_loop())
        
        # Wait for initial connection attempts (but don't block startup on failures)
        if connection_tasks:
            logger.info(f"Attempting initial connections to {len(connection_tasks)} agents...")
            await asyncio.gather(*connection_tasks, return_exceptions=True)
        
        successful_connections = sum(1 for conn in self.connections.values() if conn.status == AgentStatus.CONNECTED)
        logger.info(f"WebSocket manager started with {successful_connections}/{len(self.connections)} agent connections established")
    
    async def stop(self):
        """Stop the WebSocket manager."""
        if not self.running:
            return
        
        self.running = False
        logger.info("Stopping WebSocket manager")
        
        # Cancel background tasks
        if self.health_check_task:
            self.health_check_task.cancel()
            try:
                await self.health_check_task
            except asyncio.CancelledError:
                pass
        
        if self.reconnect_task:
            self.reconnect_task.cancel()
            try:
                await self.reconnect_task
            except asyncio.CancelledError:
                pass
        
        # Close all connections
        for connection in self.connections.values():
            await self._disconnect_agent(connection)
        
        self.connections.clear()
        logger.info("WebSocket manager stopped")
    
    async def send_message_sync(
        self,
        websocket_url: str,
        message: BridgeToAgentMessage,
        timeout: int = 30
    ) -> Optional[AgentChatResponse]:
        """
        Send a message to an agent and wait for a synchronous response.
        
        Args:
            websocket_url: WebSocket URL of the agent
            message: Message to send
            timeout: Timeout in seconds
            
        Returns:
            Agent response or None if timeout/error
        """
        connection = await self._get_or_create_connection(websocket_url)
        if not connection:
            logger.error(f"Failed to get connection for {websocket_url}")
            return None
        
        try:
            # Ensure connection is active
            if not await self._ensure_connected(connection):
                logger.error(f"Failed to establish connection to {websocket_url}")
                return None
            
            # Create future for response
            response_future = asyncio.Future()
            connection.pending_messages[message.message_id] = response_future
            
            # Send message in WebSocket format expected by mock agent
            # Convert structured objects to dictionaries for agent compatibility
            sender_data = message.sender.model_dump() if hasattr(message.sender, 'model_dump') else message.sender
            context_data = message.context.model_dump() if hasattr(message.context, 'model_dump') else message.context
            
            # Handle datetime serialization in context
            if isinstance(context_data, dict) and 'created_at' in context_data:
                if hasattr(context_data['created_at'], 'isoformat'):
                    context_data['created_at'] = context_data['created_at'].isoformat()
            
            message_data = {
                "message_id": message.message_id,
                "inbox_id": message.inbox_id,
                "conversation_id": message.conversation_id,
                "content": message.content,
                "sender": sender_data,
                "context": context_data,
                "response_mode": message.response_mode.value if hasattr(message.response_mode, 'value') else str(message.response_mode)
            }
            
            websocket_message = {
                "type": "chat_message",
                "data": message_data
            }
            message_json = json.dumps(websocket_message)
            
            logger.info(f"📤 WEBSOCKET: Sending message to agent {connection.agent_id}: {message.message_id}")
            logger.info(f"📤 WEBSOCKET: Message content: {message.content[:100]}...")
            
            await connection.websocket.send(message_json)
            
            logger.info(f"✅ WEBSOCKET: Successfully sent message to agent {connection.agent_id}")
            
            logger.debug(f"Sent sync message {message.message_id} to {connection.agent_id}")
            
            # Wait for response
            try:
                response = await asyncio.wait_for(response_future, timeout=timeout)
                return response
            except asyncio.TimeoutError:
                logger.warning(f"Timeout waiting for response from {connection.agent_id}")
                return None
            finally:
                # Clean up pending message
                connection.pending_messages.pop(message.message_id, None)
        
        except Exception as e:
            logger.error(f"Error sending sync message to {connection.agent_id}: {e}")
            connection.pending_messages.pop(message.message_id, None)
            return None
    
    async def send_message_async(
        self,
        websocket_url: str,
        message: BridgeToAgentMessage
    ) -> Optional[AgentChatResponse]:
        """
        Send a message to an agent asynchronously (fire and forget).
        
        Args:
            websocket_url: WebSocket URL of the agent
            message: Message to send
            
        Returns:
            Agent response when available, or None if error
        """
        connection = await self._get_or_create_connection(websocket_url)
        if not connection:
            logger.error(f"Failed to get connection for {websocket_url}")
            return None
        
        try:
            # Ensure connection is active
            if not await self._ensure_connected(connection):
                logger.error(f"Failed to establish connection to {websocket_url}")
                return None
            
            # Send message
            message_json = message.json()
            await connection.websocket.send(message_json)
            
            logger.debug(f"Sent async message {message.message_id} to {connection.agent_id}")
            
            # For async messages, we don't wait for a response
            # The response will be handled by the message listener
            return None
        
        except Exception as e:
            logger.error(f"Error sending async message to {connection.agent_id}: {e}")
            return None
    
    async def get_agent_status(self, agent_id: str) -> Optional[AgentConnectionInfo]:
        """Get status information for an agent."""
        connection = self.connections.get(agent_id)
        if connection:
            return connection.connection_info
        return None
    
    async def get_all_agent_status(self) -> Dict[str, AgentConnectionInfo]:
        """Get status information for all agents."""
        return {
            agent_id: connection.connection_info
            for agent_id, connection in self.connections.items()
        }
    
    async def _add_agent_connection(self, agent_id: str, websocket_url: str):
        """Add a new agent connection."""
        if agent_id in self.connections:
            logger.warning(f"Agent {agent_id} already exists, updating URL")
        
        connection = AgentConnection(agent_id, websocket_url)
        self.connections[agent_id] = connection
        
        logger.info(f"Added agent connection: {agent_id} -> {websocket_url}")
    
    async def _get_or_create_connection(self, websocket_url: str) -> Optional[AgentConnection]:
        """Get existing connection or create new one for the WebSocket URL."""
        # Find existing connection by URL
        for connection in self.connections.values():
            if connection.websocket_url == websocket_url:
                return connection
        
        # Create new connection with generated agent ID
        agent_id = f"agent_{len(self.connections) + 1}"
        await self._add_agent_connection(agent_id, websocket_url)
        return self.connections.get(agent_id)
    
    async def _ensure_connected(self, connection: AgentConnection) -> bool:
        """Ensure the connection is active, reconnect if necessary."""
        async with connection.lock:
            if connection.is_connected:
                return True
            
            return await self._connect_agent(connection)
    
    async def _connect_agent_safely(self, connection: AgentConnection) -> bool:
        """Safely attempt to connect to an agent without raising exceptions."""
        try:
            return await self._connect_agent(connection)
        except Exception as e:
            logger.error(f"Safe connection attempt failed for {connection.agent_id}: {e}")
            connection.status = AgentStatus.ERROR
            return False
    
    async def _connect_agent(self, connection: AgentConnection) -> bool:
        """Connect to an agent with retry logic."""
        max_retries = 5
        retry_delay = 2  # seconds
        
        for attempt in range(max_retries):
            try:
                connection.last_connection_attempt = datetime.utcnow()
                connection.connection_attempts += 1
                connection.status = AgentStatus.CONNECTING
                
                logger.info(f"🔌 WEBSOCKET: Connecting to agent {connection.agent_id} at {connection.websocket_url} (attempt {attempt + 1}/{max_retries})")
                
                # Connect to WebSocket
                connection.websocket = await websockets.connect(
                    connection.websocket_url,
                    timeout=self.settings.websocket_connect_timeout,
                    ping_interval=self.settings.websocket_ping_interval,
                    ping_timeout=self.settings.websocket_ping_timeout
                )
                
                connection.status = AgentStatus.CONNECTED
                connection.last_ping = datetime.utcnow()
                
                logger.info(f"✅ WEBSOCKET: Successfully connected to agent {connection.agent_id} on attempt {attempt + 1}")
                
                # Start message listener for this connection
                asyncio.create_task(self._message_listener(connection))
                
                logger.info(f"🎧 WEBSOCKET: Started message listener for agent {connection.agent_id}")
                return True
            
            except (ConnectionClosed, InvalidURI, OSError, asyncio.TimeoutError) as e:
                connection.status = AgentStatus.ERROR
                connection.websocket = None
                
                if attempt < max_retries - 1:
                    logger.warning(f"⚠️ WEBSOCKET: Connection attempt {attempt + 1} failed for agent {connection.agent_id}: {e}. Retrying in {retry_delay}s...")
                    await asyncio.sleep(retry_delay)
                    retry_delay *= 1.5  # Exponential backoff
                else:
                    logger.error(f"❌ WEBSOCKET: Failed to connect to agent {connection.agent_id} after {max_retries} attempts: {e}")
                    return False
            
            except Exception as e:
                connection.status = AgentStatus.ERROR
                connection.websocket = None
                logger.error(f"❌ WEBSOCKET: Unexpected error connecting to agent {connection.agent_id}: {e}")
                return False
        
        return False
    
    async def _disconnect_agent(self, connection: AgentConnection):
        """Disconnect from an agent."""
        logger.info(f"🔌 WEBSOCKET: Disconnecting from agent {connection.agent_id}")
        if connection.websocket:
            try:
                await connection.websocket.close()
                logger.info(f"✅ WEBSOCKET: Successfully disconnected from agent {connection.agent_id}")
            except Exception as e:
                logger.warning(f"⚠️ WEBSOCKET: Error closing connection to {connection.agent_id}: {e}")
            finally:
                connection.websocket = None
                connection.status = AgentStatus.DISCONNECTED
        
        # Cancel any pending messages
        for future in connection.pending_messages.values():
            if not future.done():
                future.cancel()
        connection.pending_messages.clear()
    
    async def _message_listener(self, connection: AgentConnection):
        """Listen for messages from an agent."""
        logger.info(f"🔥 LISTENER DEBUG: Starting message listener for {connection.agent_id}")
        try:
            logger.info(f"🔥 LISTENER DEBUG: Entering message loop for {connection.agent_id}")
            async for message in connection.websocket:
                logger.info(f"🔥 LISTENER DEBUG: Message loop iteration for {connection.agent_id}")
                try:
                    logger.info(f"📥 WEBSOCKET: Received raw message from agent {connection.agent_id}")
                    logger.info(f"📥 WEBSOCKET: Raw message content: {message}")
                    
                    # Parse WebSocket message format
                    websocket_message = json.loads(message)
                    logger.info(f"📥 WEBSOCKET: Parsed message type: {websocket_message.get('type', 'unknown')}")
                    
                    # Extract data from WebSocket message format
                    if websocket_message.get("type") == "chat_message" and "data" in websocket_message:
                        agent_message = AgentChatResponse(**websocket_message["data"])
                    else:
                        logger.warning(f"Unexpected message format from {connection.agent_id}: {websocket_message}")
                        continue
                    
                    logger.debug(f"Received message from {connection.agent_id}: {agent_message.message_id}")
                    
                    # Handle response to pending message
                    if agent_message.message_id in connection.pending_messages:
                        logger.debug(f"Handling pending message response: {agent_message.message_id}")
                        future = connection.pending_messages[agent_message.message_id]
                        if not future.done():
                            future.set_result(agent_message)
                    else:
                        # Handle unsolicited message (async response)
                        logger.info(f"Handling unsolicited message: {agent_message.message_id} from {connection.agent_id}")
                        logger.info(f"Message content: {agent_message.content}")
                        await self._handle_unsolicited_message(connection, agent_message)
                
                except (json.JSONDecodeError, ValidationError) as e:
                    logger.error(f"Invalid message from {connection.agent_id}: {e}")
                except Exception as e:
                    logger.error(f"Error processing message from {connection.agent_id}: {e}")
        
        except ConnectionClosed:
            logger.info(f"Connection to {connection.agent_id} closed")
        except Exception as e:
            logger.error(f"Error in message listener for {connection.agent_id}: {e}")
        finally:
            # Update connection status to disconnected
            if hasattr(connection, 'status') and connection.status:
                connection.status.connected = False
            connection.websocket = None
    
    async def _handle_unsolicited_message(self, connection: AgentConnection, message: AgentChatResponse):
        """Handle unsolicited messages from agents (async responses)."""
        logger.info(f"🔥 ASYNC DEBUG: Received unsolicited message from {connection.agent_id}: {message.message_id}")
        logger.info(f"🔥 ASYNC DEBUG: Message content: {message.content}")
        logger.info(f"🔥 ASYNC DEBUG: Inbox ID: {message.inbox_id}, Conversation ID: {message.conversation_id}")
        
        try:
            # Import here to avoid circular imports
            from vital_chatwoot_bridge.chatwoot.api_client import ChatwootAPIClient
            from vital_chatwoot_bridge.chatwoot.models import ChatwootAPIMessageRequest
            
            # Create Chatwoot API client (gets settings internally)
            api_client = ChatwootAPIClient()
            
            # Get settings for account_id
            settings = get_settings()
        
            # Post the async response to Chatwoot
            logger.info(f"🔥 ASYNC DEBUG: About to post to Chatwoot API: conversation_id={message.conversation_id}")
            logger.info(f"🔥 ASYNC DEBUG: Message content: {message.content}")
            
            response = await api_client.send_message(
                account_id=settings.chatwoot_account_id,
                conversation_id=message.conversation_id,
                content=message.content,
                message_type="outgoing",  # Agent response is outgoing from Chatwoot's perspective
                private=False
            )
            
            if response:
                logger.info(f"🔥 ASYNC DEBUG: ✅ Successfully posted async message to Chatwoot: {response.id}")
            else:
                logger.error(f"🔥 ASYNC DEBUG: ❌ Failed to post async message to Chatwoot - no response")
                
        except Exception as e:
            logger.error(f"Error handling unsolicited message from {connection.agent_id}: {e}")
            logger.error(f"Message content: {message.content}")
    
    async def _health_check_loop(self):
        """Background task to perform health checks on connections."""
        while self.running:
            try:
                for connection in self.connections.values():
                    if connection.is_connected:
                        # Send ping
                        try:
                            pong_waiter = await connection.websocket.ping()
                            await asyncio.wait_for(pong_waiter, timeout=5.0)
                            connection.last_pong = datetime.utcnow()
                            connection.status = AgentStatus.CONNECTED
                        except Exception as e:
                            logger.warning(f"Health check failed for {connection.agent_id}: {e}")
                            connection.status = AgentStatus.ERROR
                            await self._disconnect_agent(connection)
                
                await asyncio.sleep(self.settings.websocket_ping_interval)
            
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in health check loop: {e}")
                await asyncio.sleep(5)
    
    async def _reconnect_loop(self):
        """Background task to reconnect to failed connections."""
        while self.running:
            try:
                for connection in self.connections.values():
                    if (connection.status in [AgentStatus.DISCONNECTED, AgentStatus.ERROR] and
                        connection.last_connection_attempt and
                        datetime.utcnow() - connection.last_connection_attempt > timedelta(seconds=30)):
                        
                        logger.info(f"Attempting to reconnect to {connection.agent_id}")
                        await self._connect_agent(connection)
                
                await asyncio.sleep(10)  # Check every 10 seconds
            
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in reconnect loop: {e}")
                await asyncio.sleep(5)
