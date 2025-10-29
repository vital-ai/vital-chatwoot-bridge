# Vital Chatwoot Bridge - Revised Implementation Plan

## Overview
The Vital Chatwoot Bridge is a FastAPI service that acts as a bridge between Chatwoot (customer support platform) and AI agents. This revised plan switches from persistent WebSocket connections to per-message WebSocket connections, enabling integration with real AI agents running as separate services.

## Key Changes from Original Plan

### 1. WebSocket Connection Strategy
- **Original**: Persistent WebSocket connections maintained to all agents
- **Revised**: Per-message WebSocket connections (connect, send, receive, disconnect)
- **Benefits**: 
  - No connection state management
  - Better resource utilization
  - Easier integration with external agent services
  - Simplified error handling

### 2. Agent Architecture
- **Original**: Mock agents started via docker-compose for testing
- **Revised**: Support for both mock agents (testing) and real agents (production)
- **Real Agents**: Run as separate services, not managed by bridge docker-compose
- **Mock Agents**: Still available for testing via dedicated docker-compose

### 3. Docker Compose Structure
- **Original**: Single docker-compose.yml with mock agents
- **Revised**: 
  - `docker-compose.yml` - Production bridge only
  - `docker-compose.test.yml` - Bridge + mock agents for testing

## Architecture

### Core Components
1. **Webhook Handler** - Receives Chatwoot webhook events
2. **Per-Message WebSocket Client** - Creates connections per message
3. **Message Transformer** - Converts between Chatwoot and AI agent message formats
4. **Chatwoot API Client** - Posts responses back to Chatwoot
5. **Configuration Manager** - Maps Chatwoot inboxes to AI agents

### Message Flow Patterns

#### Synchronous Flow (Immediate Response)
```
Chatwoot → Webhook → WebSocket Connect → AI Agent → Response → WebSocket Close → Webhook Response → Chatwoot
```
- WebSocket connection created for each message
- Agent can send multiple responses during connection
- Connection closed after final response or timeout
- Primary response included in webhook HTTP response

#### Asynchronous Flow (Multiple Responses)
```
Chatwoot → Webhook → WebSocket Connect → AI Agent → Multiple Responses → WebSocket Close → Chatwoot API
```
- Agent sends multiple messages during single connection
- Each response posted to Chatwoot API as received
- Connection maintained until agent signals completion or timeout

#### Agent-Initiated Messages (Proactive)
```
External Trigger → Bridge API → Chatwoot API → Inbox
```
- Bridge exposes API for external systems to send messages
- Messages posted directly to Chatwoot conversations
- No WebSocket connection to agents needed

## Per-Message WebSocket Implementation

### WebSocket Client Manager
```python
class PerMessageWebSocketClient:
    """Handles per-message WebSocket connections to AI agents."""
    
    async def send_message_with_responses(
        self,
        websocket_url: str,
        message: BridgeToAgentMessage,
        timeout: int = 30
    ) -> List[AgentChatResponse]:
        """
        Connect, send message, collect all responses, disconnect.
        
        Returns:
            List of responses from agent (can be multiple)
        """
        
    async def _connect_and_communicate(self, websocket_url: str, message: dict, timeout: int):
        """Handle single connection lifecycle."""
        websocket = None
        responses = []
        
        try:
            # Connect
            websocket = await websockets.connect(websocket_url, timeout=10)
            
            # Send message
            await websocket.send(json.dumps(message))
            
            # Collect responses until completion or timeout
            async with asyncio.timeout(timeout):
                async for response_msg in websocket:
                    response = self._parse_response(response_msg)
                    responses.append(response)
                    
                    # Check if agent signals completion
                    if response.is_final:
                        break
                        
        finally:
            # Always close connection
            if websocket:
                await websocket.close()
                
        return responses
```

### Response Handling Strategy
```python
class ResponseHandler:
    """Handles multiple responses from agents."""
    
    async def process_agent_responses(
        self,
        responses: List[AgentChatResponse],
        conversation_id: str,
        account_id: str
    ) -> str:
        """
        Process multiple responses from agent.
        
        Returns:
            Primary response content for webhook
        """
        if not responses:
            return None
            
        primary_response = responses[0].content
        
        # Post all responses to Chatwoot
        for response in responses:
            await self.chatwoot_client.send_message(
                account_id=account_id,
                conversation_id=conversation_id,
                content=response.content,
                message_type="outgoing"
            )
            
        return primary_response
```

## Agent Integration Models

### Mock Agents (Testing)
- Started via `docker-compose.test.yml`
- Multiple mock behaviors (echo, test, delay, error)
- WebSocket servers listening on configured ports
- Used for development and CI/CD testing

### Real Agents (Production)
- External services running independently
- Bridge connects to agent WebSocket endpoints
- Agents can be in different networks/environments
- Configuration via environment variables or AWS Secrets Manager

### Agent Response Protocol
```json
{
  "message_id": "webhook_msg_123",
  "conversation_id": "456",
  "content": "Agent response content",
  "response_type": "partial" | "final",
  "metadata": {
    "agent_id": "agent1",
    "processing_time_ms": 1500,
    "confidence": 0.95,
    "is_final": false
  }
}
```

## Configuration Structure

### Enhanced Settings for Per-Message Connections
```python
class AgentConfig(BaseModel):
    agent_id: str
    websocket_url: str
    timeout_seconds: int = 30
    max_responses: int = 5  # Limit responses per message
    connection_timeout: int = 10  # Connection establishment timeout
    
class Settings(BaseSettings):
    # Chatwoot API Configuration
    chatwoot_base_url: str
    chatwoot_api_access_token: str
    chatwoot_account_id: int
    
    # AI Agent Mappings
    inbox_agent_mappings: List[InboxMapping] = []
    
    # WebSocket Configuration
    websocket_connect_timeout: int = 10
    websocket_message_timeout: int = 30
    max_responses_per_message: int = 5
    
    # Response Configuration
    enable_multiple_responses: bool = True
    primary_response_only: bool = False  # If true, only return first response
```

## Implementation Changes Required

### Phase 1: WebSocket Manager Refactoring
1. **Replace WebSocketManager**
   - Remove persistent connection management
   - Remove health check and reconnect loops
   - Implement per-message connection logic

2. **Update WebhookHandler**
   - Modify to use new per-message client
   - Handle multiple responses from agents
   - Update response posting logic

### Phase 2: Docker Compose Restructuring
1. **Rename Current Files**
   - `docker-compose.yml` → `docker-compose.test.yml`
   - `docker-compose.mock.yml` → `docker-compose.test-extended.yml`

2. **Create Production Compose**
   - New `docker-compose.yml` with bridge service only
   - Remove mock agent services
   - Optimized for production deployment

### Phase 3: Agent Integration Updates
1. **Configuration Management**
   - Support for external agent URLs
   - Environment-based agent configuration
   - AWS Secrets Manager integration for agent endpoints

2. **Error Handling**
   - Connection failure handling per message
   - Timeout management for individual connections
   - Fallback responses for agent unavailability

## File Structure Changes

```
vital_chatwoot_bridge/
├── agents/
│   ├── per_message_client.py     # NEW: Per-message WebSocket client
│   ├── mock_agent.py            # EXISTING: For testing
│   └── websocket_manager.py     # REMOVE: Replace with per_message_client
├── handlers/
│   ├── webhook_handler.py       # UPDATE: Use per-message client
│   └── response_handler.py      # NEW: Handle multiple responses
├── deployment/
│   ├── docker-compose.yml       # NEW: Production (bridge only)
│   ├── docker-compose.test.yml  # RENAMED: Testing with mocks
│   └── docker-compose.dev.yml   # NEW: Development environment
```

## API Endpoints

### Existing Endpoints (No Changes)
- `POST /webhook/chatwoot` - Main webhook receiver
- `GET /health` - Health check
- `GET /agents/status` - Agent connection status (updated for per-message)

### New Endpoints
- `POST /api/v1/messages` - Send message to Chatwoot (for external agents)
- `GET /api/v1/agents/test/{agent_id}` - Test agent connectivity
- `POST /api/v1/agents/reload` - Reload agent configuration

## Testing Strategy

### Mock Agent Testing
```bash
# Start test environment with mock agents
docker-compose -f docker-compose.test.yml up

# Run integration tests
python -m pytest tests/integration/
```

### Real Agent Testing
```bash
# Start production bridge only
docker-compose up

# Configure real agent endpoints
export INBOX_AGENT_MAPPINGS='[{"inbox_id": "1", "agent_config": {"agent_id": "real-agent", "websocket_url": "ws://external-agent:8080"}}]'

# Test with real agent
curl -X POST http://localhost:8000/api/v1/agents/test/real-agent
```

## Migration Steps

### Step 1: Backup Current Implementation
- Create backup of current websocket_manager.py
- Backup current docker-compose files

### Step 2: Implement Per-Message Client
- Create new `per_message_client.py`
- Implement connection-per-message logic
- Add support for multiple responses

### Step 3: Update Webhook Handler
- Modify to use per-message client
- Update response handling for multiple messages
- Test with mock agents

### Step 4: Restructure Docker Compose
- Rename existing files for testing
- Create production docker-compose.yml
- Update documentation

### Step 5: Test and Validate
- Run full test suite with mock agents
- Test with real agent (if available)
- Performance testing for connection overhead

## Benefits of Revised Architecture

### Operational Benefits
- **Simplified Deployment**: No persistent connection state to manage
- **Better Resource Usage**: Connections created only when needed
- **Easier Scaling**: No connection limits per bridge instance
- **Improved Reliability**: Connection failures don't affect other messages

### Development Benefits
- **Easier Testing**: Each message is independent
- **Simpler Debugging**: Clear connection lifecycle per message
- **Better Error Isolation**: Connection issues don't cascade
- **Flexible Agent Integration**: Easy to connect to external services

### Production Benefits
- **Real Agent Support**: Connect to any WebSocket-enabled AI service
- **Multiple Response Support**: Agents can send multiple messages per input
- **Proactive Messaging**: Bridge API for external message sending
- **Configuration Flexibility**: Runtime agent configuration updates

## Success Metrics

### Performance Targets
- Connection establishment time < 2 seconds
- Message processing time < 30 seconds
- Support for 100+ concurrent messages
- Zero persistent connection overhead

### Reliability Targets
- Message delivery success rate > 99.9%
- Connection failure recovery < 1 second
- Zero message loss during agent unavailability
- Graceful degradation under load

## Next Steps

1. **Implement per-message WebSocket client**
2. **Update webhook handler for new client**
3. **Restructure docker-compose files**
4. **Test with existing mock agents**
5. **Document real agent integration**
6. **Deploy and validate changes**

---

*This revised plan maintains all existing functionality while enabling integration with real AI agents through per-message WebSocket connections, providing better resource utilization and operational simplicity.*