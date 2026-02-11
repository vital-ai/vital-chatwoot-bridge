"""
Exception classes for the Chatwoot Bridge client library.
"""

from typing import Optional, Dict, Any


class BridgeClientError(Exception):
    """Base exception for all bridge client errors."""

    def __init__(
        self,
        message: str,
        status_code: Optional[int] = None,
        response_data: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(message)
        self.status_code = status_code
        self.response_data = response_data


class AuthenticationError(BridgeClientError):
    """Raised when authentication fails (token acquisition or 401 response)."""
    pass


class NotFoundError(BridgeClientError):
    """Raised when a requested resource is not found (404)."""
    pass


class ValidationError(BridgeClientError):
    """Raised when the server rejects a request due to validation (422)."""
    pass


class ServerError(BridgeClientError):
    """Raised when the bridge server returns a 5xx error."""
    pass
