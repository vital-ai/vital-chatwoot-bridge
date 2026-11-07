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
```

### Configuration

All configuration via environment variables. Hierarchical config (inbox mappings, API integrations) uses `CW_BRIDGE__` prefix with `__` separator. See [`env.example`](env.example).

## Account modes

`CW_BRIDGE__chatwoot__account_mode` picks one:

| | `single` (default) | `multi` |
|---|---|---|
| Chatwoot accounts | One: `chatwoot.account_id` | Several, typically one per application, each with its own API token (`CW_BRIDGE__chatwoot__accounts__<id>__token`) |
| Inbox → agent routes | `CW_BRIDGE__inbox_agents__<inbox>__*` | Route files (`CW_BRIDGE__routing__files`, see [`config/routes.example.yml`](config/routes.example.yml)), reloaded with `POST /api/v1/routes/reload` |
| Management paths | `/api/v1/chatwoot/...`, and `/api/v1/chatwoot/accounts/{id}/...` for the configured account | Only `/api/v1/chatwoot/accounts/{id}/...`, for an account that has routes; the paths without the account answer 400 |
| A message for an inbox with no route | Ignored | Ignored, counted, reported as `unrouted` |
| Delivery reports | Off unless enabled | On |

In both modes:

- **Pausing an inbox** (`POST /api/v1/routes/{account}/{inbox}/pause` with `{by, reason}`, then `/resume`): its messages still arrive in Chatwoot, but none is handed to its agent. The pause is kept in Redis, so it survives restarts, and reloading the routes never ends it.
- **Retries and reports:** each message is handed to its agent with the route's `retries`. Its outcome (`delivered`, `failed`, `paused` or `unrouted`, with the attempts and the last error, never the text) is posted to `CW_BRIDGE__deliveries__report_url`. `POST /api/v1/deliveries/{message_id}/retry` with `{account_id, conversation_id}` hands one message to its agent again.
- **`/status`** shows the routes, the paused inboxes and each agent's health (last success, last error, consecutive failures).
- **Callers** are checked by the token's `azp` against `CW_BRIDGE__keycloak__allowed_azps`.

### Conversation operations

At both management prefixes:

| Call | What it does |
|---|---|
| `POST .../conversations/{id}/notes` `{content, content_attributes?}` | A private note. `Idempotency-Key` makes a repeat return the first result without writing again; the key is also Chatwoot's `echo_id` |
| `POST .../conversations/{id}/replies` `{content, content_attributes?}` | A reply through the conversation's inbox (by email for an email inbox). Idempotent the same way |
| `GET`, `POST .../conversations/{id}/labels` `{labels}`, `DELETE .../labels/{label}` | Read, add (merged with the labels it has), remove |
| `POST .../conversations/{id}/status` `{status}` | `open`, `pending`, `resolved` or `snoozed` (with `snoozed_until`) |
| `POST .../conversations/{id}/assignee` `{assignee_id?, team_id?}` | Assign to an agent or team |
| `GET .../contacts?email=` or `?vital_member_id=` | Contacts that match exactly (the second is a contact custom attribute) |
| `GET .../conversations/{id}/messages/{mid}/attachments/{aid}` | The attachment's bytes, streamed (25 MB at most); the API token never goes to the storage host Chatwoot redirects to |
| `GET .../inboxes/{id}/messages/inbound?since=` | Incoming messages since a time, newest first |

The client library has the same calls (`add_note`, `reply`, `add_labels`, `set_status`, `assign`, `find_contacts`, `open_attachment`, `inbound_messages`, and `routes`, `pause_inbox`, `resume_inbox`, `reload_routes`, `retry_delivery`). `client.for_account(id)` scopes every management call to one account, as multi mode requires.

## Architecture

```
vital_chatwoot_bridge/
  api/
    routes.py                    # Health endpoint
    api_inbox_routes.py          # LoopMessage / Attentive inbound/outbound
    chatwoot_management_routes.py  # Management REST API, at /api/v1/chatwoot and /api/v1/chatwoot/accounts/{id}
    routing_routes.py            # Routes, pause/resume, reload, delivery retry
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
  routing/
    routes.py                    # The route table: single mode from settings, multi mode from route files
    pauses.py                    # Paused inboxes, in Redis
    idempotency.py               # Idempotency keys for notes and replies, in Redis
    deliveries.py                # Delivery reports and agent health
