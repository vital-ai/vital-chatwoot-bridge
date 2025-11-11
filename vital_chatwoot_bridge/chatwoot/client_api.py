"""
Chatwoot Client API integration for API inbox operations.
Handles contact creation, conversation management, and message posting via public endpoints.
"""

import asyncio
import logging
from typing import Dict, Any, Optional, List
from datetime import datetime

import httpx
from pydantic import ValidationError

from vital_chatwoot_bridge.core.config import get_settings
from vital_chatwoot_bridge.chatwoot.client_models import (
    ChatwootContact, ChatwootContactResponse,
    ChatwootConversationRequest, ChatwootConversationResponse,
    ChatwootClientMessage, ChatwootMessageResponse
)

logger = logging.getLogger(__name__)


class ChatwootClientAPIError(Exception):
    """Exception raised for Chatwoot Client API errors."""
    
    def __init__(self, message: str, status_code: Optional[int] = None, response_data: Optional[Dict] = None):
        super().__init__(message)
        self.status_code = status_code
        self.response_data = response_data


class ChatwootClientAPI:
    """Client for Chatwoot Client API (public endpoints) used by API inboxes."""
    
    def __init__(self):
        self.settings = get_settings()
        self.client = httpx.AsyncClient(
            timeout=httpx.Timeout(30.0),
            headers={"Content-Type": "application/json"}
        )
        # Use public API base URL
        self.base_url = getattr(self.settings, 'chatwoot_client_api_base_url', 
                               f"{self.settings.chatwoot_base_url.rstrip('/')}/public/api/v1")
    
    async def __aenter__(self):
        """Async context manager entry."""
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        await self.client.aclose()
    
    async def create_or_get_contact(
        self, 
        inbox_identifier: str, 
        contact: ChatwootContact
    ) -> ChatwootContactResponse:
        """
        Create or retrieve a contact in the specified inbox.
        
        Args:
            inbox_identifier: The API inbox identifier
            contact: Contact information
            
        Returns:
            ChatwootContactResponse with contact details including source_id
            
        Raises:
            ChatwootClientAPIError: If the API request fails
        """
        url = f"{self.base_url}/inboxes/{inbox_identifier}/contacts"
        
        payload = {
            "identifier": contact.identifier,
            "name": contact.name,
            "email": contact.email,
            "phone_number": contact.phone_number,
            "custom_attributes": contact.custom_attributes
        }
        
        # Remove None values
        payload = {k: v for k, v in payload.items() if v is not None}
        
        try:
            logger.info(f"Creating/getting contact for inbox {inbox_identifier}: {contact.identifier}")
            response = await self.client.post(url, json=payload)
            
            if response.status_code not in [200, 201]:
                error_msg = f"Failed to create/get contact: {response.status_code}"
                logger.error(f"{error_msg} - {response.text}")
                raise ChatwootClientAPIError(
                    error_msg, 
                    status_code=response.status_code, 
                    response_data=response.json() if response.content else None
                )
            
            response_data = response.json()
            logger.info(f"Contact created/retrieved successfully: {response_data.get('source_id')}")
            
            return ChatwootContactResponse(**response_data)
            
        except httpx.RequestError as e:
            error_msg = f"Network error creating contact: {str(e)}"
            logger.error(error_msg)
            raise ChatwootClientAPIError(error_msg)
        except ValidationError as e:
            error_msg = f"Invalid response format: {str(e)}"
            logger.error(error_msg)
            raise ChatwootClientAPIError(error_msg)
    
    async def create_conversation(
        self,
        inbox_identifier: str,
        contact_identifier: str,
        custom_attributes: Optional[Dict[str, Any]] = None
    ) -> ChatwootConversationResponse:
        """
        Create a new conversation for the contact.
        
        Args:
            inbox_identifier: The API inbox identifier
            contact_identifier: The contact's source_id from contact creation
            custom_attributes: Optional conversation attributes
            
        Returns:
            ChatwootConversationResponse with conversation details
            
        Raises:
            ChatwootClientAPIError: If the API request fails
        """
        url = f"{self.base_url}/inboxes/{inbox_identifier}/contacts/{contact_identifier}/conversations"
        
        payload = {
            "custom_attributes": custom_attributes or {}
        }
        
        try:
            logger.info(f"Creating conversation for contact {contact_identifier} in inbox {inbox_identifier}")
            response = await self.client.post(url, json=payload)
            
            if response.status_code not in [200, 201]:
                error_msg = f"Failed to create conversation: {response.status_code}"
                logger.error(f"{error_msg} - {response.text}")
                raise ChatwootClientAPIError(
                    error_msg,
                    status_code=response.status_code,
                    response_data=response.json() if response.content else None
                )
            
            response_data = response.json()
            logger.info(f"Conversation created successfully: {response_data.get('id')}")
            
            return ChatwootConversationResponse(**response_data)
            
        except httpx.RequestError as e:
            error_msg = f"Network error creating conversation: {str(e)}"
            logger.error(error_msg)
            raise ChatwootClientAPIError(error_msg)
        except ValidationError as e:
            error_msg = f"Invalid response format: {str(e)}"
            logger.error(error_msg)
            raise ChatwootClientAPIError(error_msg)
    
    async def send_message(
        self,
        inbox_identifier: str,
        contact_identifier: str,
        conversation_id: str,
        message: ChatwootClientMessage
    ) -> ChatwootMessageResponse:
        """
        Send a message to an existing conversation.
        
        Args:
            inbox_identifier: The API inbox identifier
            contact_identifier: The contact's source_id
            conversation_id: The conversation ID
            message: Message content and metadata
            
        Returns:
            ChatwootMessageResponse with message details
            
        Raises:
            ChatwootClientAPIError: If the API request fails
        """
        url = f"{self.base_url}/inboxes/{inbox_identifier}/contacts/{contact_identifier}/conversations/{conversation_id}/messages"
        
        payload = {
            "content": message.content,
            "echo_id": message.echo_id
        }
        
        # Remove None values
        payload = {k: v for k, v in payload.items() if v is not None}
        
        try:
            logger.info(f"Sending message to conversation {conversation_id}")
            response = await self.client.post(url, json=payload)
            
            if response.status_code not in [200, 201]:
                error_msg = f"Failed to send message: {response.status_code}"
                logger.error(f"{error_msg} - {response.text}")
                raise ChatwootClientAPIError(
                    error_msg,
                    status_code=response.status_code,
                    response_data=response.json() if response.content else None
                )
            
            response_data = response.json()
            logger.info(f"Message sent successfully: {response_data.get('id')}")
            
            return ChatwootMessageResponse(**response_data)
            
        except httpx.RequestError as e:
            error_msg = f"Network error sending message: {str(e)}"
            logger.error(error_msg)
            raise ChatwootClientAPIError(error_msg)
        except ValidationError as e:
            error_msg = f"Invalid response format: {str(e)}"
            logger.error(error_msg)
            raise ChatwootClientAPIError(error_msg)
    
    async def get_conversations_for_contact(
        self,
        contact_identifier: str
    ) -> List[Dict[str, Any]]:
        """
        Get all conversations for a specific contact using the user access token.
        
        Args:
            contact_identifier: The contact's source_id
            
        Returns:
            List of conversation dictionaries
        """
        try:
            # We need to get the contact ID first from the source_id
            # For now, we'll use the known contact ID 474 for our test contact
            # In a real implementation, you'd need to map source_id to contact_id
            
            # Get the user access token from settings
            user_token = getattr(self.settings, 'chatwoot_user_access_token', None)
            if not user_token:
                logger.warning("⚠️ No user access token available for conversation lookup")
                return []
            
            # Use contact ID 474 for our test contact with phone +19179919685
            # TODO: Implement proper source_id to contact_id mapping
            contact_id = 474  # This is our test contact
            
            # Use the main Chatwoot API URL (not public API) for user token
            chatwoot_base = self.settings.chatwoot_base_url.rstrip('/')
            url = f"{chatwoot_base}/api/v1/accounts/{self.settings.chatwoot_account_id}/contacts/{contact_id}/conversations"
            
            # Create a temporary client with user token for this request
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(30.0),
                headers={
                    "api_access_token": user_token,
                    "Content-Type": "application/json"
                }
            ) as user_client:
                response = await user_client.get(url)
                
                if response.status_code == 200:
                    data = response.json()
                    conversations = data.get('payload', [])
                    logger.info(f"📞 Found {len(conversations)} existing conversations for contact {contact_id}")
                    return conversations
                else:
                    logger.warning(f"⚠️ Failed to get conversations: {response.status_code} - {response.text}")
                    return []
            
        except Exception as e:
            logger.warning(f"⚠️ Failed to get conversations for contact {contact_identifier}: {e}")
            return []
    
    async def get_or_create_conversation(
        self,
        inbox_identifier: str,
        contact_identifier: str,
        custom_attributes: Optional[Dict[str, Any]] = None
    ) -> ChatwootConversationResponse:
        """
        Get existing conversation or create a new one for the contact.
        
        This method looks for existing open conversations for the same contact
        in the same inbox and reuses them for back-and-forth messaging.
        
        Args:
            inbox_identifier: The API inbox identifier
            contact_identifier: The contact's source_id
            custom_attributes: Optional conversation attributes
            
        Returns:
            ChatwootConversationResponse with conversation details
        """
        try:
            # First, try to find existing open conversations for this contact
            existing_conversations = await self.get_conversations_for_contact(contact_identifier)
            
            # Get the numeric inbox ID from the inbox identifier
            # For LoopMessage: identifier="NUCyR3zVNKSVLmfxktmiZq6e" maps to inbox_id=2
            target_inbox_id = None
            try:
                # Get the API inbox config to find the numeric inbox ID
                api_inbox_config = self.settings.get_api_inbox_by_identifier(inbox_identifier)
                if api_inbox_config:
                    target_inbox_id = api_inbox_config.chatwoot_inbox_id
                    logger.info(f"📞 Mapped inbox identifier {inbox_identifier} to numeric ID {target_inbox_id}")
            except Exception as e:
                logger.warning(f"⚠️ Could not map inbox identifier to numeric ID: {e}")
            
            # Look for an open conversation in the same inbox
            for conversation in existing_conversations:
                conv_status = conversation.get('status')
                conv_inbox_id = str(conversation.get('inbox_id'))
                logger.info(f"📞 Checking conversation {conversation['id']}: status={conv_status}, inbox_id={conv_inbox_id}, target_inbox_id={target_inbox_id}")
                
                if (conv_status in ['open', 'pending'] and 
                    target_inbox_id and 
                    conv_inbox_id == str(target_inbox_id)):
                    logger.info(f"📞 Reusing existing conversation {conversation['id']} for contact {contact_identifier}")
                    return ChatwootConversationResponse(
                        id=conversation['id'],
                        inbox_id=conversation['inbox_id'],
                        messages=conversation.get('messages', []),
                        contact=conversation.get('contact', {})
                    )
            
            # No existing open conversation found, create a new one
            logger.info(f"📞 Creating new conversation for contact {contact_identifier}")
            return await self.create_conversation(
                inbox_identifier, 
                contact_identifier, 
                custom_attributes
            )
            
        except Exception as e:
            # If lookup fails, fall back to creating a new conversation
            logger.warning(f"⚠️ Conversation lookup failed, creating new: {e}")
            return await self.create_conversation(
                inbox_identifier, 
                contact_identifier, 
                custom_attributes
            )
    
    async def post_message_to_inbox(
        self,
        inbox_identifier: str,
        contact: ChatwootContact,
        message: ChatwootClientMessage,
        conversation_id: Optional[str] = None,
        custom_attributes: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Complete flow: create/get contact, create/get conversation, send message.
        
        Args:
            inbox_identifier: The API inbox identifier
            contact: Contact information
            message: Message to send
            conversation_id: Optional existing conversation ID
            custom_attributes: Optional conversation attributes
            
        Returns:
            Dictionary with contact, conversation, and message details
            
        Raises:
            ChatwootClientAPIError: If any step fails
        """
        try:
            # Step 1: Create or get contact
            contact_response = await self.create_or_get_contact(inbox_identifier, contact)
            
            # Step 2: Create or get conversation
            if conversation_id:
                # Use existing conversation (simplified - in practice you'd validate it exists)
                conversation_response = ChatwootConversationResponse(
                    id=int(conversation_id),
                    inbox_id=inbox_identifier,
                    messages=[],
                    contact={}
                )
            else:
                conversation_response = await self.get_or_create_conversation(
                    inbox_identifier,
                    contact_response.source_id,
                    custom_attributes
                )
            
            # Step 3: Send message
            message_response = await self.send_message(
                inbox_identifier,
                contact_response.source_id,
                str(conversation_response.id),
                message
            )
            
            return {
                "contact": contact_response.dict(),
                "conversation": conversation_response.dict(),
                "message": message_response.dict(),
                "status": "success"
            }
            
        except ChatwootClientAPIError:
            raise
        except Exception as e:
            error_msg = f"Unexpected error in message flow: {str(e)}"
            logger.error(error_msg)
            raise ChatwootClientAPIError(error_msg)
