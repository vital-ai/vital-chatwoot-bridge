# AWS ECS Fargate Deployment

This directory contains the AWS deployment configuration for the Vital Chatwoot Bridge service.

## Files

- `task-definition.json` - ECS Fargate task definition with AWS Secrets Manager integration
- `service-definition.json` - ECS service configuration (optional)

## Prerequisites

1. **AWS CLI configured** with appropriate permissions
2. **ECR repository** created for the Docker image
3. **ECS cluster** set up for Fargate
4. **AWS Secrets Manager** secrets created
5. **IAM roles** configured with proper permissions

## Setup Instructions

### 1. Create AWS Secrets Manager Secrets

Create the following secrets in AWS Secrets Manager:

```bash
# Chatwoot configuration
aws secretsmanager create-secret \
  --name "vital-chatwoot-bridge/chatwoot-base-url" \
  --description "Chatwoot base URL for Vital Chatwoot Bridge" \
  --secret-string "https://your-chatwoot-instance.com"

aws secretsmanager create-secret \
  --name "vital-chatwoot-bridge/chatwoot-api-token" \
  --description "Chatwoot API token for Vital Chatwoot Bridge" \
  --secret-string "your-chatwoot-api-token"

# Vital AI configuration
aws secretsmanager create-secret \
  --name "vital-chatwoot-bridge/vital-ai-base-url" \
  --description "Vital AI base URL for Vital Chatwoot Bridge" \
  --secret-string "https://your-vital-ai-instance.com"

aws secretsmanager create-secret \
  --name "vital-chatwoot-bridge/vital-ai-api-token" \
  --description "Vital AI API token for Vital Chatwoot Bridge" \
  --secret-string "your-vital-ai-api-token"
```

### 2. Create ECR Repository

```bash
aws ecr create-repository --repository-name vital-chatwoot-bridge
```

### 3. Build and Push Docker Image

```bash
# Get ECR login token
aws ecr get-login-password --region REGION | docker login --username AWS --password-stdin ACCOUNT_ID.dkr.ecr.REGION.amazonaws.com

# Build image
docker build -t vital-chatwoot-bridge .

# Tag image
docker tag vital-chatwoot-bridge:latest ACCOUNT_ID.dkr.ecr.REGION.amazonaws.com/vital-chatwoot-bridge:latest

# Push image
docker push ACCOUNT_ID.dkr.ecr.REGION.amazonaws.com/vital-chatwoot-bridge:latest
```

### 4. Create CloudWatch Log Group

```bash
aws logs create-log-group --log-group-name "/ecs/vital-chatwoot-bridge"
```

### 5. Update Task Definition

Replace the following placeholders in `task-definition.json`:

- `ACCOUNT_ID` - Your AWS account ID
- `REGION` - Your AWS region (e.g., us-east-1)
- `XXXXXX` - The random suffix AWS adds to secret ARNs

### 6. Register Task Definition

```bash
aws ecs register-task-definition --cli-input-json file://aws_deploy/task-definition.json
```

### 7. Create ECS Service

```bash
aws ecs create-service \
  --cluster your-cluster-name \
  --service-name vital-chatwoot-bridge \
  --task-definition vital-chatwoot-bridge:1 \
  --desired-count 1 \
  --launch-type FARGATE \
  --network-configuration "awsvpcConfiguration={subnets=[subnet-12345,subnet-67890],securityGroups=[sg-abcdef],assignPublicIp=ENABLED}"
```

## IAM Roles

### Task Execution Role

The task execution role needs permissions to:
- Pull images from ECR
- Create CloudWatch logs
- Retrieve secrets from AWS Secrets Manager

### Task Role

The task role should have minimal permissions required by your application.

## Security Considerations

- All sensitive configuration is stored in AWS Secrets Manager
- Container runs as non-root user
- Network access is controlled via security groups
- CloudWatch logging enabled for monitoring

## Monitoring

- Health checks configured at container level
- CloudWatch logs available at `/ecs/vital-chatwoot-bridge`
- Application metrics can be added via CloudWatch custom metrics
