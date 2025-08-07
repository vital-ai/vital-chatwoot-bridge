"""
Mock AI agent implementation for testing the Vital Chatwoot Bridge.
"""

import asyncio
import json
import logging
import random
import time
from datetime import datetime, timezone
from typing import Dict, Any, Optional
from websockets.server import serve, WebSocketServerProtocol
from websockets.exceptions import ConnectionClosed
from fastapi import FastAPI, BackgroundTasks
from pydantic import BaseModel
import uvicorn
import threading

logger = logging.getLogger(__name__)

from vital_chatwoot_bridge.agents.models import (
    MockAgentBehavior,
    MockAgentConfig,
    MockAgentResponse,
    AgentChatRequest,
    AgentChatResponse,
    WebSocketMessage,
    WebSocketMessageType,
    AgentResponseMetadata
)
from vital_chatwoot_bridge.core.models import ResponseMode


class AsyncMessageRequest(BaseModel):
    """Request to trigger an async message from the agent."""
    inbox_id: str
    conversation_id: str
    content: str


class MockAIAgent:
    """Mock AI agent for testing bridge functionality."""
    
    def __init__(self, config: MockAgentConfig):
        self.config = config
        self.message_count = 0
        self.start_time = datetime.now(timezone.utc)
        
        # Default response templates
        self.default_templates = {
            "greeting": "Hello! I'm a mock AI agent. How can I help you today?",
            "help": "I can assist you with various tasks. Just ask me anything!",
            "goodbye": "Thank you for chatting with me. Have a great day!",
            "error": "I'm sorry, I encountered an error processing your request.",
            "default": "I received your message: '{content}'. This is a mock response.",
        }
        
        # Merge with custom templates
        self.response_templates = {**self.default_templates, **self.config.response_templates}
    
    async def process_message(self, request: AgentChatRequest) -> AgentChatResponse:
        """Process a chat message and return appropriate response."""
        start_time = time.time()
        self.message_count += 1
        
        try:
            # Generate response based on behavior
            if self.config.behavior == MockAgentBehavior.ECHO:
                response_content = await self._echo_response(request)
            elif self.config.behavior == MockAgentBehavior.TEST:
                response_content = await self._test_response(request)
            elif self.config.behavior == MockAgentBehavior.DELAY:
                response_content = await self._delay_response(request)
            elif self.config.behavior == MockAgentBehavior.ERROR:
                response_content = await self._error_response(request)
            elif self.config.behavior == MockAgentBehavior.RANDOM:
                response_content = await self._random_response(request)
            else:
                response_content = await self._echo_response(request)
            
            processing_time = int((time.time() - start_time) * 1000)
            
            # Create response metadata
            metadata = AgentResponseMetadata(
                agent_id=self.config.agent_id,
                processing_time_ms=processing_time,
                confidence=random.uniform(0.8, 0.99),
                ai_model_version="mock-v1.0"
            )
            
            return AgentChatResponse(
                message_id=request.message_id,
                inbox_id=request.inbox_id,
                conversation_id=request.conversation_id,
                content=response_content,
                response_type=request.response_mode,
                metadata=metadata,
                success=True
            )
            
        except Exception as e:
            processing_time = int((time.time() - start_time) * 1000)
            
            return AgentChatResponse(
                message_id=request.message_id,
                inbox_id=request.inbox_id,
                conversation_id=request.conversation_id,
                content="I apologize, but I encountered an error processing your request.",
                response_type=request.response_mode,
                success=False,
                error_message=str(e)
            )
    
    async def _echo_response(self, request: AgentChatRequest) -> str:
        """Generate echo response."""
        return f"Echo: {request.content}"
    
    async def _test_response(self, request: AgentChatRequest) -> str:
        """Generate test response based on keywords."""
        content_lower = request.content.lower()
        
        if any(word in content_lower for word in ["hello", "hi", "hey"]):
            return self.response_templates["greeting"]
        elif any(word in content_lower for word in ["help", "assist", "support"]):
            return self.response_templates["help"]
        elif any(word in content_lower for word in ["bye", "goodbye", "thanks"]):
            return self.response_templates["goodbye"]
        elif "error" in content_lower:
            return self.response_templates["error"]
        else:
            return self.response_templates["default"].format(content=request.content)
    
    async def _delay_response(self, request: AgentChatRequest) -> str:
        """Generate delayed response."""
        await asyncio.sleep(self.config.delay_seconds)
        return f"Delayed response after {self.config.delay_seconds}s: {request.content}"
    
    async def _error_response(self, request: AgentChatRequest) -> str:
        """Generate error response."""
        raise Exception(f"Mock agent error for testing (message: {request.message_id})")
    
    async def _random_response(self, request: AgentChatRequest) -> str:
        """Generate random response behavior."""
        if random.random() < self.config.error_rate:
            raise Exception("Random error occurred")
        
        behaviors = [MockAgentBehavior.ECHO, MockAgentBehavior.TEST, MockAgentBehavior.DELAY]
        chosen_behavior = random.choice(behaviors)
        
        if chosen_behavior == MockAgentBehavior.ECHO:
            return await self._echo_response(request)
        elif chosen_behavior == MockAgentBehavior.TEST:
            return await self._test_response(request)
        elif chosen_behavior == MockAgentBehavior.DELAY:
            # Use shorter delay for random mode
            await asyncio.sleep(random.uniform(1, 3))
            return f"Random delayed response: {request.content}"
    
    def get_stats(self) -> Dict[str, Any]:
        """Get agent statistics."""
        uptime = (datetime.utcnow() - self.start_time).total_seconds()
        return {
            "agent_id": self.config.agent_id,
            "behavior": self.config.behavior,
            "message_count": self.message_count,
            "uptime_seconds": uptime,
            "messages_per_minute": (self.message_count / uptime * 60) if uptime > 0 else 0
        }


class MockAgentWebSocketServer:
    """WebSocket server for mock AI agent."""
    
    def __init__(self, agent: MockAIAgent, host: str = "localhost", port: int = 8080):
        self.agent = agent
        self.host = host
        self.port = port
        self.server = None
        self.connected_clients = set()
        self.bridge_connections = set()  # Track bridge connections for async messaging
        
        # Create FastAPI app for REST endpoints
        self.rest_app = FastAPI(
            title=f"Mock Agent {agent.config.agent_id} API",
            description="REST API for triggering mock agent actions"
        )
        self._setup_rest_endpoints()
        self.rest_server = None
    
    def _setup_rest_endpoints(self):
        """Setup REST API endpoints for triggering agent actions."""
        
        @self.rest_app.post("/trigger-async-message")
        async def trigger_async_message(request: AsyncMessageRequest, background_tasks: BackgroundTasks):
            """Trigger the agent to send an async message to connected bridges."""
            success = await self.send_async_message(
                inbox_id=request.inbox_id,
                conversation_id=request.conversation_id,
                content=request.content
            )
            
            return {
                "success": success,
                "message": "Async message sent" if success else "No bridge connections available",
                "agent_id": self.agent.config.agent_id,
                "bridge_connections": len(self.bridge_connections)
            }
        
        @self.rest_app.get("/status")
        async def get_status():
            """Get agent status and connection info."""
            return {
                "agent_id": self.agent.config.agent_id,
                "behavior": self.agent.config.behavior.value,
                "websocket_connections": len(self.connected_clients),
                "bridge_connections": len(self.bridge_connections),
                "message_count": self.agent.message_count,
                "uptime_seconds": int((datetime.utcnow() - self.agent.start_time).total_seconds())
            }
    
    async def handle_client(self, websocket: WebSocketServerProtocol, path: str):
        """Handle WebSocket client connection."""
        self.connected_clients.add(websocket)
        # Assume connections from bridge service for async messaging
        self.bridge_connections.add(websocket)
        client_address = f"{websocket.remote_address[0]}:{websocket.remote_address[1]}"
        logger.info(f"🔌 MOCK AGENT: Client {client_address} connected to {self.agent.config.agent_id}")
        
        try:
            async for raw_message in websocket:
                try:
                    logger.info(f"🔍 MOCK AGENT: Received raw message: {raw_message[:200]}...")
                    # Parse incoming message
                    message_data = json.loads(raw_message)
                    logger.info(f"🔍 MOCK AGENT: Parsed message type: {message_data.get('type')}")
                    
                    if message_data.get("type") == "chat_message":
                        logger.info(f"🔍 MOCK AGENT: Processing chat message with data keys: {list(message_data.get('data', {}).keys())}")
                        # Process chat request
                        try:
                            request = AgentChatRequest(**message_data["data"])
                            logger.info(f"🔍 MOCK AGENT: Created AgentChatRequest successfully")
                            response = await self.agent.process_message(request)
                            logger.info(f"🔍 MOCK AGENT: Generated response: {response.content[:100]}...")
                            
                            # Send response
                            response_message = WebSocketMessage(
                                type=WebSocketMessageType.CHAT_MESSAGE,
                                data=response.dict()
                            )
                            await websocket.send(response_message.json())
                            logger.info(f"🔍 MOCK AGENT: Sent response successfully")
                        except Exception as e:
                            logger.error(f"❌ MOCK AGENT: Error processing chat message: {e}")
                            logger.error(f"❌ MOCK AGENT: Message data: {message_data}")
                    
                    elif message_data.get("type") == "ping":
                        # Respond to ping
                        pong_message = WebSocketMessage(
                            type=WebSocketMessageType.PONG,
                            data={"agent_id": self.agent.config.agent_id}
                        )
                        await websocket.send(pong_message.json())
                    
                    elif message_data.get("type") == "status":
                        # Send status information
                        status_message = WebSocketMessage(
                            type=WebSocketMessageType.STATUS,
                            data=self.agent.get_stats()
                        )
                        await websocket.send(status_message.json())
                
                except json.JSONDecodeError as e:
                    # Send error response for invalid JSON
                    error_message = WebSocketMessage(
                        type=WebSocketMessageType.ERROR,
                        data={
                            "error": "Invalid JSON",
                            "message": str(e)
                        }
                    )
                    await websocket.send(error_message.json())
                
                except Exception as e:
                    # Send error response for processing errors
                    error_message = WebSocketMessage(
                        type=WebSocketMessageType.ERROR,
                        data={
                            "error": "Processing error",
                            "message": str(e)
                        }
                    )
                    await websocket.send(error_message.json())
        
        except ConnectionClosed:
            logger.info(f"🔌 MOCK AGENT: Client {client_address} disconnected from {self.agent.config.agent_id}")
        
        finally:
            self.connected_clients.discard(websocket)
            self.bridge_connections.discard(websocket)
    
    async def start_server(self):
        """Start both WebSocket and REST servers."""
        logger.info(f"🚀 MOCK AGENT: Starting {self.agent.config.agent_id} on {self.host}:{self.port}")
        
        # Start WebSocket server
        try:
            self.server = await serve(
                self.handle_client,
                self.host,
                self.port
            )
            logger.info(f"🌐 MOCK AGENT: WebSocket server started on ws://{self.host}:{self.port} for {self.agent.config.agent_id}")
            
            # Give server a moment to fully bind
            await asyncio.sleep(0.5)
            logger.info(f"✅ MOCK AGENT: WebSocket server is ready to accept connections")
        except Exception as e:
            logger.error(f"❌ MOCK AGENT: Failed to start WebSocket server: {e}")
            raise
        
        # Start REST server on port + 1000 (e.g., WS on 8085, REST on 9085)
        rest_port = self.port + 1000
        rest_config = uvicorn.Config(
            self.rest_app,
            host=self.host,
            port=rest_port,
            log_level="warning"  # Reduce log noise
        )
        self.rest_server = uvicorn.Server(rest_config)
        
        # Start REST server in background thread
        def start_rest_server():
            asyncio.run(self.rest_server.serve())
        
        rest_thread = threading.Thread(target=start_rest_server, daemon=True)
        rest_thread.start()
        
        logger.info(f"🌐 MOCK AGENT: REST API started on http://{self.host}:{rest_port} for {self.agent.config.agent_id}")
        logger.info(f"📡 MOCK AGENT: Trigger async message: POST http://{self.host}:{rest_port}/trigger-async-message")
        logger.info(f"📊 MOCK AGENT: Agent status: GET http://{self.host}:{rest_port}/status")
    
    async def stop_server(self):
        """Stop the WebSocket server."""
        if self.server:
            self.server.close()
            await self.server.wait_closed()
            logger.info(f"🛑 MOCK AGENT: Server stopped for {self.agent.config.agent_id}")
    
    def get_connection_count(self) -> int:
        """Get number of connected clients."""
        return len(self.connected_clients)
    
    async def send_async_message(self, inbox_id: str, conversation_id: str, content: str):
        """Send an async message to all connected bridge clients."""
        if not self.bridge_connections:
            logger.warning(f"⚠️ MOCK AGENT: No bridge connections available for async message in {self.agent.config.agent_id}")
            return False
        
        # Create async message in the format expected by the bridge
        async_message = {
            "type": "chat_message",
            "data": {
                "message_id": f"async_{int(time.time() * 1000)}",
                "inbox_id": inbox_id,
                "conversation_id": conversation_id,
                "content": content,
                "response_type": "async",
                "success": True,
                "metadata": {
                    "agent_id": self.agent.config.agent_id,
                    "processing_time_ms": 0,
                    "confidence": 0.95,
                    "ai_model_version": "mock-v1.0"
                }
            }
        }
        
        message_json = json.dumps(async_message)
        sent_count = 0
        
        # Send to all connected bridge clients
        for websocket in list(self.bridge_connections):
            try:
                await websocket.send(message_json)
                sent_count += 1
                logger.info(f"📤 MOCK AGENT: Sent async message to bridge from {self.agent.config.agent_id}")
            except Exception as e:
                logger.error(f"❌ MOCK AGENT: Failed to send async message from {self.agent.config.agent_id}: {e}")
                self.bridge_connections.discard(websocket)
        
        return sent_count > 0


async def create_mock_agent_server(
    agent_id: str = "mock-agent-1",
    behavior: MockAgentBehavior = MockAgentBehavior.ECHO,
    host: str = "localhost",
    port: int = 8080,
    **kwargs
) -> MockAgentWebSocketServer:
    """Create and start a mock agent server."""
    config = MockAgentConfig(
        agent_id=agent_id,
        behavior=behavior,
        **kwargs
    )
    
    agent = MockAIAgent(config)
    server = MockAgentWebSocketServer(agent, host, port)
    await server.start_server()
    
    return server


# Example usage and testing
if __name__ == "__main__":
    import sys
    
    async def main():
        # Parse command line arguments: host port behavior
        if len(sys.argv) >= 4:
            host = sys.argv[1]
            port = int(sys.argv[2])
            behavior_str = sys.argv[3]
            
            # Map behavior string to enum
            behavior_map = {
                "echo": MockAgentBehavior.ECHO,
                "test": MockAgentBehavior.TEST,
                "delay": MockAgentBehavior.DELAY,
                "error": MockAgentBehavior.ERROR,
                "random": MockAgentBehavior.RANDOM
            }
            
            behavior = behavior_map.get(behavior_str, MockAgentBehavior.ECHO)
            agent_id = f"{behavior_str}-agent"
            
            logger.info(f"🚀 MOCK AGENT: Starting {agent_id} on {host}:{port} with behavior {behavior_str}")
            
            # Create single agent with specified parameters
            server = await create_mock_agent_server(
                agent_id=agent_id,
                behavior=behavior,
                host=host,
                port=port
            )
            
            logger.info(f"✅ MOCK AGENT: {agent_id} started successfully. Press Ctrl+C to stop...")
            
            try:
                # Keep server running - wait for the WebSocket server to serve connections
                await server.server.wait_closed()
            except KeyboardInterrupt:
                logger.info(f"🛑 MOCK AGENT: Shutting down {agent_id}...")
                await server.stop_server()
        else:
            # Default behavior - create multiple agents
            agents = [
                ("echo-agent", MockAgentBehavior.ECHO, 8080),
                ("test-agent", MockAgentBehavior.TEST, 8081),
                ("delay-agent", MockAgentBehavior.DELAY, 8082),
            ]
            
            servers = []
            for agent_id, behavior, port in agents:
                server = await create_mock_agent_server(
                    agent_id=agent_id,
                    behavior=behavior,
                    port=port
                )
                servers.append(server)
            
            logger.info(f"✅ MOCK AGENT: All mock agents started successfully. Press Ctrl+C to stop...")
            
            try:
                # Keep servers running
                await asyncio.Future()  # Run forever
            except KeyboardInterrupt:
                logger.info(f"🛑 MOCK AGENT: Shutting down all mock agents...")
                for server in servers:
                    await server.stop_server()
    
    asyncio.run(main())
