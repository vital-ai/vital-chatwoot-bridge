# Test Inbound Scripts

This directory contains test scripts for testing the vital-chatwoot-bridge inbound message processing functionality.

## Scripts

### 1. test_loopmessage_inbound.py

Tests LoopMessage inbound message processing via the REST API.

**Endpoint:** `POST /api/v1/inboxes/loopmessage/messages/inbound`

**Usage:**
```bash
# Run all scenarios (default)
python test_loopmessage_inbound.py

# Run specific scenario
python test_loopmessage_inbound.py 1

# Run all scenarios explicitly
python test_loopmessage_inbound.py 0
```

**Test Scenarios:**
1. **Basic Test Message** - Simple test message
2. **Loan Request** - Customer asking for loan assistance  
3. **Customer Support** - General support inquiry

**Features:**
- Command-line scenario selection
- Multiple test scenarios with different message types
- Detailed response parsing and display
- Extracts conversation ID, message ID, and contact info
- Configurable phone numbers and customer names

### 2. test_attentive_inbound.py

Tests Attentive webhook and email inbound message processing.

**Endpoints:** 
- `POST /api/v1/inboxes/attentive/webhook` (for webhook events)
- `POST /api/v1/inboxes/attentive/email/inbound` (for email replies)

**Usage:**
```bash
# Run all scenarios (default)
python test_attentive_inbound.py

# Run specific scenario  
python test_attentive_inbound.py 1

# Run all scenarios explicitly
python test_attentive_inbound.py 0
```

**Test Scenarios:**
1. **SMS Inbound Message** - Customer replying to SMS campaign
2. **SMS Sent** - Business sending promotional SMS
3. **Email Sent** - Business sending marketing email
4. **Email Reply** - Customer replying to business email
5. **Multi-Channel Contact** - Contact with both email and phone
6. **Support Request via SMS** - Customer support request

**Message Types Covered:**
- `sms.inbound_message` - Customer SMS replies
- `sms.sent` - Business SMS campaigns  
- `email.sent` - Business email campaigns
- Email replies (separate endpoint)

**Features:**
- Command-line scenario selection
- Tests all Attentive webhook event types
- Supports both SMS and email messages
- Tests multi-channel contacts (email + phone)
- Realistic webhook payload generation
- Email reply testing with proper headers
- Campaign and metadata simulation

## Configuration

Both scripts are configured to connect to:
- **Bridge URL:** `http://localhost:8009`
- **Test Phone:** `+19179919685`
- **Test Emails:** Various example.com addresses

## Requirements

```bash
pip install requests
```

## Expected Behavior

When running these scripts successfully, you should see:

1. **HTTP 200 responses** from the bridge API
2. **Chatwoot conversation and message IDs** in the response
3. **New conversations** appearing in Chatwoot dashboard
4. **Agent responses** being generated (for LoopMessage)
5. **Proper contact aggregation** (for Attentive multi-channel)

## Troubleshooting

### Common Issues:

1. **Connection refused** - Make sure the bridge is running on localhost:8009
2. **422 Validation errors** - Check payload structure matches API models
3. **500 Internal errors** - Check bridge logs for detailed error information
4. **No agent responses** - Verify AIMP agent is running and configured

### Debug Tips:

- Check bridge logs: `docker compose logs vital-chatwoot-bridge`
- Verify Chatwoot is running and accessible
- Confirm inbox configurations in `.env` file
- Test with single scenarios first before running all

## Integration Testing

These scripts are designed for:
- **Development testing** - Verify API endpoints work correctly
- **Integration testing** - Test end-to-end message flow
- **Regression testing** - Ensure changes don't break existing functionality
- **Demo purposes** - Show system capabilities

Use these scripts as part of your development workflow to ensure the bridge correctly processes inbound messages from both LoopMessage and Attentive platforms.
