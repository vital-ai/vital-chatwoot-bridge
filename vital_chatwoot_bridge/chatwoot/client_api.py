"""
Chatwoot Client API integration for API inbox operations.
Handles contact creation, conversation management, and message posting via public endpoints.
"""

import asyncio
import io
import json
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


# ---------------------------------------------------------------------------
# Module-level semaphore (shared across all ChatwootClientAPI instances in this task)
# ---------------------------------------------------------------------------
_chatwoot_semaphore: Optional[asyncio.Semaphore] = None


def _get_semaphore() -> asyncio.Semaphore:
    """Lazy-init the global Chatwoot concurrency semaphore."""
    global _chatwoot_semaphore
    if _chatwoot_semaphore is None:
        settings = get_settings()
        _chatwoot_semaphore = asyncio.Semaphore(settings.rl_max_chatwoot_concurrency)
        logger.info(f"🚦 Chatwoot semaphore initialized — max_concurrency={settings.rl_max_chatwoot_concurrency}")
    return _chatwoot_semaphore


class ChatwootClientAPI:
    """Client for Chatwoot Main API used by API inboxes."""
    
    def __init__(self):
        self.settings = get_settings()
        self.client = httpx.AsyncClient(
            timeout=httpx.Timeout(30.0),
            headers={
                "api_access_token": self.settings.chatwoot_user_access_token,
                "Content-Type": "application/json"
            }
        )
        # Use main API base URL
        self.base_url = f"{self.settings.chatwoot_base_url.rstrip('/')}/api/v1"
    
    async def __aenter__(self):
        """Async context manager entry."""
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        await self.client.aclose()

    # ------------------------------------------------------------------
    # Rate-limited request helper
    # ------------------------------------------------------------------

    async def _request(
        self,
        method: str,
        url: str,
        **kwargs,
    ) -> httpx.Response:
        """Execute an HTTP request through the global semaphore with retry.

        Retries on 429 (rate-limited) and 503 (unavailable) with exponential
        backoff.  Other 5xx errors get a single retry.
        """
        sem = _get_semaphore()
        max_attempts = self.settings.rl_retry_max_attempts
        base_delay = self.settings.rl_retry_base_delay

        last_response: Optional[httpx.Response] = None
        for attempt in range(1, max_attempts + 1):
            async with sem:
                last_response = await self.client.request(method, url, **kwargs)

            status = last_response.status_code

            # Success or client error (not retryable)
            if status < 500 and status not in (429,):
                return last_response

            # Determine delay
            if status in (429, 503):
                retry_after = last_response.headers.get("Retry-After")
                if retry_after:
                    try:
                        delay = float(retry_after)
                    except ValueError:
                        delay = base_delay * (2 ** (attempt - 1))
                else:
                    delay = base_delay * (2 ** (attempt - 1))
            else:
                # Other 5xx — single retry with base delay
                delay = base_delay
                if attempt >= 2:
                    break  # Only one retry for generic 5xx

            if attempt < max_attempts:
                logger.warning(
                    f"🚦 Chatwoot API {status} on {method} {url} — "
                    f"retry {attempt}/{max_attempts} after {delay:.1f}s"
                )
                await asyncio.sleep(delay)

        # All retries exhausted — return last response for caller to handle
        return last_response

    async def create_or_get_contact(
        self, 
        inbox_id: int, 
        contact: ChatwootContact
    ) -> ChatwootContactResponse:
        """
        Create or retrieve a contact using Main API.
        
        Args:
            inbox_id: The numeric inbox ID
            contact: Contact information
            
        Returns:
            ChatwootContactResponse with contact details
            
        Raises:
            ChatwootClientAPIError: If the API request fails
        """
        # Use contact cache for deduplication
        from vital_chatwoot_bridge.chatwoot.contact_cache import get_contact_cache
        cache = get_contact_cache()
        cache_key = contact.phone_number or contact.email or contact.identifier

        async def _do_create_or_get() -> ChatwootContactResponse:
            return await self._create_or_get_contact_uncached(inbox_id, contact)

        return await cache.get_or_create(cache_key, _do_create_or_get)

    async def _create_or_get_contact_uncached(
        self,
        inbox_id: int,
        contact: ChatwootContact,
    ) -> ChatwootContactResponse:
        """Actual contact search/create logic (called through the cache)."""
        try:
            # First, search for existing contact
            search_url = f"{self.base_url}/accounts/{self.settings.chatwoot_account_id}/contacts/search"
            search_params = {"q": contact.phone_number or contact.email or contact.identifier}
            
            logger.info(f"Searching for existing contact: {search_params['q']}")
            search_response = await self._request("GET", search_url, params=search_params)
            
            if search_response.status_code == 200:
                search_data = search_response.json()
                contacts = search_data.get('payload', [])
                
                # Look for exact match
                for existing_contact in contacts:
                    if (existing_contact.get('phone_number') == contact.phone_number or
                        existing_contact.get('email') == contact.email or
                        existing_contact.get('identifier') == contact.identifier):
                        logger.info(f"Found existing contact: {existing_contact['id']}")
                        return ChatwootContactResponse(
                            id=existing_contact['id'],
                            source_id=str(existing_contact['id']),  # Use contact_id as source_id for Main API
                            name=existing_contact.get('name'),
                            email=existing_contact.get('email')
                        )
            
            # Create new contact if not found
            create_url = f"{self.base_url}/accounts/{self.settings.chatwoot_account_id}/contacts"
            payload = {
                "inbox_id": inbox_id,
                "name": contact.name,
                "email": contact.email,
                "phone_number": contact.phone_number,
                "identifier": contact.identifier
            }
            
            # Remove None values
            payload = {k: v for k, v in payload.items() if v is not None}
            
            logger.info(f"Creating new contact for inbox {inbox_id}: {contact.identifier}")
            create_response = await self._request("POST", create_url, json=payload)

            # ----------------------------------------------------------
            # Handle 422 (duplicate contact) gracefully
            # ----------------------------------------------------------
            if create_response.status_code == 422:
                logger.warning(
                    f"Contact already exists (422), re-searching: "
                    f"{contact.phone_number or contact.email or contact.identifier}"
                )
                # Re-search — the contact exists but we lost the race
                retry_resp = await self._request("GET", search_url, params=search_params)
                if retry_resp.status_code == 200:
                    for existing_contact in retry_resp.json().get('payload', []):
                        if (existing_contact.get('phone_number') == contact.phone_number or
                            existing_contact.get('email') == contact.email or
                            existing_contact.get('identifier') == contact.identifier):
                            logger.info(f"Found contact on re-search after 422: {existing_contact['id']}")
                            return ChatwootContactResponse(
                                id=existing_contact['id'],
                                source_id=str(existing_contact['id']),
                                name=existing_contact.get('name'),
                                email=existing_contact.get('email')
                            )
                # If re-search also fails, raise
                raise ChatwootClientAPIError(
                    "Contact 422 (duplicate) but re-search found nothing",
                    status_code=422,
                    response_data=create_response.json() if create_response.content else None
                )
            
            if create_response.status_code not in [200, 201]:
                error_msg = f"Failed to create contact: {create_response.status_code}"
                logger.error(f"{error_msg} - {create_response.text}")
                raise ChatwootClientAPIError(
                    error_msg, 
                    status_code=create_response.status_code, 
                    response_data=create_response.json() if create_response.content else None
                )
            
            response_data = create_response.json()
            # Handle nested payload.contact structure from Chatwoot API
            if 'payload' in response_data and 'contact' in response_data['payload']:
                contact_data = response_data['payload']['contact']
            else:
                contact_data = response_data.get('payload', response_data)
            
            logger.info(f"Contact created successfully: {contact_data.get('id')}")
            
            return ChatwootContactResponse(
                id=contact_data['id'],
                source_id=str(contact_data['id']),  # Use contact_id as source_id for Main API
                name=contact_data.get('name'),
                email=contact_data.get('email')
            )
            
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
        inbox_id: int,
        contact_id: int,
        custom_attributes: Optional[Dict[str, Any]] = None
    ) -> ChatwootConversationResponse:
        """
        Create a new conversation using Main API.
        
        Args:
            inbox_id: The numeric inbox ID
            contact_id: The contact's ID
            custom_attributes: Optional conversation attributes
            
        Returns:
            ChatwootConversationResponse with conversation details
            
        Raises:
            ChatwootClientAPIError: If the API request fails
        """
        url = f"{self.base_url}/accounts/{self.settings.chatwoot_account_id}/conversations"
        
        payload = {
            "source_id": f"contact_{contact_id}",
            "inbox_id": inbox_id,
            "contact_id": contact_id,
            "custom_attributes": custom_attributes or {}
        }
        
        try:
            logger.info(f"Creating conversation for contact {contact_id} in inbox {inbox_id}")
            response = await self._request("POST", url, json=payload)
            
            if response.status_code not in [200, 201]:
                error_msg = f"Failed to create conversation: {response.status_code}"
                logger.error(f"{error_msg} - {response.text}")
                raise ChatwootClientAPIError(
                    error_msg,
                    status_code=response.status_code,
                    response_data=response.json() if response.content else None
                )
            
            response_data = response.json()
            conversation_data = response_data.get('payload', response_data)
            logger.info(f"Conversation created successfully: {conversation_data.get('id')}")
            
            return ChatwootConversationResponse(
                id=conversation_data['id'],
                inbox_id=conversation_data['inbox_id'],
                messages=conversation_data.get('messages', []),
                contact=conversation_data.get('contact', {})
            )
            
        except httpx.RequestError as e:
            error_msg = f"Network error creating conversation: {str(e)}"
            logger.error(error_msg)
            raise ChatwootClientAPIError(error_msg)
        except ValidationError as e:
            error_msg = f"Invalid response format: {str(e)}"
            logger.error(error_msg)
            raise ChatwootClientAPIError(error_msg)
    
    @staticmethod
    def _build_multipart_files(attachments):
        """Convert ChatwootAttachment objects into httpx-compatible file tuples."""
        files = []
        for att in attachments:
            if att.file_bytes:
                files.append(
                    ("attachments[]", (att.filename, io.BytesIO(att.file_bytes), att.content_type))
                )
            elif att.signed_id:
                files.append(
                    ("attachments[]", (None, att.signed_id))
                )
        return files

    async def send_message(
        self,
        conversation_id: int,
        message: ChatwootClientMessage
    ) -> ChatwootMessageResponse:
        """
        Send a message to an existing conversation using Main API.

        Automatically switches to multipart form-data when the message
        carries ``file_attachments`` with ``file_bytes``.
        
        Args:
            conversation_id: The conversation ID
            message: Message content and metadata
            
        Returns:
            ChatwootMessageResponse with message details
            
        Raises:
            ChatwootClientAPIError: If the API request fails
        """
        url = f"{self.base_url}/accounts/{self.settings.chatwoot_account_id}/conversations/{conversation_id}/messages"

        has_file_attachments = (
            message.file_attachments
            and any(a.file_bytes for a in message.file_attachments)
        )

        try:
            logger.info(f"Sending message to conversation {conversation_id}")

            if has_file_attachments:
                # -- Multipart form-data path --------------------------------
                data: Dict[str, Any] = {
                    "content": message.content,
                    "message_type": message.message_type,
                    "private": "false",
                    "content_type": message.content_type,
                }
                if message.echo_id:
                    data["echo_id"] = message.echo_id
                if message.content_attributes:
                    data["content_attributes"] = json.dumps(message.content_attributes)

                files = self._build_multipart_files(message.file_attachments)
                logger.info(f"📎 Uploading {len(files)} attachment(s) via multipart")

                headers = {k: v for k, v in self.client.headers.items()
                           if k.lower() != "content-type"}

                response = await self._request(
                    "POST", url, data=data, files=files, headers=headers
                )
            else:
                # -- JSON path -----------------------------------------------
                payload: Dict[str, Any] = {
                    "content": message.content,
                    "message_type": message.message_type,
                    "private": False,
                    "content_type": message.content_type,
                }
                if message.echo_id:
                    payload["echo_id"] = message.echo_id
                if message.content_attributes:
                    payload["content_attributes"] = message.content_attributes

                # Signed-ID-only attachments
                if message.file_attachments:
                    payload["attachments"] = [
                        {"signed_id": a.signed_id}
                        for a in message.file_attachments if a.signed_id
                    ]
                elif message.attachments:
                    payload["attachments"] = message.attachments

                response = await self._request("POST", url, json=payload)
            
            if response.status_code not in [200, 201]:
                error_msg = f"Failed to send message: {response.status_code}"
                logger.error(f"{error_msg} - {response.text}")
                raise ChatwootClientAPIError(
                    error_msg,
                    status_code=response.status_code,
                    response_data=response.json() if response.content else None
                )
            
            response_data = response.json()
            message_data = response_data.get('payload', response_data)
            logger.info(f"Message sent successfully: {message_data.get('id')}")
            
            return ChatwootMessageResponse(**message_data)
            
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
        contact_id: int
    ) -> List[Dict[str, Any]]:
        """
        Get all conversations for a specific contact using Main API.
        
        Args:
            contact_id: The contact's ID
            
        Returns:
            List of conversation dictionaries
        """
        try:
            url = f"{self.base_url}/accounts/{self.settings.chatwoot_account_id}/contacts/{contact_id}/conversations"
            
            response = await self._request("GET", url)
            
            if response.status_code == 200:
                data = response.json()
                conversations = data.get('payload', [])
                logger.info(f"📞 Found {len(conversations)} existing conversations for contact {contact_id}")
                return conversations
            else:
                logger.warning(f"⚠️ Failed to get conversations: {response.status_code} - {response.text}")
                return []
            
        except Exception as e:
            logger.warning(f"⚠️ Failed to get conversations for contact {contact_id}: {e}")
            return []
    
    async def get_or_create_conversation(
        self,
        inbox_id: int,
        contact_id: int,
        custom_attributes: Optional[Dict[str, Any]] = None
    ) -> ChatwootConversationResponse:
        """
        Get existing conversation or create a new one for the contact using Main API.
        
        This method looks for existing open conversations for the same contact
        in the same inbox and reuses them for back-and-forth messaging.
        
        Args:
            inbox_id: The numeric inbox ID
            contact_id: The contact's ID
            custom_attributes: Optional conversation attributes
            
        Returns:
            ChatwootConversationResponse with conversation details
        """
        try:
            # First, try to find existing open conversations for this contact
            existing_conversations = await self.get_conversations_for_contact(contact_id)
            
            # Look for an open conversation in the same inbox
            for conversation in existing_conversations:
                conv_status = conversation.get('status')
                conv_inbox_id = conversation.get('inbox_id')
                logger.info(f"📞 Checking conversation {conversation['id']}: status={conv_status}, inbox_id={conv_inbox_id}, target_inbox_id={inbox_id}")
                
                if (conv_status in ['open', 'pending'] and 
                    conv_inbox_id == inbox_id):
                    logger.info(f"📞 Reusing existing conversation {conversation['id']} for contact {contact_id}")
                    return ChatwootConversationResponse(
                        id=conversation['id'],
                        inbox_id=conversation['inbox_id'],
                        messages=conversation.get('messages', []),
                        contact=conversation.get('contact', {})
                    )
            
            # No existing open conversation found, create a new one
            logger.info(f"📞 Creating new conversation for contact {contact_id}")
            return await self.create_conversation(
                inbox_id, 
                contact_id, 
                custom_attributes
            )
            
        except Exception as e:
            # If lookup fails, fall back to creating a new conversation
            logger.warning(f"⚠️ Conversation lookup failed, creating new: {e}")
            return await self.create_conversation(
                inbox_id, 
                contact_id, 
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
        Complete flow using Main API: create/get contact, create/get conversation, send message.
        
        Args:
            inbox_identifier: The API inbox identifier (will be converted to numeric ID)
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
            # Get numeric inbox ID from identifier
            api_inbox_config = self.settings.get_api_inbox_by_identifier(inbox_identifier)
            if not api_inbox_config:
                raise ChatwootClientAPIError(f"No API inbox config found for identifier: {inbox_identifier}")
            
            inbox_id = int(api_inbox_config.chatwoot_inbox_id)
            logger.info(f"📞 Using inbox ID {inbox_id} for identifier {inbox_identifier}")
            
            # Step 1: Create or get contact
            contact_response = await self.create_or_get_contact(inbox_id, contact)
            
            # Step 2: Create or get conversation
            if conversation_id:
                # Use existing conversation (simplified - in practice you'd validate it exists)
                conversation_response = ChatwootConversationResponse(
                    id=int(conversation_id),
                    inbox_id=inbox_id,
                    messages=[],
                    contact={}
                )
            else:
                conversation_response = await self.get_or_create_conversation(
                    inbox_id,
                    contact_response.id,  # Use contact.id instead of source_id
                    custom_attributes
                )
            
            # Step 3: Send message
            message_response = await self.send_message(
                conversation_response.id,
                message
            )
            
            return {
                "contact": contact_response.model_dump(),
                "conversation": conversation_response.model_dump(),
                "message": message_response.model_dump(),
                "status": "success"
            }
            
        except ChatwootClientAPIError:
            raise
        except Exception as e:
            error_msg = f"Unexpected error in message flow: {str(e)}"
            logger.error(error_msg)
            raise ChatwootClientAPIError(error_msg)
