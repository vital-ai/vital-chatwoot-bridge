"""
LoopMessage API Client for sending iMessages and SMS.
Based on the LoopMessage API integration patterns.
"""

import logging
import httpx
from typing import Dict, Any, Optional
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class LoopMessageConfig:
    """Configuration for LoopMessage API client."""
    authorization_key: str
    secret_key: str
    base_url: str = "https://server.loopmessage.com/api/v1"


class LoopMessageClientError(Exception):
    """Exception raised for LoopMessage API errors."""
    
    def __init__(self, message: str, error_code: Optional[int] = None, status_code: Optional[int] = None):
        super().__init__(message)
        self.error_code = error_code
        self.status_code = status_code


class LoopMessageClient:
    """Client for LoopMessage API operations."""
    
    def __init__(self, config: LoopMessageConfig):
        self.config = config
        self.client = httpx.AsyncClient(timeout=30.0)
    
    async def __aenter__(self):
        """Async context manager entry."""
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        await self.client.aclose()
    
    async def send_message(
        self,
        recipient: str,
        text: str,
        sender_name: str,
        passthrough: Optional[str] = None,
        attachments: Optional[list] = None,
        effect: Optional[str] = None,
        reply_to_id: Optional[str] = None,
        subject: Optional[str] = None,
        service: str = "imessage"
    ) -> Dict[str, Any]:
        """
        Send a single message via LoopMessage API.
        
        Args:
            recipient: Phone number or email address
            text: Message content
            sender_name: Dedicated sender name
            passthrough: Optional metadata string
            attachments: Optional list of HTTPS URLs
            effect: Optional message effect
            reply_to_id: Optional message ID for replies
            subject: Optional message subject
            service: Service type ('imessage' or 'sms')
            
        Returns:
            LoopMessage API response
            
        Raises:
            LoopMessageClientError: If the API request fails
        """
        endpoint = "/message/send/"
        
        payload = {
            "recipient": recipient,
            "text": text,
            "sender_name": sender_name
        }
        
        # Add optional parameters
        if passthrough:
            payload["passthrough"] = passthrough
        if attachments:
            payload["attachments"] = attachments
        if effect:
            payload["effect"] = effect
        if reply_to_id:
            payload["reply_to_id"] = reply_to_id
        if subject:
            payload["subject"] = subject
        if service != "imessage":
            payload["service"] = service
        
        try:
            logger.info(f"Sending LoopMessage to: {recipient}")
            response_data = await self._make_api_request("POST", endpoint, payload)
            
            # Handle error response
            if not response_data.get("success", False):
                error_code = response_data.get("code", "Unknown")
                error_message = response_data.get("message", "Unknown error")
                raise LoopMessageClientError(
                    f"LoopMessage API Error {error_code}: {error_message}",
                    error_code=error_code
                )
            
            logger.info(f"LoopMessage sent successfully: {response_data.get('message_id', 'Unknown ID')}")
            return response_data
            
        except LoopMessageClientError:
            raise
        except Exception as e:
            error_msg = f"Unexpected error sending LoopMessage: {str(e)}"
            logger.error(error_msg)
            raise LoopMessageClientError(error_msg)
    
    async def send_group_message(
        self,
        group_id: str,
        text: str,
        sender_name: str,
        passthrough: Optional[str] = None,
        attachments: Optional[list] = None
    ) -> Dict[str, Any]:
        """
        Send a message to an iMessage group.
        
        Args:
            group_id: iMessage group identifier
            text: Message content
            sender_name: Dedicated sender name
            passthrough: Optional metadata string
            attachments: Optional list of HTTPS URLs
            
        Returns:
            LoopMessage API response
            
        Raises:
            LoopMessageClientError: If the API request fails
        """
        endpoint = "/message/send/"
        
        payload = {
            "group": group_id,
            "text": text,
            "sender_name": sender_name
        }
        
        # Add optional parameters
        if passthrough:
            payload["passthrough"] = passthrough
        if attachments:
            payload["attachments"] = attachments
        
        try:
            logger.info(f"Sending LoopMessage to group: {group_id}")
            response_data = await self._make_api_request("POST", endpoint, payload)
            
            # Handle error response
            if not response_data.get("success", False):
                error_code = response_data.get("code", "Unknown")
                error_message = response_data.get("message", "Unknown error")
                raise LoopMessageClientError(
                    f"LoopMessage API Error {error_code}: {error_message}",
                    error_code=error_code
                )
            
            logger.info(f"Group LoopMessage sent successfully: {response_data.get('message_id', 'Unknown ID')}")
            return response_data
            
        except LoopMessageClientError:
            raise
        except Exception as e:
            error_msg = f"Unexpected error sending group LoopMessage: {str(e)}"
            logger.error(error_msg)
            raise LoopMessageClientError(error_msg)
    
    async def send_audio_message(
        self,
        recipient: str,
        text: str,
        media_url: str,
        sender_name: str,
        passthrough: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Send an audio message via LoopMessage API.
        
        Args:
            recipient: Phone number or email address
            text: Message text
            media_url: HTTPS URL to audio file
            sender_name: Dedicated sender name
            passthrough: Optional metadata string
            
        Returns:
            LoopMessage API response
            
        Raises:
            LoopMessageClientError: If the API request fails
        """
        endpoint = "/message/send/"
        
        payload = {
            "recipient": recipient,
            "text": text,
            "media_url": media_url,
            "sender_name": sender_name,
            "audio_message": True
        }
        
        if passthrough:
            payload["passthrough"] = passthrough
        
        try:
            logger.info(f"Sending audio LoopMessage to: {recipient}")
            response_data = await self._make_api_request("POST", endpoint, payload)
            
            # Handle error response
            if not response_data.get("success", False):
                error_code = response_data.get("code", "Unknown")
                error_message = response_data.get("message", "Unknown error")
                raise LoopMessageClientError(
                    f"LoopMessage API Error {error_code}: {error_message}",
                    error_code=error_code
                )
            
            logger.info(f"Audio LoopMessage sent successfully: {response_data.get('message_id', 'Unknown ID')}")
            return response_data
            
        except LoopMessageClientError:
            raise
        except Exception as e:
            error_msg = f"Unexpected error sending audio LoopMessage: {str(e)}"
            logger.error(error_msg)
            raise LoopMessageClientError(error_msg)
    
    async def send_reaction(
        self,
        recipient: str,
        text: str,
        message_id: str,
        sender_name: str,
        reaction: str,
        passthrough: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Send a reaction to a message.
        
        Args:
            recipient: Phone number or email address
            text: Message text
            message_id: Target message ID
            sender_name: Dedicated sender name
            reaction: Reaction type (love, like, dislike, laugh, exclaim, question)
            passthrough: Optional metadata string
            
        Returns:
            LoopMessage API response
            
        Raises:
            LoopMessageClientError: If the API request fails
        """
        endpoint = "/message/send/"
        
        payload = {
            "recipient": recipient,
            "text": text,
            "message_id": message_id,
            "sender_name": sender_name,
            "reaction": reaction
        }
        
        if passthrough:
            payload["passthrough"] = passthrough
        
        try:
            logger.info(f"Sending reaction '{reaction}' to message {message_id}")
            response_data = await self._make_api_request("POST", endpoint, payload)
            
            # Handle error response
            if not response_data.get("success", False):
                error_code = response_data.get("code", "Unknown")
                error_message = response_data.get("message", "Unknown error")
                raise LoopMessageClientError(
                    f"LoopMessage API Error {error_code}: {error_message}",
                    error_code=error_code
                )
            
            logger.info(f"Reaction sent successfully: {response_data.get('message_id', 'Unknown ID')}")
            return response_data
            
        except LoopMessageClientError:
            raise
        except Exception as e:
            error_msg = f"Unexpected error sending reaction: {str(e)}"
            logger.error(error_msg)
            raise LoopMessageClientError(error_msg)
    
    async def check_message_status(self, message_id: str) -> Dict[str, Any]:
        """
        Check the status of a message.
        
        Args:
            message_id: Message ID to check
            
        Returns:
            Message status information
            
        Raises:
            LoopMessageClientError: If the API request fails
        """
        endpoint = f"/message/status/{message_id}/"
        
        try:
            logger.info(f"Checking status for message ID: {message_id}")
            response_data = await self._make_api_request("GET", endpoint)
            
            logger.info(f"Status retrieved for message {message_id}: {response_data.get('status', 'Unknown')}")
            return response_data
            
        except Exception as e:
            error_msg = f"Error checking message status: {str(e)}"
            logger.error(error_msg)
            raise LoopMessageClientError(error_msg)
    
    async def _make_api_request(self, method: str, endpoint: str, data: Optional[Dict] = None) -> Dict[str, Any]:
        """
        Make authenticated API request to LoopMessage service.
        
        Args:
            method: HTTP method (GET, POST)
            endpoint: API endpoint path
            data: Optional request payload
            
        Returns:
            API response data
            
        Raises:
            LoopMessageClientError: If the request fails
        """
        url = f"{self.config.base_url}{endpoint}"
        
        headers = {
            "Authorization": self.config.authorization_key,
            "Loop-Secret-Key": self.config.secret_key,
            "Content-Type": "application/json"
        }
        
        logger.debug(f"Making {method} request to {url}")
        
        try:
            if method.upper() == "GET":
                response = await self.client.get(url, headers=headers)
            elif method.upper() == "POST":
                response = await self.client.post(url, headers=headers, json=data)
            else:
                raise ValueError(f"Unsupported HTTP method: {method}")
            
            logger.debug(f"Response status: {response.status_code}")
            
            # Handle HTTP errors with specific LoopMessage error messages
            if response.status_code == 400:
                error_data = response.json() if response.content else {}
                raise LoopMessageClientError(
                    f"Bad Request: {error_data.get('message', 'Invalid request')}",
                    status_code=400
                )
            elif response.status_code == 401:
                raise LoopMessageClientError(
                    "Unauthorized: Invalid authorization key",
                    status_code=401
                )
            elif response.status_code == 402:
                raise LoopMessageClientError(
                    "Payment Required: No available requests/credits",
                    status_code=402
                )
            elif response.status_code == 404:
                raise LoopMessageClientError(
                    "Not Found: Message ID not found or invalid endpoint",
                    status_code=404
                )
            elif response.status_code == 500:
                raise LoopMessageClientError(
                    "Server Error: LoopMessage service unavailable",
                    status_code=500
                )
            elif response.status_code != 200:
                raise LoopMessageClientError(
                    f"HTTP {response.status_code}: {response.text}",
                    status_code=response.status_code
                )
            
            return response.json()
            
        except httpx.RequestError as e:
            if "timeout" in str(e).lower():
                raise LoopMessageClientError("Request timeout - LoopMessage service did not respond in time")
            elif "connection" in str(e).lower():
                raise LoopMessageClientError("Connection error - Unable to reach LoopMessage service")
            else:
                raise LoopMessageClientError(f"Network error: {str(e)}")
        except ValueError as e:
            if "JSON" in str(e):
                raise LoopMessageClientError("Invalid JSON response from LoopMessage service")
            raise LoopMessageClientError(f"Request error: {str(e)}")
        except Exception as e:
            if isinstance(e, LoopMessageClientError):
                raise
            raise LoopMessageClientError(f"Unexpected error: {str(e)}")
    
    @staticmethod
    def get_error_message(error_code: int) -> str:
        """
        Get human-readable error message for LoopMessage error codes.
        
        Args:
            error_code: LoopMessage API error code
            
        Returns:
            Human-readable error message
        """
        error_messages = {
            100: "Bad request",
            110: "Missing credentials in request",
            120: "One or more required parameters are missing",
            125: "Authorization key is invalid or does not exist",
            130: "Secret key is invalid or does not exist",
            140: "No text parameter in request",
            150: "No recipient parameter in request",
            160: "Invalid recipient",
            170: "Invalid recipient email",
            180: "Invalid recipient phone number",
            190: "Phone number is not mobile",
            210: "Sender name not specified in request parameters",
            220: "Invalid sender name",
            230: "Internal error occurred while trying to use the specified sender name",
            240: "Sender name is not activated or unpaid",
            270: "This recipient blocked any type of messages",
            300: "Unable to send this type of message without dedicated sender name",
            330: "You send messages too frequently to recipients you haven't contacted for a long time",
            400: "No available requests/credits on your balance",
            500: "Your account is suspended",
            510: "Your account is blocked",
            530: "Your account is suspended due to debt",
            540: "No active purchased sender name to send message",
            545: "Your sender name has been suspended by Apple",
            550: "Requires a dedicated sender name or need to add this recipient as sandbox contact",
            560: "Unable to send outbound messages until this recipient initiates a conversation with your sender",
            570: "This API request is deprecated and not supported",
            580: "Invalid effect parameter",
            590: "Invalid message_id for reply",
            595: "Invalid or non-existent message_id",
            600: "Invalid reaction parameter",
            610: "Reaction or message_id is invalid or does not exist",
            620: "Unable to use effect and reaction parameters in the same request",
            630: "Need to set up a vCard file for this sender name in the dashboard",
            640: "No media file URL - media_url",
            1110: "Unable to send SMS if the recipient is an email address",
            1120: "Unable to send SMS if the recipient is group",
            1130: "Unable to send SMS with marketing content",
            1140: "Unable to send audio messages through SMS"
        }
        
        return error_messages.get(error_code, f"Unknown error (code: {error_code})")


def create_loopmessage_client(api_key: str, base_url: Optional[str] = None) -> LoopMessageClient:
    """
    Factory function to create a LoopMessage client from API key string.
    
    Args:
        api_key: API key in format 'authorization_key:secret_key'
        base_url: Optional custom base URL
        
    Returns:
        Configured LoopMessage client
        
    Raises:
        ValueError: If API key format is invalid
    """
    if not api_key or ':' not in api_key:
        raise ValueError("Invalid LoopMessage API key format. Expected 'authorization_key:secret_key'")
    
    parts = api_key.split(':', 1)
    if len(parts) != 2:
        raise ValueError("Invalid LoopMessage API key format. Expected 'authorization_key:secret_key'")
    
    authorization_key, secret_key = parts
    
    config = LoopMessageConfig(
        authorization_key=authorization_key,
        secret_key=secret_key,
        base_url=base_url or "https://server.loopmessage.com/api/v1"
    )
    
    return LoopMessageClient(config)
