# Vital Chatwoot Bridge - Implementation Plan

## Overview
The Vital Chatwoot Bridge is a FastAPI service that acts as a bridge between Chatwoot (customer support platform) and AI agents. It receives webhook events from Chatwoot, forwards messages to AI agents via WebSocket connections, and posts AI responses back to Chatwoot conversations.

## Architecture

### Core Components
1. **Webhook Handler** - Receives Chatwoot webhook events
2. **WebSocket Manager** - Manages connections to N AI agents
3. **Message Transformer** - Converts between Chatwoot and AI agent message formats
4. **Chatwoot API Client** - Posts responses back to Chatwoot
5. **Configuration Manager** - Maps Chatwoot inboxes to AI agents

### Message Flow Patterns

#### Synchronous Flow (Immediate Response)
```
Chatwoot → Webhook → WebSocket → AI Agent → WebSocket Response → Webhook Response → Chatwoot
```
- Used when AI agent responds quickly (< 30 seconds)
- Response included directly in webhook HTTP response
- Chatwoot displays message immediately

#### Asynchronous Flow (Delayed Response)
```
Chatwoot → Webhook → WebSocket → AI Agent → WebSocket Response → Chatwoot API → Inbox
```
- Used when AI agent takes longer to respond
- Webhook returns HTTP 200 immediately
- AI response posted separately via Chatwoot API

## Chatwoot Integration

### Webhook Events to Handle
- `message_created` - Customer sends a message
- `conversation_created` - New conversation started
- `webwidget_triggered` - Customer opens chat widget

### Chatwoot API Usage
- **Endpoint**: `POST /api/v1/accounts/{account_id}/conversations/{conversation_id}/messages`
- **Authentication**: Static `api_access_token` from Profile Settings
- **Headers**: `api_access_token: YOUR_TOKEN`
- **Payload**: `{"content": "AI response", "message_type": "outgoing"}`

### Authentication Details
- **Token Type**: User access token (static, long-lived)
- **Generation**: Chatwoot Profile Settings → Access Token
- **Usage**: Same token for all API calls
- **Security**: No webhook signature verification available in Chatwoot

## Message Structure & Correlation

### Message Flow with Identifiers

#### Bridge → AI Agent Message Format
```json
{
  "message_id": "webhook_msg_123",          // For correlation in sync responses
  "inbox_id": 1,                            // Chatwoot inbox identifier
  "conversation_id": 456,                    // Chatwoot conversation ID
  "content": "Hello, I need help",           // Customer message content
  "sender": {
    "id": 789,
    "name": "John Doe",
    "email": "john@example.com"
  },
  "context": {
    "channel": "web_widget",
    "created_at": "2025-01-07T09:47:24Z",
    "additional_attributes": {}
  },
  "response_mode": "sync" | "async"         // Expected response type
}
```

#### AI Agent → Bridge Response Format
```json
{
  "message_id": "webhook_msg_123",          // Correlation ID (for sync responses)
  "inbox_id": 1,                            // Target inbox for routing
  "conversation_id": 456,                    // Target conversation
  "content": "I can help you with that!",   // AI response content
  "response_type": "sync" | "async",        // Response handling mode
  "metadata": {
    "agent_id": "agent1",
    "processing_time_ms": 1500,
    "confidence": 0.95
  }
}
```

### Message Correlation Strategy
- **Synchronous Flow**: `message_id` links webhook request to AI response
- **Asynchronous Flow**: `inbox_id` + `conversation_id` for routing
- **Error Handling**: Unmatched `message_id` triggers fallback response

## Configuration Structure

### Enhanced Settings
```python
class AgentConfig(BaseModel):
    agent_id: str
    websocket_url: str
    timeout_seconds: int = 30
    
class InboxMapping(BaseModel):
    inbox_id: int
    agent_config: AgentConfig
    
class Settings(BaseSettings):
    # Chatwoot API Configuration
    chatwoot_base_url: str
    chatwoot_api_access_token: str
    chatwoot_account_id: int
    
    # AI Agent Mappings
    inbox_agent_mappings: List[InboxMapping] = []
    
    # Response Configuration
    default_response_timeout: int = 30
    enable_async_responses: bool = True
    max_sync_response_time: int = 25  # Leave buffer for HTTP response
```

### Environment Variables
```bash
# Chatwoot Configuration
CHATWOOT_BASE_URL=https://your-chatwoot-instance.com
CHATWOOT_API_ACCESS_TOKEN=your-static-token
CHATWOOT_ACCOUNT_ID=1

# AI Agent Configuration (JSON)
INBOX_AGENT_MAPPINGS='[{"inbox_id": 1, "agent_config": {"agent_id": "agent1", "websocket_url": "ws://agent1:8080"}}]'

# Response Settings
DEFAULT_RESPONSE_TIMEOUT=30
ENABLE_ASYNC_RESPONSES=true
```

## Implementation Plan

### Phase 1: Core Infrastructure
1. **Update Configuration**
   - Extend `Settings` class with Chatwoot and AI agent config
   - Add Pydantic models for inbox mappings

2. **Create Base Models**
   - Chatwoot webhook event models
   - AI agent message models
   - Response models

### Phase 2: Chatwoot Integration
1. **Webhook Handler**
   - FastAPI endpoints for webhook events
   - Event parsing and validation
   - Inbox-to-agent routing logic

2. **Chatwoot API Client**
   - HTTP client for posting messages
   - Error handling and retry logic
   - Rate limiting support

### Phase 3: AI Agent Communication
1. **WebSocket Manager**
   - Connection pool for multiple AI agents
   - Connection health monitoring
   - Reconnection logic

2. **Message Transformation**
   - Chatwoot → AI agent format conversion
   - AI agent → Chatwoot format conversion
   - Context preservation

### Phase 4: Response Handling
1. **Synchronous Response Handler**
   - Timeout management
   - Direct webhook response

2. **Asynchronous Response Handler**
   - Background task processing
   - Chatwoot API posting
   - Error handling

### Phase 5: Production Features
1. **Error Handling & Resilience**
   - Fallback responses
   - Circuit breaker pattern
   - Dead letter queues

2. **Logging**
   - Structured logging
   - Health checks

## File Structure

```
vital_chatwoot_bridge/
├── __init__.py
├── main.py                    # FastAPI app
├── core/
│   ├── __init__.py
│   ├── config.py             # Enhanced settings
│   └── models.py             # Pydantic models
├── chatwoot/
│   ├── __init__.py
│   ├── webhook_handler.py    # Webhook endpoints
│   ├── api_client.py         # Chatwoot API client
│   └── models.py             # Chatwoot data models
├── agents/
│   ├── __init__.py
│   ├── websocket_manager.py  # WebSocket connections
│   ├── message_transformer.py # Format conversion
│   ├── mock_agent.py         # Mock AI agent for testing
│   └── models.py             # AI agent models
├── handlers/
│   ├── __init__.py
│   ├── sync_handler.py       # Synchronous responses
│   └── async_handler.py      # Asynchronous responses
├── utils/
│   ├── __init__.py
│   ├── logging.py            # Structured logging
│   └── exceptions.py         # Custom exceptions
└── testing/
    ├── __init__.py
    ├── mock_chatwoot.py      # Mock Chatwoot service
    ├── test_scenarios.py     # Predefined test scenarios
    └── integration_tests.py  # End-to-end tests
```

## API Endpoints

### Webhook Endpoints
- `POST /webhook/chatwoot` - Main webhook receiver (handles all Chatwoot webhook events)

### Management Endpoints
- `GET /health` - Health check (existing)
- `GET /agents/status` - AI agent connection status
- `GET /config/mappings` - Current inbox-agent mappings
- `POST /config/mappings` - Update mappings (admin)

## Error Handling Strategy

### Webhook Processing Errors
- Invalid payload → HTTP 400 with error details
- Agent unavailable → Fallback response or async retry
- Timeout → Switch to async mode

### AI Agent Communication Errors
- Connection failed → Retry with exponential backoff
- Response timeout → Fallback message
- Invalid response → Log error, send generic response

### Chatwoot API Errors
- Authentication failed → Alert and retry
- Rate limited → Implement backoff
- Invalid conversation → Log and skip

## Security Considerations

### Webhook Security
- Request validation
- IP allowlisting (optional)

### API Security
- Secure token storage (environment variables via ECS)
- Request/response logging

### WebSocket Security
- TLS/WSS connections
- Authentication tokens
- Connection limits

## Deployment Configuration

### Docker Updates
- Add WebSocket client dependencies
- Update health checks
- Add connection monitoring

### AWS ECS Updates
- Configure agent mapping environment variables
- Update resource allocation for WebSocket connections

## Mock AI Agent Implementation

### Purpose
- **Testing**: Validate bridge functionality without external AI dependencies
- **Development**: Rapid iteration and debugging
- **Demo**: Showcase bridge capabilities

### Mock Agent Features
```python
class MockAIAgent:
    def __init__(self, agent_id: str, behavior: str = "echo"):
        self.agent_id = agent_id
        self.behavior = behavior  # "echo", "test", "delay", "error"
    
    async def process_message(self, message: dict) -> dict:
        if self.behavior == "echo":
            return self._echo_response(message)
        elif self.behavior == "test":
            return self._test_response(message)
        elif self.behavior == "delay":
            await asyncio.sleep(5)  # Simulate processing time
            return self._echo_response(message)
        elif self.behavior == "error":
            raise Exception("Mock agent error for testing")
```

### Mock Response Behaviors
1. **Echo Mode**: Returns customer message with "Echo: " prefix
2. **Test Mode**: Returns predefined test responses based on keywords
3. **Delay Mode**: Simulates slow AI processing (5+ seconds)
4. **Error Mode**: Triggers error handling pathways

### Mock Agent WebSocket Server
```python
# Simple WebSocket server for testing
class MockAgentServer:
    async def handle_connection(self, websocket, path):
        async for message in websocket:
            request = json.loads(message)
            response = await self.mock_agent.process_message(request)
            await websocket.send(json.dumps(response))
```

### Test Scenarios
- **Sync Response**: Mock agent responds within 2 seconds
- **Async Response**: Mock agent delays 30+ seconds
- **Error Recovery**: Mock agent throws exceptions
- **Multiple Inboxes**: Different mock behaviors per inbox

## Mock Chatwoot Service Implementation

### Purpose
- **Local Testing**: Complete testing environment without real Chatwoot instance
- **Development**: Rapid iteration and webhook testing
- **CI/CD**: Automated testing in pipelines
- **Demo**: Showcase complete bridge functionality

### Mock Chatwoot Features
```python
class MockChatwootService:
    def __init__(self, host: str = "localhost", port: int = 9000):
        self.host = host
        self.port = port
        self.conversations = {}  # Store mock conversations
        self.messages = {}       # Store mock messages
        self.webhook_urls = []   # Registered webhook endpoints
    
    # Webhook simulation endpoints
    async def trigger_message_created(self, inbox_id: int, content: str)
    async def trigger_conversation_created(self, inbox_id: int)
    async def trigger_webwidget_triggered(self, inbox_id: int)
    
    # Mock Chatwoot API endpoints
    async def receive_message(self, account_id: int, conversation_id: int, message: dict)
    async def get_conversation(self, account_id: int, conversation_id: int)
    async def list_messages(self, account_id: int, conversation_id: int)
```

### Mock Chatwoot API Endpoints

#### Webhook Simulation (for testing bridge)
- `POST /mock/webhook/trigger/message_created` - Trigger message_created webhook
- `POST /mock/webhook/trigger/conversation_created` - Trigger conversation_created webhook
- `POST /mock/webhook/trigger/webwidget_triggered` - Trigger webwidget_triggered webhook
- `POST /mock/webhook/register` - Register bridge webhook URL
- `GET /mock/webhook/history` - View webhook call history

#### Mock Chatwoot API (receives bridge responses)
- `POST /api/v1/accounts/{account_id}/conversations/{conversation_id}/messages` - Receive messages from bridge
- `GET /api/v1/accounts/{account_id}/conversations/{conversation_id}` - Get conversation details
- `GET /api/v1/accounts/{account_id}/conversations/{conversation_id}/messages` - List messages
- `GET /mock/api/received_messages` - View all received messages (testing endpoint)

### Mock Data Generation
```python
class MockDataGenerator:
    @staticmethod
    def create_mock_message_event(inbox_id: int, content: str) -> ChatwootMessageCreatedEvent:
        return ChatwootMessageCreatedEvent(
            id=random.randint(1000, 9999),
            content=content,
            message_type=0,  # incoming
            created_at=int(time.time()),
            sender={
                "id": random.randint(100, 999),
                "name": "Test Customer",
                "email": "customer@test.com",
                "type": "contact"
            },
            conversation=create_mock_conversation(inbox_id),
            inbox={"id": inbox_id, "name": f"Test Inbox {inbox_id}"},
            account={"id": 1, "name": "Test Account"}
        )
```

### Testing Workflow with Mock Services
1. **Start Mock Chatwoot Service** on port 9000
2. **Start Mock AI Agent** on port 8080
3. **Start Bridge Service** on port 8000
4. **Register webhook** URL with mock Chatwoot
5. **Trigger webhook events** via mock Chatwoot API
6. **Verify responses** received by mock Chatwoot

### Mock Service Configuration
```python
class MockChatwootConfig(BaseModel):
    host: str = "localhost"
    port: int = 9000
    webhook_delay_ms: int = 100  # Delay before sending webhooks
    auto_respond: bool = True    # Auto-respond to bridge messages
    log_requests: bool = True    # Log all requests for debugging
    
class MockTestScenario(BaseModel):
    name: str
    inbox_id: int
    messages: List[str]
    expected_responses: int
    timeout_seconds: int = 30
```

## Testing Strategy

### Unit Tests
- Webhook payload parsing
- Message transformation logic
- API client functionality

### Integration Tests
- End-to-end webhook → agent → response flow
- Chatwoot API integration
- WebSocket connection handling

### Load Testing
- Concurrent webhook processing
- Multiple agent connections
- Response time under load

## Success Metrics

### Performance
- Webhook processing time < 100ms
- Synchronous response time < 25s
- Agent connection uptime > 99%

### Reliability
- Message delivery success rate > 99.9%
- Zero data loss
- Graceful degradation under load

### Scalability
- Support 100+ concurrent conversations
- Handle 1000+ messages per minute
- Scale to N AI agents dynamically

## Next Steps

1. **Implement Phase 1** - Update configuration and models
2. **Create mock AI agent** - Testing infrastructure
3. **Create mock Chatwoot service** - Local testing environment
4. **Create webhook handlers** - Basic event processing
5. **Build WebSocket manager** - AI agent communication
6. **Integrate Chatwoot API** - Response posting
7. **Add error handling** - Production resilience
8. **Deploy and test** - End-to-end validation with mock services

---

*This plan provides a comprehensive roadmap for implementing the Vital Chatwoot Bridge with proper separation of concerns, error handling, and production-ready features.*