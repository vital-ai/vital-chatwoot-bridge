# Chatwoot API Inbox Implementation Plan

## Overview

This document outlines the plan to implement API Inbox support for the vital-chatwoot-bridge application. We need to support two distinct API inbox types:

1. **LoopMessage Inbox** - For bidirectional iMessage conversations (inbound from LoopMessage app, outbound from Chatwoot)
2. **Attentive Inbox** - For aggregating marketing messages (inbound-only, templated messages via Attentive API)

## Chatwoot API Inbox Architecture

### How API Inboxes Work in Chatwoot

API Inboxes in Chatwoot are designed for custom integrations where external systems need to send messages into Chatwoot conversations. Unlike built-in channels (email, SMS, website widget), API inboxes require:

1. **Client API Authentication**: Uses `inbox_identifier` + `contact_identifier`
2. **Three-Step Message Flow**:
   - Create/Get Contact → Get `contact_identifier` (source_id)
   - Create/Get Conversation → Get `conversation_id`
   - Send Message → Post message to conversation

### Inbox-Specific Requirements

**LoopMessage Inbox (Bidirectional):**
- **Inbound**: External LoopMessage app calls bridge endpoint to post iMessages to Chatwoot
- **Outbound**: Chatwoot webhook triggers bridge endpoint that forwards messages to LoopMessage
- **Use Case**: Full conversation support for iMessage customer service
- **Integration**: Bridge receives webhooks from Chatwoot for outbound messages

**Attentive Inbox (Aggregation-Only):**
- **Inbound**: Aggregate Attentive messages from multiple sources:
  - **Business → Customer**: `sms.sent` and `email.sent` webhook events from Attentive
  - **Customer → Business SMS**: `sms.inbound_message` webhook events from Attentive
  - **Customer → Business Email**: Email replies captured outside Attentive (separate endpoint)
- **Outbound**: Not supported from Chatwoot (Attentive handles templated responses via their API)
- **Use Case**: Complete message aggregation for Attentive SMS/email campaigns including customer replies
- **Integration**: 
  - Attentive webhooks → Bridge webhook endpoint → Chatwoot
  - Email system → Bridge email endpoint → Chatwoot

### Key API Endpoints

```
POST /public/api/v1/inboxes/{inbox_identifier}/contacts
POST /public/api/v1/inboxes/{inbox_identifier}/contacts/{contact_identifier}/conversations
POST /public/api/v1/inboxes/{inbox_identifier}/contacts/{contact_identifier}/conversations/{conversation_id}/messages
```

## Current Bridge Implementation Status

Based on the retrieved memories and code analysis:

✅ **Already Implemented:**
- Webhook signature verification
- Per-message AIMP integration
- Chatwoot compliance (string IDs)
- Basic Chatwoot API client
- WebSocket communication with agents
- End-to-end message flow (webhook → agent → response)

❌ **Missing for API Inboxes:**
- Client API integration (contact/conversation creation)
- REST endpoints for posting inbound messages to API inboxes
- Outbound message handling for LoopMessage
- Inbox-specific message routing
- Contact/conversation management

## Implementation Plan

### 1. Configuration Enhancement

Add API inbox configuration to support multiple inbox types:

```yaml
# config/api_inboxes.json
{
  "loopmessage": {
    "inbox_identifier": "loop_msg_inbox_123",
    "name": "LoopMessage iMessages",
    "message_types": ["imessage"],
    "contact_identifier_field": "phone_number",
    "supports_outbound": true,
    "outbound_webhook_url": "https://loopmessage-api.com/send",
    "hmac_secret": "optional_hmac_secret"
  },
  "attentive": {
    "inbox_identifier": "attentive_inbox_456", 
    "name": "Attentive Messages",
    "message_types": ["email", "sms"],
    "contact_identifier_field": "email_or_phone",
    "supports_outbound": false,
    "webhook_events": {
      "sms.sent": "business_to_customer",
      "email.sent": "business_to_customer", 
      "sms.inbound_message": "customer_to_business"
    },
    "supports_email_replies": true,
    "description": "Aggregation of Attentive messages via webhook events",
    "hmac_secret": "optional_hmac_secret"
  }
}
```

Environment variables:
```
CHATWOOT_API_INBOXES_CONFIG_PATH=/path/to/api_inboxes.json
CHATWOOT_CLIENT_API_BASE_URL=https://your-chatwoot.com/public/api/v1
LOOPMESSAGE_API_URL=https://loopmessage-api.com
LOOPMESSAGE_API_KEY=your_loopmessage_api_key
ATTENTIVE_WEBHOOK_SECRET=your_attentive_webhook_secret
```

### 2. New Models

Create Pydantic models for API inbox operations:

```python
# vital_chatwoot_bridge/chatwoot/client_models.py

class ChatwootContact(BaseModel):
    identifier: str
    name: Optional[str] = None
    email: Optional[str] = None
    phone_number: Optional[str] = None
    custom_attributes: Dict[str, Any] = {}

class ChatwootConversationRequest(BaseModel):
    custom_attributes: Dict[str, Any] = {}

class ChatwootClientMessage(BaseModel):
    content: str
    message_type: str = "incoming"  # incoming/outgoing
    echo_id: Optional[str] = None
    attachments: Optional[List[Dict]] = None

class APIInboxMessageRequest(BaseModel):
    inbox_type: str  # "loopmessage" or "attentive"
    contact: ChatwootContact
    message: ChatwootClientMessage
    conversation_id: Optional[str] = None  # If continuing existing conversation
```

### 3. Chatwoot Client API Integration

Extend the existing `ChatwootAPIClient` with Client API methods:

```python
# vital_chatwoot_bridge/chatwoot/client_api.py

class ChatwootClientAPI:
    """Client for Chatwoot Client API (public endpoints)."""
    
    async def create_or_get_contact(
        self, 
        inbox_identifier: str, 
        contact: ChatwootContact
    ) -> Dict[str, Any]:
        """Create or retrieve contact, returns contact with source_id."""
        
    async def create_conversation(
        self,
        inbox_identifier: str,
        contact_identifier: str,
        custom_attributes: Dict = None
    ) -> Dict[str, Any]:
        """Create new conversation."""
        
    async def send_message(
        self,
        inbox_identifier: str,
        contact_identifier: str, 
        conversation_id: str,
        message: ChatwootClientMessage
    ) -> Dict[str, Any]:
        """Send message to conversation."""
        
    async def get_or_create_conversation(
        self,
        inbox_identifier: str,
        contact_identifier: str,
        custom_attributes: Dict = None
    ) -> Dict[str, Any]:
        """Get existing conversation or create new one."""
```

### 4. REST API Endpoints

Add new endpoints to `vital_chatwoot_bridge/api/routes.py`:

```python
# New router for API inbox operations
api_inbox_router = APIRouter(prefix="/api/v1/inboxes")

# Inbound message endpoints (both inbox types)
@api_inbox_router.post("/loopmessage/messages/inbound")
async def post_loopmessage_inbound(request: LoopMessageInboundRequest) -> Dict[str, Any]:
    """Receive iMessage from LoopMessage app and post to Chatwoot."""
    
@api_inbox_router.post("/attentive/webhook")
async def handle_attentive_webhook(request: AttentiveWebhookRequest) -> Dict[str, Any]:
    """Receive Attentive webhook and process for Chatwoot aggregation."""
    
@api_inbox_router.post("/attentive/email/inbound")
async def handle_attentive_email_reply(request: AttentiveEmailReplyRequest) -> Dict[str, Any]:
    """Receive email reply (outside Attentive webhooks) and post to Chatwoot for aggregation."""
    
@api_inbox_router.post("/attentive/messages/inbound") 
async def post_attentive_inbound(request: AttentiveInboundRequest) -> Dict[str, Any]:
    """Receive processed Attentive message and post to Chatwoot for aggregation."""

# Outbound message endpoint (LoopMessage only)
@api_inbox_router.post("/loopmessage/messages/outbound")
async def post_loopmessage_outbound(request: LoopMessageOutboundRequest) -> Dict[str, Any]:
    """Receive outbound message from Chatwoot webhook and send to LoopMessage."""

# Generic endpoints
@api_inbox_router.post("/{inbox_type}/messages/inbound")
async def post_generic_inbound_message(
    inbox_type: str, 
    request: APIInboxMessageRequest
) -> Dict[str, Any]:
    """Generic endpoint for posting inbound messages to any configured API inbox."""
```

### 4.1. Webhook Integration for Outbound Messages

Extend existing webhook handler to support API inbox outbound messages:

```python
# vital_chatwoot_bridge/handlers/webhook_handler.py

async def handle_message_created_webhook(event_data: ChatwootWebhookMessageData) -> WebhookResponse:
    """Handle message created webhook - check if outbound message needs forwarding."""
    
    # Check if message is from an API inbox that supports outbound
    inbox_config = await get_api_inbox_config_by_chatwoot_inbox_id(event_data.inbox.id)
    
    if inbox_config and inbox_config.get('supports_outbound') and event_data.message_type == 'outgoing':
        # Forward outbound message to external service
        await forward_outbound_message(inbox_config, event_data)
    
    # Continue with existing webhook processing...
```

### 5. Message Processing Service

Create a service to handle the complete message flow:

```python
# vital_chatwoot_bridge/services/api_inbox_service.py

class APIInboxService:
    """Service for handling API inbox message operations."""
    
    async def process_attentive_webhook(
        self,
        webhook_payload: AttentiveWebhookRequest
    ) -> Dict[str, Any]:
        """
        Process Attentive webhook and convert to Chatwoot message:
        1. Parse webhook event type and determine sender direction
        2. Extract contact information from subscriber data
        3. Extract message content and metadata
        4. Create/get contact and conversation in Chatwoot
        5. Post message with proper sender attribution
        """
        
    async def process_attentive_email_reply(
        self,
        email_reply: AttentiveEmailReplyRequest
    ) -> Dict[str, Any]:
        """
        Process email reply (outside Attentive webhooks) and convert to Chatwoot message:
        1. Extract contact information from email addresses
        2. Create/get contact and conversation in Chatwoot
        3. Post email reply as customer message
        4. Link to original email thread if possible
        """
        
    async def process_inbound_message(
        self, 
        inbox_type: str, 
        message_request: APIInboxMessageRequest
    ) -> Dict[str, Any]:
        """
        Inbound message flow (both inbox types):
        1. Validate inbox configuration
        2. Create/get contact
        3. Create/get conversation  
        4. Set message direction (for Attentive: business vs customer sender)
        5. Send message to Chatwoot
        6. Return result
        """
        
    async def process_outbound_message(
        self, 
        inbox_type: str, 
        message_request: OutboundMessageRequest
    ) -> Dict[str, Any]:
        """
        Outbound message flow (LoopMessage only):
        1. Validate inbox supports outbound
        2. Format message for external API
        3. Send to external service (LoopMessage)
        4. Return delivery status
        """
        
    async def _get_inbox_config(self, inbox_type: str) -> Dict[str, Any]:
        """Get configuration for specific inbox type."""
        
    async def _send_to_external_service(
        self, 
        inbox_config: Dict, 
        message_data: Dict
    ) -> Dict[str, Any]:
        """Send outbound message to external service (LoopMessage)."""
        
    async def handle_chatwoot_outbound_webhook(
        self,
        webhook_data: ChatwootWebhookMessageData
    ) -> Dict[str, Any]:
        """Handle outbound message webhook from Chatwoot for API inboxes."""
```

### 6. Inbox-Specific Request Models

Create specialized models for each inbox type and direction:

```python
# LoopMessage specific models
class LoopMessageContact(BaseModel):
    phone_number: str
    name: Optional[str] = None
    
class LoopMessageInboundRequest(BaseModel):
    """Inbound iMessage from LoopMessage app to Chatwoot."""
    contact: LoopMessageContact
    message_content: str
    message_type: Literal["imessage"] = "imessage"
    conversation_id: Optional[str] = None
    timestamp: Optional[datetime] = None
    
class LoopMessageOutboundRequest(BaseModel):
    """Outbound iMessage from Chatwoot to LoopMessage."""
    phone_number: str
    message_content: str
    conversation_id: str
    chatwoot_message_id: str
    agent_name: Optional[str] = None

# Attentive specific models (inbound-only)
class AttentiveContact(BaseModel):
    email: Optional[str] = None
    phone_number: Optional[str] = None
    name: Optional[str] = None
    
    @validator('email', 'phone_number')
    def validate_contact_method(cls, v, values):
        if not v and not values.get('email') and not values.get('phone_number'):
            raise ValueError('Either email or phone_number must be provided')
        return v

class AttentiveEmailReplyRequest(BaseModel):
    """Email reply captured outside of Attentive webhooks."""
    contact: AttentiveContact
    message_content: str
    subject: Optional[str] = None
    from_email: str  # Customer's email address
    to_email: str   # Business email address that received the reply
    reply_to_message_id: Optional[str] = None  # Reference to original Attentive email if available
    timestamp: Optional[datetime] = None
    email_headers: Optional[Dict[str, str]] = None  # Additional email metadata

class AttentiveWebhookRequest(BaseModel):
    """Attentive webhook payload for message aggregation in Chatwoot."""
    type: Literal["sms.sent", "email.sent", "sms.inbound_message"]
    timestamp: int  # Unix timestamp from Attentive
    company: Dict[str, Any]  # Attentive company info
    subscriber: Dict[str, Any]  # Contact information
    message: Dict[str, Any]  # Message content and metadata
    
class AttentiveInboundRequest(BaseModel):
    """Processed Attentive message for Chatwoot aggregation."""
    contact: AttentiveContact
    message_content: str
    message_type: Literal["email", "sms"]
    sender_type: Literal["business", "customer"]  # Derived from webhook event type
    attentive_event_type: str  # Original webhook event type
    attentive_message_id: str  # Attentive's message ID
    attentive_timestamp: int  # Original Attentive timestamp
    campaign_info: Optional[Dict[str, Any]] = None  # Campaign details if available
```

## Implementation Steps

### Phase 1: Core Infrastructure
1. ✅ Research Chatwoot API capabilities
2. 🔄 Create configuration system for API inboxes
3. 🔄 Implement Chatwoot Client API integration
4. 🔄 Create base models and services

### Phase 2: API Endpoints
1. 🔄 Implement inbound message endpoints (both inbox types)
2. 🔄 Implement LoopMessage outbound endpoint
3. 🔄 Implement LoopMessage-specific inbound/outbound endpoints
4. 🔄 Implement Attentive webhook endpoint
5. 🔄 Implement Attentive email reply endpoint (non-webhook)
6. 🔄 Add request validation and error handling

### Phase 3: Testing & Integration
1. 🔄 Create unit tests for Client API integration
2. 🔄 Create integration tests with mock Chatwoot
3. 🔄 Test with real Chatwoot API inboxes
4. 🔄 Performance testing and optimization

## API Usage Examples

### LoopMessage Inbound iMessage (from LoopMessage app to Chatwoot)
```bash
curl -X POST http://localhost:8000/api/v1/inboxes/loopmessage/messages/inbound \
  -H "Content-Type: application/json" \
  -d '{
    "contact": {
      "phone_number": "+1234567890",
      "name": "John Doe"
    },
    "message_content": "Hello, I need help with my order",
    "message_type": "imessage",
    "timestamp": "2024-01-15T10:30:00Z"
  }'
```

### LoopMessage Outbound iMessage (from Chatwoot to LoopMessage)
```bash
curl -X POST http://localhost:8000/api/v1/inboxes/loopmessage/messages/outbound \
  -H "Content-Type: application/json" \
  -d '{
    "phone_number": "+1234567890",
    "message_content": "Hi John! I can help you with your order. What\'s your order number?",
    "conversation_id": "123",
    "chatwoot_message_id": "456",
    "agent_name": "Sarah"
  }'
```

### Attentive Webhook (sms.sent event)
```bash
curl -X POST http://localhost:8000/api/v1/inboxes/attentive/webhook \
  -H "Content-Type: application/json" \
  -d '{
    "type": "sms.sent",
    "timestamp": 1632945178104,
    "company": {
      "display_name": "Your Company",
      "company_id": "MDc6Q29tcGFueTU"
    },
    "subscriber": {
      "email": "customer@example.com",
      "phone": "+15555555555",
      "external_id": 16467358
    },
    "message": {
      "id": "MDc6TWVzc2FnZTEyNzI1MA",
      "type": "ONE_TIME",
      "text": "Your order has shipped! Track: https://example.attn.tv/l/abc/123",
      "channel": "TEXT"
    }
  }'
```

### Attentive Webhook (sms.inbound_message event)
```bash
curl -X POST http://localhost:8000/api/v1/inboxes/attentive/webhook \
  -H "Content-Type: application/json" \
  -d '{
    "type": "sms.inbound_message",
    "timestamp": 1686927677855,
    "company": {
      "display_name": "Your Company",
      "company_id": "MDc6Q29tcGFueTIyNzM"
    },
    "subscriber": {
      "phone": "+15555555555",
      "external_id": 12345
    },
    "message": {
      "type": "TYPE_CONVERSATION",
      "text": "STOP - Please remove me from your SMS list",
      "to_phone": "+174881"
    }
  }'
```

### Attentive Email Reply (outside webhook system)
```bash
curl -X POST http://localhost:8000/api/v1/inboxes/attentive/email/inbound \
  -H "Content-Type: application/json" \
  -d '{
    "contact": {
      "email": "customer@example.com",
      "name": "Jane Smith"
    },
    "message_content": "Thank you for the shipping notification! When will it arrive?",
    "subject": "Re: Your order has shipped!",
    "from_email": "customer@example.com",
    "to_email": "support@yourcompany.com",
    "timestamp": "2024-01-15T18:30:00Z",
    "email_headers": {
      "message-id": "<reply123@example.com>",
      "in-reply-to": "<original456@attentive.com>"
    }
  }'
```

### Generic API Inbox
```bash
curl -X POST http://localhost:8000/api/v1/inboxes/custom_inbox/messages \
  -H "Content-Type: application/json" \
  -d '{
    "inbox_type": "custom_inbox",
    "contact": {
      "identifier": "user123",
      "email": "user@example.com"
    },
    "message": {
      "content": "Custom message content",
      "message_type": "incoming"
    }
  }'
```

## Security Considerations

1. **HMAC Verification**: Optional HMAC signature verification for each inbox type
2. **Rate Limiting**: Implement rate limiting per inbox type
3. **Input Validation**: Strict validation of all input data
4. **Contact PII**: Secure handling of contact information
5. **API Keys**: Secure storage of Chatwoot API credentials

## Configuration Management

The API inbox configuration should be stored externally (AWS Secrets Manager, as mentioned in memories) rather than baked into the container:

```python
# Load from AWS Secrets Manager or local file
async def load_api_inbox_config() -> Dict[str, Any]:
    if settings.aws_secrets_manager_enabled:
        return await load_from_secrets_manager(settings.api_inbox_config_secret_name)
    else:
        return load_from_file(settings.api_inbox_config_path)
```

## Monitoring & Logging

1. **Message Flow Tracking**: Log each step of the message processing
2. **Performance Metrics**: Track API response times and success rates
3. **Error Handling**: Comprehensive error logging and alerting
4. **Audit Trail**: Log all message posts for compliance

## Future Enhancements

1. **Bulk Message Support**: Batch processing for multiple messages
2. **Message Templates**: Support for message templates per inbox type
3. **Webhook Integration**: Optional webhooks for message status updates
4. **Analytics Integration**: Message delivery and engagement tracking
5. **Multi-tenant Support**: Support for multiple Chatwoot accounts