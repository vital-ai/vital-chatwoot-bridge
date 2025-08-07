"""
Mock Chatwoot service for local testing of the Vital Chatwoot Bridge.
This service simulates Chatwoot's webhook and API functionality.
"""

import asyncio
import json
import logging
import random
import time
from datetime import datetime
from typing import Dict, List, Any, Optional
from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
import httpx
import uvicorn

logger = logging.getLogger(__name__)

from vital_chatwoot_bridge.chatwoot.models import (
    ChatwootMessageCreatedEvent,
    ChatwootConversationCreatedEvent,
    ChatwootWebWidgetTriggeredEvent,
    ChatwootAPIMessageRequest,
    ChatwootAPIMessageResponse,
    ChatwootAccount,
    ChatwootInbox,
    ChatwootContact,
    ChatwootConversation,
    ChatwootContactInbox,
    ChatwootConversationMeta,
    ChatwootAdditionalAttributes,
    ChatwootBrowserInfo
)


class MockChatwootConfig(BaseModel):
    """Configuration for mock Chatwoot service."""
    host: str = "localhost"
    port: int = 9000
    webhook_delay_ms: int = 100
    auto_respond: bool = True
    log_requests: bool = True
    bridge_webhook_url: str = "http://localhost:8000/webhook/chatwoot"


class WebhookTriggerRequest(BaseModel):
    """Request to trigger a webhook event."""
    inbox_id: str = Field(..., description="Inbox ID for the event as string")
    content: str = Field(default="Hello from mock Chatwoot!", description="Message content")
    sender_name: str = Field(default="Test Customer", description="Sender name")
    sender_email: str = Field(default="customer@test.com", description="Sender email")


class WebhookRegistrationRequest(BaseModel):
    """Request to register a webhook URL."""
    url: str = Field(..., description="Webhook URL to register")
    events: List[str] = Field(default=["message_created", "conversation_created"], description="Events to subscribe to")


class MockConversationData(BaseModel):
    """Mock conversation data storage."""
    id: int
    inbox_id: str
    status: str = "open"
    messages: List[Dict[str, Any]] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=datetime.utcnow)


class MockChatwootService:
    """Mock Chatwoot service for testing."""
    
    def __init__(self, config: MockChatwootConfig):
        self.config = config
        self.app = FastAPI(
            title="Mock Chatwoot Service",
            description="Mock Chatwoot service for testing Vital Chatwoot Bridge",
            version="1.0.0"
        )
        
        # Data storage
        self.conversations: Dict[int, MockConversationData] = {}
        self.messages: Dict[int, Dict[str, Any]] = {}
        self.webhook_urls: List[str] = [config.bridge_webhook_url]
        self.webhook_history: List[Dict[str, Any]] = []
        self.received_messages: List[Dict[str, Any]] = []
        
        # Counters for generating IDs
        self.conversation_counter = 1000
        self.message_counter = 2000
        
        self._setup_routes()
        self._setup_middleware()
    
    def _setup_middleware(self):
        """Setup FastAPI middleware."""
        self.app.add_middleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )
    
    def _setup_routes(self):
        """Setup FastAPI routes."""
        
        # Webhook simulation endpoints
        @self.app.post("/mock/webhook/trigger/message_created")
        async def trigger_message_created(request: WebhookTriggerRequest, background_tasks: BackgroundTasks):
            """Trigger a message_created webhook event."""
            conversation = self._get_or_create_conversation(request.inbox_id)
            event = self._create_message_event(conversation, request)
            
            background_tasks.add_task(self._send_webhook, "message_created", event.dict())
            
            return {
                "status": "triggered",
                "event": "message_created",
                "conversation_id": conversation.id,
                "message_id": event.id
            }
        
        @self.app.post("/mock/webhook/trigger/conversation_created")
        async def trigger_conversation_created(request: WebhookTriggerRequest, background_tasks: BackgroundTasks):
            """Trigger a conversation_created webhook event."""
            conversation = self._create_new_conversation(request.inbox_id)
            event = self._create_conversation_event(conversation, request)
            
            background_tasks.add_task(self._send_webhook, "conversation_created", event.dict())
            
            return {
                "status": "triggered",
                "event": "conversation_created",
                "conversation_id": conversation.id
            }
        
        @self.app.post("/mock/webhook/trigger/webwidget_triggered")
        async def trigger_webwidget_triggered(request: WebhookTriggerRequest, background_tasks: BackgroundTasks):
            """Trigger a webwidget_triggered webhook event."""
            conversation = self._get_or_create_conversation(request.inbox_id)
            event = self._create_webwidget_event(conversation, request)
            
            background_tasks.add_task(self._send_webhook, "webwidget_triggered", event.dict())
            
            return {
                "status": "triggered",
                "event": "webwidget_triggered",
                "conversation_id": conversation.id
            }
        
        @self.app.post("/mock/webhook/register")
        async def register_webhook(request: WebhookRegistrationRequest):
            """Register a webhook URL."""
            if request.url not in self.webhook_urls:
                self.webhook_urls.append(request.url)
            
            return {
                "status": "registered",
                "url": request.url,
                "events": request.events,
                "total_webhooks": len(self.webhook_urls)
            }
        
        @self.app.get("/mock/webhook/history")
        async def get_webhook_history():
            """Get webhook call history."""
            return {
                "history": self.webhook_history,
                "total_calls": len(self.webhook_history)
            }
        
        # Mock Chatwoot API endpoints (receive bridge responses)
        @self.app.post("/api/v1/accounts/{account_id}/conversations/{conversation_id}/messages")
        async def receive_message(
            account_id: str,
            conversation_id: str,
            message: ChatwootAPIMessageRequest
        ) -> ChatwootAPIMessageResponse:
            """Receive a message from the bridge (simulating Chatwoot API)."""
            
            # Store received message for testing
            received_msg = {
                "account_id": account_id,
                "conversation_id": conversation_id,
                "content": message.content,
                "message_type": message.message_type,
                "private": message.private,
                "received_at": datetime.utcnow().isoformat(),
                "sender": "bridge"
            }
            self.received_messages.append(received_msg)
            
            if self.config.log_requests:
                logger.info(f"📨 MOCK CHATWOOT: Received message: {message.content} (conversation: {conversation_id})")
            
            # Create response
            message_id = str(self.message_counter)
            self.message_counter += 1
            
            response = ChatwootAPIMessageResponse(
                id=message_id,
                content=message.content,
                account_id=account_id,
                inbox_id=self._get_inbox_id_for_conversation(conversation_id),
                conversation_id=conversation_id,
                message_type=1,  # outgoing
                created_at=int(time.time()),
                updated_at=int(time.time()),
                private=message.private,
                status="sent",
                content_type=message.content_type,
                content_attributes=message.content_attributes,
                sender_type="user",
                sender_id="1"
            )
            
            return response
        
        @self.app.get("/api/v1/accounts/{account_id}/conversations/{conversation_id}")
        async def get_conversation(account_id: int, conversation_id: int):
            """Get conversation details."""
            conversation = self.conversations.get(conversation_id)
            if not conversation:
                raise HTTPException(status_code=404, detail="Conversation not found")
            
            return {
                "id": conversation.id,
                "inbox_id": conversation.inbox_id,
                "status": conversation.status,
                "messages": conversation.messages,
                "created_at": conversation.created_at.isoformat()
            }
        
        @self.app.get("/api/v1/accounts/{account_id}/conversations/{conversation_id}/messages")
        async def list_messages(account_id: str, conversation_id: str):
            """List messages in a conversation."""
            conversation = self.conversations.get(conversation_id)
            if not conversation:
                raise HTTPException(status_code=404, detail="Conversation not found")
            
            return {
                "messages": conversation.messages,
                "count": len(conversation.messages)
            }
        
        # Testing endpoints
        @self.app.get("/mock/api/received_messages")
        async def get_received_messages():
            """Get all messages received from the bridge."""
            return {
                "messages": self.received_messages,
                "count": len(self.received_messages)
            }
        
        @self.app.get("/debug/conversations")
        async def get_conversations():
            """Get all mock conversations."""
            return {
                "conversations": [conv.dict() for conv in self.conversations.values()],
                "total": len(self.conversations)
            }
        
        @self.app.get("/debug/recent-messages")
        async def get_recent_messages():
            """Get recent messages received from the bridge for testing verification."""
            # Return the last 50 messages received from the bridge
            recent_messages = self.received_messages[-50:] if len(self.received_messages) > 50 else self.received_messages
            return recent_messages
        
        @self.app.post("/debug/reset")
        async def reset_data():
            """Reset all mock data."""
            self.conversations.clear()
            self.messages.clear()
            self.webhook_history.clear()
            self.received_messages.clear()
            self.conversation_counter = 1000
            self.message_counter = 2000
            return {"status": "reset", "message": "All mock data cleared"}
        
        @self.app.get("/mock/health")
        async def health_check():
            """Health check endpoint."""
            return {
                "status": "ok",
                "service": "mock-chatwoot",
                "conversations": len(self.conversations),
                "received_messages": len(self.received_messages),
                "webhook_urls": len(self.webhook_urls)
            }
    
    def _get_or_create_conversation(self, inbox_id: str) -> MockConversationData:
        """Get existing conversation or create new one."""
        # Find existing conversation for inbox
        for conv in self.conversations.values():
            if conv.inbox_id == inbox_id and conv.status == "open":
                return conv
        
        # Create new conversation
        return self._create_new_conversation(inbox_id)
    
    def _create_new_conversation(self, inbox_id: str) -> MockConversationData:
        """Create a new conversation."""
        conversation_id = self.conversation_counter
        self.conversation_counter += 1
        
        conversation = MockConversationData(
            id=conversation_id,
            inbox_id=inbox_id
        )
        
        self.conversations[conversation_id] = conversation
        return conversation
    
    def _get_inbox_id_for_conversation(self, conversation_id: str) -> str:
        """Get inbox ID for a conversation."""
        conversation = self.conversations.get(conversation_id)
        return conversation.inbox_id if conversation else "1"
    
    def _create_message_event(self, conversation: MockConversationData, request: WebhookTriggerRequest) -> ChatwootMessageCreatedEvent:
        """Create a mock message_created event."""
        message_id = self.message_counter
        self.message_counter += 1
        
        # Create mock data
        contact = ChatwootContact(
            id=str(random.randint(100, 999)),
            name=request.sender_name,
            avatar=None,
            account=ChatwootAccount(id="1", name="Test Account")
        )
        
        inbox = ChatwootInbox(id=request.inbox_id, name=f"Test Inbox {request.inbox_id}")
        account = ChatwootAccount(id="1", name="Test Account")
        
        contact_inbox = ChatwootContactInbox(
            id=str(random.randint(1000, 9999)),
            contact_id=contact.id,
            inbox_id=request.inbox_id,
            source_id=f"source_{random.randint(1000, 9999)}",
            created_at=datetime.utcnow().isoformat(),
            updated_at=datetime.utcnow().isoformat()
        )
        
        browser_info = ChatwootBrowserInfo(
            device_name="Desktop",
            browser_name="Chrome",
            platform_name="Mac",
            browser_version="120.0.0.0",
            platform_version="14.0"
        )
        
        additional_attrs = ChatwootAdditionalAttributes(
            browser=browser_info,
            referer="http://localhost:3000",
            initiated_at={"timestamp": datetime.utcnow().isoformat()}
        )
        
        meta = ChatwootConversationMeta(sender=contact, assignee=None)
        
        chatwoot_conversation = ChatwootConversation(
            id=str(conversation.id),
            inbox_id=request.inbox_id,
            status=conversation.status,
            channel="web_widget",
            can_reply=True,
            contact_inbox=contact_inbox,
            messages=[],
            meta=meta,
            additional_attributes=additional_attrs,
            unread_count=1,
            timestamp=int(time.time()),
            account_id="1"
        )
        
        event = ChatwootMessageCreatedEvent(
            id=str(message_id),
            content=request.content,
            message_type="incoming",  # incoming as string
            created_at=datetime.utcnow().isoformat(),
            sender={
                "id": contact.id,
                "name": contact.name,
                "email": request.sender_email,
                "type": "contact"
            },
            contact={
                "id": contact.id,
                "name": contact.name,
                "email": request.sender_email
            },
            account=account,
            conversation=chatwoot_conversation,
            inbox=inbox
        )
        
        return event
    
    def _create_conversation_event(self, conversation: MockConversationData, request: WebhookTriggerRequest) -> ChatwootConversationCreatedEvent:
        """Create a mock conversation_created event."""
        # Similar to message event but for conversation creation
        contact = ChatwootContact(
            id=str(random.randint(100, 999)),
            name=request.sender_name,
            account=ChatwootAccount(id="1", name="Test Account")
        )
        
        contact_inbox = ChatwootContactInbox(
            id=str(random.randint(1000, 9999)),
            contact_id=contact.id,
            inbox_id=request.inbox_id,
            source_id=f"source_{random.randint(1000, 9999)}",
            created_at=datetime.utcnow().isoformat(),
            updated_at=datetime.utcnow().isoformat()
        )
        
        meta = ChatwootConversationMeta(sender=contact, assignee=None)
        
        event = ChatwootConversationCreatedEvent(
            id=str(conversation.id),
            inbox_id=request.inbox_id,
            status=conversation.status,
            channel="web_widget",
            can_reply=True,
            contact_inbox=contact_inbox,
            messages=[],
            meta=meta,
            timestamp=int(time.time()),
            account_id="1"
        )
        
        return event
    
    def _create_webwidget_event(self, conversation: MockConversationData, request: WebhookTriggerRequest) -> ChatwootWebWidgetTriggeredEvent:
        """Create a mock webwidget_triggered event."""
        contact = ChatwootContact(
            id=str(random.randint(100, 999)),
            name=request.sender_name,
            account=ChatwootAccount(id="1", name="Test Account")
        )
        
        inbox = ChatwootInbox(id=request.inbox_id, name=f"Test Inbox {request.inbox_id}")
        account = ChatwootAccount(id="1", name="Test Account")
        
        event = ChatwootWebWidgetTriggeredEvent(
            id=f"widget_{random.randint(10000, 99999)}",
            contact=contact,
            inbox=inbox,
            account=account,
            current_conversation=None,
            source_id=f"source_{random.randint(1000, 9999)}",
            event_info={
                "initiated_at": {"timestamp": datetime.utcnow().isoformat()},
                "referer": "http://localhost:3000",
                "widget_language": "en",
                "browser_language": "en-US",
                "browser": {
                    "browser_name": "Chrome",
                    "browser_version": "120.0.0.0",
                    "device_name": "Desktop",
                    "platform_name": "Mac",
                    "platform_version": "14.0"
                }
            }
        )
        
        return event
    
    async def _send_webhook(self, event_type: str, event_data: Dict[str, Any]):
        """Send webhook to registered URLs."""
        if self.config.webhook_delay_ms > 0:
            await asyncio.sleep(self.config.webhook_delay_ms / 1000)
        
        webhook_payload = {
            "event": event_type,
            **event_data
        }
        
        # Record webhook call
        webhook_record = {
            "event_type": event_type,
            "payload": webhook_payload,
            "timestamp": datetime.utcnow().isoformat(),
            "urls": self.webhook_urls.copy()
        }
        self.webhook_history.append(webhook_record)
        
        # Send to all registered webhook URLs
        async with httpx.AsyncClient() as client:
            for url in self.webhook_urls:
                try:
                    if self.config.log_requests:
                        logger.info(f"📡 MOCK CHATWOOT: Sending {event_type} webhook to {url}")
                    
                    response = await client.post(
                        url,
                        json=webhook_payload,
                        timeout=30.0
                    )
                    
                    webhook_record[f"response_{url}"] = {
                        "status_code": response.status_code,
                        "response_time_ms": response.elapsed.total_seconds() * 1000
                    }
                    
                    if self.config.log_requests:
                        logger.info(f"📡 MOCK CHATWOOT: Webhook response: {response.status_code}")
                
                except Exception as e:
                    webhook_record[f"error_{url}"] = str(e)
                    if self.config.log_requests:
                        logger.error(f"❌ MOCK CHATWOOT: Webhook error: {e}")
    
    async def start_server(self):
        """Start the mock Chatwoot server."""
        config = uvicorn.Config(
            self.app,
            host=self.config.host,
            port=self.config.port,
            log_level="info"
        )
        server = uvicorn.Server(config)
        await server.serve()


# Standalone server runner
async def run_mock_chatwoot_server(
    host: str = "localhost",
    port: int = 9000,
    bridge_webhook_url: str = "http://localhost:8000/webhook/chatwoot"
):
    """Run the mock Chatwoot server."""
    config = MockChatwootConfig(
        host=host,
        port=port,
        bridge_webhook_url=bridge_webhook_url
    )
    
    service = MockChatwootService(config)
    logger.info(f"🚀 MOCK CHATWOOT: Starting service on http://{host}:{port}")
    logger.info(f"📡 MOCK CHATWOOT: Bridge webhook URL: {bridge_webhook_url}")
    logger.info(f"📋 MOCK CHATWOOT: API docs available at: http://{host}:{port}/docs")
    
    await service.start_server()


if __name__ == "__main__":
    import sys
    
    # Parse command line arguments
    host = sys.argv[1] if len(sys.argv) > 1 else "localhost"
    port = int(sys.argv[2]) if len(sys.argv) > 2 else 9000
    bridge_url = sys.argv[3] if len(sys.argv) > 3 else "http://localhost:8000/webhook/chatwoot"
    
    asyncio.run(run_mock_chatwoot_server(host, port, bridge_url))
