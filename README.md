# vital-chatwoot-bridge

Chatwoot management bridge with REST API and async Python client.

## What It Does

- **REST Management API** — CRUD endpoints for Chatwoot contacts, conversations, messages, agents, and inboxes, secured with Keycloak JWT
- **Unified Messaging** — Single `POST /messages` endpoint for inbound and outbound messages across SMS, email, and iMessage (via LoopMessage)
- **Webhook Bridge** — Routes Chatwoot webhook events to AI agents via WebSocket (AIMP protocol)
- **API Inbox Integrations** — LoopMessage (bidirectional iMessage) and Attentive (inbound aggregation)

## Client Library

Install with client dependencies only (no server deps):

```bash
pip install vital-chatwoot-bridge[client]
```

### Usage

```python
from vital_chatwoot_bridge.client.client import ChatwootBridgeClient

async with ChatwootBridgeClient(
    base_url="https://bridge.example.com",
    keycloak_url="https://keycloak.example.com",
    realm="myrealm",
    client_id="my-client",
    client_secret="secret",
) as client:
    # Contacts
    contacts = await client.list_contacts(page=1)
    contact = await client.create_contact(name="Jane Doe", email="jane@example.com")

    # Conversations
    convs = await client.list_conversations(status="open")
    summary = await client.account_summary()

    # Messages
    result = await client.post_message(
        direction="outbound",
        contact_identifier="jane@example.com",
        message_content="Hello from the bridge!",
        inbox_id=1,
    )

    # Force a new conversation instead of reusing an open one
    result = await client.post_message(
        direction="outbound",
        contact_identifier="+15551234567",
        message_content="New thread",
        inbox_id=6,
        conversation_mode="create_new",
    )
```

### Exception Handling

```python
from vital_chatwoot_bridge.client.exceptions import (
    BridgeClientError,
    AuthenticationError,
    NotFoundError,
    ValidationError,
    ServerError,
)

try:
    contact = await client.get_contact(999999)
except NotFoundError:
    print("Contact not found")
except AuthenticationError:
    print("Token expired or invalid")
```

### Response Models

```python
from vital_chatwoot_bridge.client.models import PaginatedResponse, SingleResponse
```

All list endpoints return `PaginatedResponse` (with `.data`, `.meta`).  
All single-item endpoints return `SingleResponse` (with `.data`).

## Server Deployment

See [`aws_deploy/README.md`](aws_deploy/README.md) for ECS Fargate deployment.

### Local Development

```bash
# Start with Docker Compose
docker compose up --build

# Run endpoint tests
python -m test_endpoint_scripts.test_contacts
python -m test_endpoint_scripts.test_conversations
python -m test_endpoint_scripts.test_messages --case m-send-lm -v

# List all test case IDs
python -m test_endpoint_scripts.test_messages --list
```

### Configuration

All configuration via environment variables. Hierarchical config (inbox mappings, API integrations) uses `CW_BRIDGE__` prefix with `__` separator. See [`env.example`](env.example).

## Architecture

```
vital_chatwoot_bridge/
  api/
    routes.py                    # Health endpoint
    api_inbox_routes.py          # LoopMessage / Attentive inbound/outbound
    chatwoot_management_routes.py  # Management REST API (36 endpoints)
  chatwoot/
    api_client.py                # Chatwoot API client (httpx, retries)
    management_models.py         # Pydantic request/response models
  client/                        # Standalone client library
    client.py                    # ChatwootBridgeClient (async)
    auth.py                      # Keycloak JWT token management
    base.py                      # HTTP client with error mapping
    models.py                    # Response envelope models
    exceptions.py                # Typed exception hierarchy
  core/
    config.py                    # CW_BRIDGE__ env parser integration
  utils/
    env_parser.py                # Generic hierarchical env var parser
    jwt_verify.py                # Keycloak JWT verification (server-side)
    logging_config.py            # JSON / text log formatting
  handlers/
    webhook_handler.py           # Chatwoot webhook → AI agent routing
