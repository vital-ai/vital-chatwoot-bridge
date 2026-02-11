"""
Configuration settings for the Vital Chatwoot Bridge application.
"""

import os
import logging
from typing import List, Optional, Dict, Any
from functools import lru_cache
from pydantic import BaseModel, Field

from vital_chatwoot_bridge.utils.env_parser import parse_env_tree, coerce_dict

logger = logging.getLogger(__name__)


class AgentConfig(BaseModel):
    """Configuration for an AI agent."""
    agent_id: str = Field(..., description="Unique identifier for the AI agent")
    websocket_url: str = Field(..., description="WebSocket URL for the AI agent")
    timeout_seconds: int = Field(default=30, description="Response timeout in seconds")
    behavior: str = Field(default="default", description="Agent behavior mode (for mock agents)")


class InboxMapping(BaseModel):
    """Mapping between Chatwoot inbox and AI agent."""
    inbox_id: str = Field(..., description="Chatwoot inbox identifier as string")
    agent_config: AgentConfig = Field(..., description="AI agent configuration")


class APIInboxConfig(BaseModel):
    """Configuration for an API inbox."""
    inbox_identifier: str = Field(..., description="API inbox identifier from Chatwoot")
    chatwoot_inbox_id: Optional[str] = Field(None, description="Internal Chatwoot inbox ID for webhook mapping")
    name: str = Field(..., description="Human-readable inbox name")
    message_types: List[str] = Field(..., description="Supported message types (email, sms, imessage)")
    contact_identifier_field: str = Field(..., description="Field to use for contact identification")
    supports_outbound: bool = Field(default=False, description="Whether outbound messages are supported")
    outbound_webhook_url: Optional[str] = Field(None, description="URL for outbound message delivery")
    webhook_events: Optional[Dict[str, str]] = Field(None, description="Supported webhook events and their directions")
    supports_email_replies: bool = Field(default=False, description="Whether email replies are supported outside webhooks")
    description: Optional[str] = Field(None, description="Inbox description")
    hmac_secret: Optional[str] = Field(None, description="HMAC secret for webhook verification")


class Config:
    """Simple configuration class that reads from environment variables."""
    
    def __init__(self):
        # Application settings
        self.app_name = "Vital Chatwoot Bridge"
        self.debug = os.getenv('DEBUG', 'false').lower() == 'true'
        self.host = os.getenv('HOST', '0.0.0.0')
        self.port = int(os.getenv('PORT', '8000'))
        
        # CORS settings (comma-separated origins, default "*")
        cors_env = os.getenv('CORS_ALLOWED_ORIGINS', '*')
        self.allowed_origins = [o.strip() for o in cors_env.split(',')]
        
        # Chatwoot API Configuration
        self.chatwoot_base_url = os.getenv('CHATWOOT_BASE_URL', '')
        self.chatwoot_api_access_token = os.getenv('CHATWOOT_API_ACCESS_TOKEN', '')  # Deprecated - kept for backward compatibility
        self.chatwoot_user_access_token = os.getenv('CHATWOOT_USER_ACCESS_TOKEN', '')  # Main API access token
        self.chatwoot_account_id = os.getenv('CHATWOOT_ACCOUNT_ID', '1')
        self.chatwoot_bot_webhook_secret = os.getenv('CHATWOOT_BOT_WEBHOOK_SECRET', '')  # Still needed for webhook security
        self.enforce_webhook_signatures = os.getenv('ENFORCE_WEBHOOK_SIGNATURES', 'true').lower() == 'true'
        
        # Chatwoot Client API Configuration (for API inboxes)
        self.chatwoot_client_api_base_url = os.getenv('CHATWOOT_CLIENT_API_BASE_URL', 
                                                     f"{self.chatwoot_base_url.rstrip('/')}/public/api/v1" if self.chatwoot_base_url else '')
        
        # LoopMessage API Configuration
        self.loopmessage_api_url = os.getenv('LOOPMESSAGE_API_URL', 'https://server.loopmessage.com/api/v1')
        self.loopmessage_authorization_key = os.getenv('LOOPMESSAGE_AUTHORIZATION_KEY', '')
        self.loopmessage_secret_key = os.getenv('LOOPMESSAGE_SECRET_KEY', '')
        self.loopmessage_sender_name = os.getenv('LOOPMESSAGE_SENDER_NAME', '')
        
        # Keycloak Configuration for JWT tokens
        self.keycloak_realm = os.getenv('KEYCLOAK_REALM', '')
        self.keycloak_client_id = os.getenv('KEYCLOAK_CLIENT_ID', '')
        self.keycloak_client_secret = os.getenv('KEYCLOAK_CLIENT_SECRET', '')
        self.keycloak_user = os.getenv('KEYCLOAK_USER', '')
        self.keycloak_password = os.getenv('KEYCLOAK_PASSWORD', '')
        self.keycloak_base_url = os.getenv('KEYCLOAK_BASE_URL', 'http://localhost:8085')
        
        # Response Configuration
        self.default_response_timeout = int(os.getenv('DEFAULT_RESPONSE_TIMEOUT', '30'))
        self.max_sync_response_time = int(os.getenv('MAX_SYNC_RESPONSE_TIME', '25'))
        
        # WebSocket Configuration
        self.websocket_connect_timeout = int(os.getenv('WEBSOCKET_CONNECT_TIMEOUT', '10'))
        self.websocket_ping_interval = int(os.getenv('WEBSOCKET_PING_INTERVAL', '30'))
        self.websocket_ping_timeout = int(os.getenv('WEBSOCKET_PING_TIMEOUT', '10'))
        self.websocket_max_reconnect_attempts = int(os.getenv('WEBSOCKET_MAX_RECONNECT_ATTEMPTS', '5'))
        
        # Parse hierarchical config from CW_BRIDGE__* env vars
        env_tree = parse_env_tree("CW_BRIDGE")
        self.inbox_agent_mappings = self._parse_inbox_agents(env_tree.get("inbox_agents", {}))
        self.api_inboxes = self._parse_api_inboxes(env_tree.get("api_inboxes", {}))
    
    @staticmethod
    def _parse_inbox_agents(agents_tree: Dict[str, Any]) -> List[InboxMapping]:
        """Build InboxMapping list from CW_BRIDGE__inbox_agents__<id>__* env vars."""
        mappings: List[InboxMapping] = []
        for inbox_id, fields in agents_tree.items():
            if not isinstance(fields, dict):
                continue
            try:
                agent_fields = coerce_dict(fields)
                agent_config = AgentConfig(**agent_fields)
                mappings.append(InboxMapping(inbox_id=inbox_id, agent_config=agent_config))
                logger.info(f"📋 CONFIG: Loaded inbox agent mapping: inbox {inbox_id} → {agent_config.agent_id}")
            except Exception as e:
                logger.error(f"❌ CONFIG: Failed to parse inbox agent mapping for inbox {inbox_id}: {e}")
        logger.info(f"📋 CONFIG: {len(mappings)} inbox agent mappings loaded")
        return mappings
    
    @staticmethod
    def _parse_api_inboxes(inboxes_tree: Dict[str, Any]) -> Dict[str, APIInboxConfig]:
        """Build APIInboxConfig dict from CW_BRIDGE__api_inboxes__<type>__* env vars."""
        api_inboxes: Dict[str, APIInboxConfig] = {}
        for inbox_type, fields in inboxes_tree.items():
            if not isinstance(fields, dict):
                continue
            try:
                prepared = dict(fields)
                # Handle comma-separated list fields
                if "message_types" in prepared and isinstance(prepared["message_types"], str):
                    prepared["message_types"] = [t.strip() for t in prepared["message_types"].split(",")]
                # Handle boolean fields (Pydantic strict mode won't coerce strings)
                for bool_field in ("supports_outbound", "supports_email_replies"):
                    if bool_field in prepared and isinstance(prepared[bool_field], str):
                        prepared[bool_field] = prepared[bool_field].lower() == "true"
                api_inboxes[inbox_type] = APIInboxConfig(**prepared)
                logger.info(f"📋 CONFIG: Loaded API inbox '{inbox_type}': {prepared.get('name', 'Unknown')}")
            except Exception as e:
                logger.error(f"❌ CONFIG: Failed to parse API inbox config for '{inbox_type}': {e}")
        logger.info(f"📋 CONFIG: {len(api_inboxes)} API inbox configurations loaded")
        return api_inboxes
    
    def get_agent_for_inbox(self, inbox_id: str) -> Optional[AgentConfig]:
        """Get the AI agent configuration for a specific inbox."""
        for mapping in self.inbox_agent_mappings:
            if mapping.inbox_id == inbox_id:
                return mapping.agent_config
        return None
    
    def get_api_inbox_config(self, inbox_type: str) -> Optional[APIInboxConfig]:
        """Get the API inbox configuration for a specific inbox type."""
        return self.api_inboxes.get(inbox_type)
    
    def get_api_inbox_by_identifier(self, inbox_identifier: str) -> Optional[APIInboxConfig]:
        """Get the API inbox configuration by Chatwoot inbox identifier."""
        for config in self.api_inboxes.values():
            if config.inbox_identifier == inbox_identifier:
                return config
        return None
    
    def get_api_inbox_by_chatwoot_id(self, chatwoot_inbox_id: str) -> Optional[APIInboxConfig]:
        """Get the API inbox configuration by Chatwoot internal inbox ID."""
        for config in self.api_inboxes.values():
            if config.chatwoot_inbox_id == chatwoot_inbox_id:
                return config
        return None
    

@lru_cache()
def get_settings() -> Config:
    """Get cached application settings."""
    return Config()
