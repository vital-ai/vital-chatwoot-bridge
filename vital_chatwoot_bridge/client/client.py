"""
Main client class for the Chatwoot Bridge REST API.
"""

from typing import Optional

from vital_chatwoot_bridge.client.auth import KeycloakAuth
from vital_chatwoot_bridge.client.base import BaseClient
from vital_chatwoot_bridge.client.contacts import ContactsMixin
from vital_chatwoot_bridge.client.conversations import ConversationsMixin
from vital_chatwoot_bridge.client.messages import MessagesMixin
from vital_chatwoot_bridge.client.agents import AgentsMixin
from vital_chatwoot_bridge.client.inboxes import InboxesMixin


class ChatwootBridgeClient(
    ContactsMixin,
    ConversationsMixin,
    MessagesMixin,
    AgentsMixin,
    InboxesMixin,
    BaseClient,
):
    """
    Async client for the Vital Chatwoot Bridge REST API.

    Authenticates via Keycloak JWT and provides typed methods for all
    management endpoints (contacts, conversations, messages, agents, inboxes).

    Usage:
        from vital_chatwoot_bridge.client.client import ChatwootBridgeClient

        async with ChatwootBridgeClient(
            base_url="http://localhost:8000",
            keycloak_url="https://keycloak.example.com",
            realm="myrealm",
            client_id="my-client",
            client_secret="secret",
        ) as client:
            contacts = await client.list_contacts(page=1)
            result = await client.post_message(direction="outbound", inbox_id=1, ...)
    """

    def __init__(
        self,
        base_url: str,
        keycloak_url: str,
        realm: str,
        client_id: str,
        client_secret: Optional[str] = None,
        username: Optional[str] = None,
        password: Optional[str] = None,
        timeout: float = 30.0,
    ):
        """
        Args:
            base_url: Bridge service URL (e.g. http://localhost:8000)
            keycloak_url: Keycloak base URL
            realm: Keycloak realm name
            client_id: OAuth2 client ID
            client_secret: OAuth2 client secret (for client_credentials grant)
            username: Username (for password grant)
            password: Password (for password grant)
            timeout: HTTP request timeout in seconds
        """
        auth = KeycloakAuth(
            keycloak_url=keycloak_url,
            realm=realm,
            client_id=client_id,
            client_secret=client_secret,
            username=username,
            password=password,
        )
        super().__init__(base_url=base_url, auth=auth, timeout=timeout)
