"""
Chatwoot API client for posting messages and managing conversations.
"""

import asyncio
import logging
from typing import Dict, Any, Optional, List
from datetime import datetime

import httpx
from pydantic import ValidationError

from vital_chatwoot_bridge.core.config import get_settings
from vital_chatwoot_bridge.chatwoot.models import (
    ChatwootAPIMessageRequest, ChatwootAPIMessageResponse,
    ChatwootConversation, ChatwootMessage
)

logger = logging.getLogger(__name__)


class ChatwootAPIError(Exception):
    """Exception raised for Chatwoot API errors."""
    
    def __init__(self, message: str, status_code: Optional[int] = None, response_data: Optional[Dict] = None):
        super().__init__(message)
        self.status_code = status_code
        self.response_data = response_data


class ChatwootAPIClient:
    """Client for interacting with Chatwoot API."""
    
    def __init__(self):
        self.settings = get_settings()
        self.client = httpx.AsyncClient(
            timeout=httpx.Timeout(30.0),
            headers={
                "api_access_token": self.settings.chatwoot_api_access_token,
                "Content-Type": "application/json"
            }
        )
        self.base_url = self.settings.chatwoot_base_url.rstrip('/')
    
    async def __aenter__(self):
        """Async context manager entry."""
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        await self.client.aclose()
    
    async def send_message(
        self,
        account_id: int,
        conversation_id: int,
        content: str,
        message_type: str = "outgoing",
        private: bool = False,
        content_type: str = "text",
        content_attributes: Optional[Dict[str, Any]] = None
    ) -> ChatwootAPIMessageResponse:
        """
        Send a message to a Chatwoot conversation.
        
        Args:
            account_id: Chatwoot account ID
            conversation_id: Conversation ID
            content: Message content
            message_type: Type of message ("incoming" or "outgoing")
            private: Whether the message is private (internal note)
            content_type: Content type ("text", "input_email", etc.)
            content_attributes: Additional content attributes
            
        Returns:
            API response with message details
            
        Raises:
            ChatwootAPIError: If the API request fails
        """
        try:
            # Prepare request
            request_data = ChatwootAPIMessageRequest(
                content=content,
                message_type=message_type,
                private=private,
                content_type=content_type,
                content_attributes=content_attributes or {}
            )
            
            # API endpoint
            url = f"{self.base_url}/api/v1/accounts/{account_id}/conversations/{conversation_id}/messages"
            
            logger.info(f"📤 REST: Making POST request to Chatwoot API")
            logger.info(f"📤 REST: URL: {url}")
            logger.info(f"📤 REST: Message content: {content[:100]}...")
            logger.info(f"📤 REST: Message type: {message_type}, Private: {private}")
            
            # Make request
            response = await self.client.post(
                url,
                json=request_data.dict(exclude_none=True)
            )
            
            logger.info(f"✅ REST: Received response from Chatwoot API: HTTP {response.status_code}")
            
            # Handle response
            if response.status_code == 200:
                response_data = response.json()
                
                # Parse response
                api_response = ChatwootAPIMessageResponse(**response_data)
                
                logger.info(f"Message sent successfully to conversation {conversation_id}")
                return api_response
            
            else:
                error_data = None
                try:
                    error_data = response.json()
                except:
                    pass
                
                error_msg = f"Failed to send message: HTTP {response.status_code}"
                if error_data:
                    error_msg += f" - {error_data}"
                
                logger.error(error_msg)
                raise ChatwootAPIError(
                    error_msg,
                    status_code=response.status_code,
                    response_data=error_data
                )
        
        except ValidationError as e:
            logger.error(f"Invalid API response: {e}")
            raise ChatwootAPIError(f"Invalid API response: {str(e)}")
        
        except httpx.RequestError as e:
            logger.error(f"HTTP request error: {e}")
            raise ChatwootAPIError(f"HTTP request failed: {str(e)}")
        
        except Exception as e:
            logger.error(f"Unexpected error sending message: {e}")
            raise ChatwootAPIError(f"Unexpected error: {str(e)}")
    
    async def get_conversation(
        self,
        account_id: int,
        conversation_id: int
    ) -> Optional[ChatwootConversation]:
        """
        Get conversation details from Chatwoot.
        
        Args:
            account_id: Chatwoot account ID
            conversation_id: Conversation ID
            
        Returns:
            Conversation details or None if not found
        """
        try:
            url = f"{self.base_url}/api/v1/accounts/{account_id}/conversations/{conversation_id}"
            
            response = await self.client.get(url)
            
            if response.status_code == 200:
                conversation_data = response.json()
                return ChatwootConversation(**conversation_data)
            
            elif response.status_code == 404:
                logger.warning(f"Conversation {conversation_id} not found")
                return None
            
            else:
                logger.error(f"Failed to get conversation: HTTP {response.status_code}")
                return None
        
        except Exception as e:
            logger.error(f"Error getting conversation {conversation_id}: {e}")
            return None
    
    async def list_conversations(
        self,
        account_id: int,
        status: Optional[str] = None,
        assignee_type: Optional[str] = None,
        page: int = 1
    ) -> List[ChatwootConversation]:
        """
        List conversations for an account.
        
        Args:
            account_id: Chatwoot account ID
            status: Filter by status ("open", "resolved", "pending")
            assignee_type: Filter by assignee type
            page: Page number for pagination
            
        Returns:
            List of conversations
        """
        try:
            url = f"{self.base_url}/api/v1/accounts/{account_id}/conversations"
            
            params = {"page": page}
            if status:
                params["status"] = status
            if assignee_type:
                params["assignee_type"] = assignee_type
            
            response = await self.client.get(url, params=params)
            
            if response.status_code == 200:
                data = response.json()
                conversations = []
                
                for conv_data in data.get("data", {}).get("payload", []):
                    try:
                        conversation = ChatwootConversation(**conv_data)
                        conversations.append(conversation)
                    except ValidationError as e:
                        logger.warning(f"Invalid conversation data: {e}")
                
                return conversations
            
            else:
                logger.error(f"Failed to list conversations: HTTP {response.status_code}")
                return []
        
        except Exception as e:
            logger.error(f"Error listing conversations: {e}")
            return []
    
    async def get_conversation_messages(
        self,
        account_id: int,
        conversation_id: int,
        page: int = 1
    ) -> List[ChatwootMessage]:
        """
        Get messages for a conversation.
        
        Args:
            account_id: Chatwoot account ID
            conversation_id: Conversation ID
            page: Page number for pagination
            
        Returns:
            List of messages
        """
        try:
            url = f"{self.base_url}/api/v1/accounts/{account_id}/conversations/{conversation_id}/messages"
            
            params = {"page": page}
            response = await self.client.get(url, params=params)
            
            if response.status_code == 200:
                data = response.json()
                messages = []
                
                for msg_data in data.get("payload", []):
                    try:
                        message = ChatwootMessage(**msg_data)
                        messages.append(message)
                    except ValidationError as e:
                        logger.warning(f"Invalid message data: {e}")
                
                return messages
            
            else:
                logger.error(f"Failed to get messages: HTTP {response.status_code}")
                return []
        
        except Exception as e:
            logger.error(f"Error getting messages for conversation {conversation_id}: {e}")
            return []
    
    async def update_conversation(
        self,
        account_id: int,
        conversation_id: int,
        status: Optional[str] = None,
        assignee_id: Optional[int] = None,
        team_id: Optional[int] = None,
        labels: Optional[List[str]] = None
    ) -> bool:
        """
        Update conversation properties.
        
        Args:
            account_id: Chatwoot account ID
            conversation_id: Conversation ID
            status: New status ("open", "resolved", "pending")
            assignee_id: ID of user to assign conversation to
            team_id: ID of team to assign conversation to
            labels: List of labels to add
            
        Returns:
            True if successful, False otherwise
        """
        try:
            url = f"{self.base_url}/api/v1/accounts/{account_id}/conversations/{conversation_id}"
            
            update_data = {}
            if status:
                update_data["status"] = status
            if assignee_id is not None:
                update_data["assignee_id"] = assignee_id
            if team_id is not None:
                update_data["team_id"] = team_id
            if labels is not None:
                update_data["labels"] = labels
            
            if not update_data:
                logger.warning("No update data provided")
                return False
            
            response = await self.client.patch(url, json=update_data)
            
            if response.status_code == 200:
                logger.info(f"Conversation {conversation_id} updated successfully")
                return True
            else:
                logger.error(f"Failed to update conversation: HTTP {response.status_code}")
                return False
        
        except Exception as e:
            logger.error(f"Error updating conversation {conversation_id}: {e}")
            return False
    
    async def create_contact(
        self,
        account_id: int,
        name: str,
        email: Optional[str] = None,
        phone: Optional[str] = None,
        identifier: Optional[str] = None,
        custom_attributes: Optional[Dict[str, Any]] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Create a new contact in Chatwoot.
        
        Args:
            account_id: Chatwoot account ID
            name: Contact name
            email: Contact email
            phone: Contact phone number
            identifier: Custom identifier
            custom_attributes: Custom attributes
            
        Returns:
            Contact data or None if failed
        """
        try:
            url = f"{self.base_url}/api/v1/accounts/{account_id}/contacts"
            
            contact_data = {"name": name}
            if email:
                contact_data["email"] = email
            if phone:
                contact_data["phone_number"] = phone
            if identifier:
                contact_data["identifier"] = identifier
            if custom_attributes:
                contact_data["custom_attributes"] = custom_attributes
            
            response = await self.client.post(url, json=contact_data)
            
            if response.status_code == 200:
                contact = response.json()
                logger.info(f"Contact created: {contact.get('id')}")
                return contact
            else:
                logger.error(f"Failed to create contact: HTTP {response.status_code}")
                return None
        
        except Exception as e:
            logger.error(f"Error creating contact: {e}")
            return None
    
    async def health_check(self) -> bool:
        """
        Check if the Chatwoot API is accessible.
        
        Returns:
            True if API is accessible, False otherwise
        """
        try:
            # Try to access the accounts endpoint
            url = f"{self.base_url}/api/v1/accounts"
            
            response = await self.client.get(url)
            
            if response.status_code in [200, 401, 403]:
                # 200 = success, 401/403 = auth issue but API is accessible
                logger.info("Chatwoot API health check passed")
                return True
            else:
                logger.warning(f"Chatwoot API health check failed: HTTP {response.status_code}")
                return False
        
        except Exception as e:
            logger.error(f"Chatwoot API health check error: {e}")
            return False
    
    async def close(self):
        """Close the HTTP client."""
        await self.client.aclose()


# Singleton instance for global use
_chatwoot_client: Optional[ChatwootAPIClient] = None


async def get_chatwoot_client() -> ChatwootAPIClient:
    """Get or create the global Chatwoot API client."""
    global _chatwoot_client
    
    if _chatwoot_client is None:
        _chatwoot_client = ChatwootAPIClient()
    
    return _chatwoot_client


async def close_chatwoot_client():
    """Close the global Chatwoot API client."""
    global _chatwoot_client
    
    if _chatwoot_client:
        await _chatwoot_client.close()
        _chatwoot_client = None
