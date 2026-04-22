# AWS ECS Fargate Deployment

Deployment configuration for the Vital Chatwoot Bridge service on ECS Fargate.

## Files

- `task-definition.json` — ECS task definition with Secrets Manager integration
- `service-definition.json` — ECS service with ALB, circuit breaker, and ECS Exec

## Prerequisites

1. AWS CLI configured with appropriate permissions
2. ECR repository for the Docker image
3. ECS cluster (Fargate)
4. AWS Secrets Manager secrets (see below)
5. IAM roles: `ecsTaskExecutionRole` + `vital-chatwoot-bridge-task-role`
6. ALB + target group (port 8000, health check path `/health`)

## Configuration

All environment variables use the `CW_BRIDGE__` prefix with `__` separators. See `env.example` for the full list.

### Environment Variables (non-sensitive, in task definition)

| Variable | Value | Description |
|----------|-------|-------------|
| `CW_BRIDGE__app__port` | `8000` | Application port |
| `CW_BRIDGE__app__host` | `0.0.0.0` | Bind address |
| `CW_BRIDGE__app__environment` | `production` | Skips `.env` file loading |
| `CW_BRIDGE__app__log_format` | `json` | JSON structured logs for CloudWatch |
| `CW_BRIDGE__app__log_level` | `INFO` | Log verbosity |
| `CW_BRIDGE__chatwoot__enforce_webhook_signatures` | `true` | Verify Chatwoot webhook HMACs |
| `CW_BRIDGE__timeouts__response` | `30` | Agent response timeout (seconds) |
| `CW_BRIDGE__websocket__connect_timeout` | `10` | WebSocket connect timeout |
| `CW_BRIDGE__websocket__ping_interval` | `30` | WebSocket ping interval |
| `CW_BRIDGE__websocket__ping_timeout` | `10` | WebSocket ping timeout |

### Secrets Manager Secrets (sensitive)

| Env Var | Secret Name |
|---------|-------------|
| `CW_BRIDGE__chatwoot__base_url` | `vital-chatwoot-bridge/chatwoot-base-url` |
| `CW_BRIDGE__chatwoot__user_access_token` | `vital-chatwoot-bridge/chatwoot-user-access-token` |
| `CW_BRIDGE__chatwoot__account_id` | `vital-chatwoot-bridge/chatwoot-account-id` |
| `CW_BRIDGE__bots__default__access_token` | `vital-chatwoot-bridge/bot-default-access-token` |
| `CW_BRIDGE__keycloak__base_url` | `vital-chatwoot-bridge/keycloak-base-url` |
| `CW_BRIDGE__keycloak__realm` | `vital-chatwoot-bridge/keycloak-realm` |
| `CW_BRIDGE__keycloak__client_id` | `vital-chatwoot-bridge/keycloak-client-id` |
| `CW_BRIDGE__keycloak__client_secret` | `vital-chatwoot-bridge/keycloak-client-secret` |
| `CW_BRIDGE__loopmessage__api_url` | `vital-chatwoot-bridge/loopmessage-api-url` |
| `CW_BRIDGE__loopmessage__authorization_key` | `vital-chatwoot-bridge/loopmessage-authorization-key` |
| `CW_BRIDGE__loopmessage__secret_key` | `vital-chatwoot-bridge/loopmessage-secret-key` |
| `CW_BRIDGE__loopmessage__sender_name` | `vital-chatwoot-bridge/loopmessage-sender-name` |

### Structured Config (set as env vars or secrets)

```bash
# Bot definitions (webhook HMAC signing keys from Chatwoot)
CW_BRIDGE__bots__default__access_token=chatwoot-bot-access-token
CW_BRIDGE__bots__default__name=Default Bot

# Inbox → Agent mapping (bot field links to CW_BRIDGE__bots__)
CW_BRIDGE__inbox_agents__1__agent_id=sales-agent
CW_BRIDGE__inbox_agents__1__websocket_url=http://agents-internal:6006
CW_BRIDGE__inbox_agents__1__timeout_seconds=30
CW_BRIDGE__inbox_agents__1__bot=default

# API inbox integrations
CW_BRIDGE__api_inboxes__loopmessage__inbox_identifier=abcdef
CW_BRIDGE__api_inboxes__loopmessage__chatwoot_inbox_id=6
CW_BRIDGE__api_inboxes__loopmessage__name=LoopMessage iMessages
CW_BRIDGE__api_inboxes__loopmessage__message_types=imessage
CW_BRIDGE__api_inboxes__loopmessage__contact_identifier_field=phone_number
CW_BRIDGE__api_inboxes__loopmessage__supports_outbound=true
```

## Deployment Steps

### 1. Create Secrets

```bash
aws secretsmanager create-secret \
  --name "vital-chatwoot-bridge/chatwoot-base-url" \
  --secret-string "https://chatwoot.example.com"

aws secretsmanager create-secret \
  --name "vital-chatwoot-bridge/chatwoot-user-access-token" \
  --secret-string "your-token"

aws secretsmanager create-secret \
  --name "vital-chatwoot-bridge/chatwoot-account-id" \
  --secret-string "4"

aws secretsmanager create-secret \
  --name "vital-chatwoot-bridge/bot-default-access-token" \
  --secret-string "your-bot-access-token"

aws secretsmanager create-secret \
  --name "vital-chatwoot-bridge/keycloak-base-url" \
  --secret-string "https://keycloak.example.com"

aws secretsmanager create-secret \
  --name "vital-chatwoot-bridge/keycloak-realm" \
  --secret-string "your-realm"

aws secretsmanager create-secret \
  --name "vital-chatwoot-bridge/keycloak-client-id" \
  --secret-string "your-client-id"

aws secretsmanager create-secret \
  --name "vital-chatwoot-bridge/keycloak-client-secret" \
  --secret-string "your-client-secret"

aws secretsmanager create-secret \
  --name "vital-chatwoot-bridge/loopmessage-api-url" \
  --secret-string "https://server.loopmessage.com/api/v1"

aws secretsmanager create-secret \
  --name "vital-chatwoot-bridge/loopmessage-authorization-key" \
  --secret-string "your-authorization-key"

aws secretsmanager create-secret \
  --name "vital-chatwoot-bridge/loopmessage-secret-key" \
  --secret-string "your-secret-key"

aws secretsmanager create-secret \
  --name "vital-chatwoot-bridge/loopmessage-sender-name" \
  --secret-string "sender@a.imsg.co"
```

### 2. Create ECR Repository & Push Image

```bash
aws ecr create-repository --repository-name vital-chatwoot-bridge

aws ecr get-login-password --region REGION \
  | docker login --username AWS --password-stdin ACCOUNT_ID.dkr.ecr.REGION.amazonaws.com

docker build -t vital-chatwoot-bridge .
docker tag vital-chatwoot-bridge:latest ACCOUNT_ID.dkr.ecr.REGION.amazonaws.com/vital-chatwoot-bridge:latest
docker push ACCOUNT_ID.dkr.ecr.REGION.amazonaws.com/vital-chatwoot-bridge:latest
```

### 3. Create CloudWatch Log Group

```bash
aws logs create-log-group --log-group-name "/ecs/vital-chatwoot-bridge"
```

### 4. Update & Register Task Definition

Replace placeholders in `task-definition.json`:
- `ACCOUNT_ID` — AWS account ID
- `REGION` — AWS region (e.g. `us-east-1`)
- `XXXXXX` — Secret ARN suffix (find via `aws secretsmanager list-secrets`)

Add any `CW_BRIDGE__*` env vars to the `environment` array.

```bash
aws ecs register-task-definition --cli-input-json file://aws_deploy/task-definition.json
```

### 5. Create/Update ECS Service

```bash
aws ecs create-service --cli-input-json file://aws_deploy/service-definition.json
```

Or update an existing service:

```bash
aws ecs update-service \
  --cluster CLUSTER_NAME \
  --service vital-chatwoot-bridge \
  --task-definition vital-chatwoot-bridge:REVISION \
  --force-new-deployment
```

## IAM Roles

### Task Execution Role (`ecsTaskExecutionRole`)

- `ecr:GetAuthorizationToken`, `ecr:BatchGetImage`, `ecr:GetDownloadUrlForLayer`
- `logs:CreateLogStream`, `logs:PutLogEvents`
- `secretsmanager:GetSecretValue` for all `vital-chatwoot-bridge/*` secrets
- `ssmmessages:*` (if `enableExecuteCommand` is true)

### Task Role (`vital-chatwoot-bridge-task-role`)

Minimal permissions. No AWS services are called by the application directly.

## Health Check

- **Container**: `curl -f http://localhost:8000/health` every 30s, 30s start period
- **ALB target group**: HTTP GET `/health`, expected 200
- **Service**: 60s grace period before health check enforcement

## Debugging

ECS Exec is enabled (`enableExecuteCommand: true`):

```bash
aws ecs execute-command \
  --cluster CLUSTER_NAME \
  --task TASK_ID \
  --container vital-chatwoot-bridge \
  --interactive \
  --command "/bin/bash"
```

## Monitoring

- JSON structured logs in CloudWatch at `/ecs/vital-chatwoot-bridge`
- Query with CloudWatch Insights: `fields @timestamp, level, logger, message | filter level = "ERROR"`
- Deployment circuit breaker auto-rolls back failed deployments
