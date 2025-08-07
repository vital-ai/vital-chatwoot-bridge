"""
Configuration settings for the Vital Chatwoot Bridge application.
"""

import os
import json
import logging
from typing import List, Optional
from functools import lru_cache
from pydantic import BaseModel, Field

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


class Config:
    """Simple configuration class that reads from environment variables."""
    
    def __init__(self):
        # Application settings
        self.app_name = "Vital Chatwoot Bridge"
        self.debug = os.getenv('DEBUG', 'false').lower() == 'true'
        self.host = os.getenv('HOST', '0.0.0.0')
        self.port = int(os.getenv('PORT', '8000'))
        
        # CORS settings
        self.allowed_origins = ["*"]
        
        # Chatwoot API Configuration
        self.chatwoot_base_url = os.getenv('CHATWOOT_BASE_URL', '')
        self.chatwoot_api_access_token = os.getenv('CHATWOOT_API_ACCESS_TOKEN', '')
        self.chatwoot_account_id = int(os.getenv('CHATWOOT_ACCOUNT_ID', '1'))
        
        # Response Configuration
        self.default_response_timeout = int(os.getenv('DEFAULT_RESPONSE_TIMEOUT', '30'))
        self.max_sync_response_time = int(os.getenv('MAX_SYNC_RESPONSE_TIME', '25'))
        
        # WebSocket Configuration
        self.websocket_connect_timeout = int(os.getenv('WEBSOCKET_CONNECT_TIMEOUT', '10'))
        self.websocket_ping_interval = int(os.getenv('WEBSOCKET_PING_INTERVAL', '30'))
        self.websocket_ping_timeout = int(os.getenv('WEBSOCKET_PING_TIMEOUT', '10'))
        self.websocket_max_reconnect_attempts = int(os.getenv('WEBSOCKET_MAX_RECONNECT_ATTEMPTS', '5'))
        
        # Parse inbox agent mappings from JSON
        self.inbox_agent_mappings = self._parse_inbox_mappings()
    
    def _parse_inbox_mappings(self) -> List[InboxMapping]:
        """Parse inbox mappings from JSON environment variable."""
        mappings_json = os.getenv('INBOX_AGENT_MAPPINGS', '[]')
        logger.info(f"📋 CONFIG: Loading INBOX_AGENT_MAPPINGS: {mappings_json[:100]}..." if len(mappings_json) > 100 else f"📋 CONFIG: Loading INBOX_AGENT_MAPPINGS: {mappings_json}")
        try:
            mappings_data = json.loads(mappings_json)
            logger.info(f"📋 CONFIG: Parsed {len(mappings_data)} inbox mappings from JSON")
            mappings = [InboxMapping(**mapping) for mapping in mappings_data]
            logger.info(f"📋 CONFIG: Created {len(mappings)} InboxMapping objects successfully")
            return mappings
        except (json.JSONDecodeError, ValueError) as e:
            logger.error(f"❌ CONFIG: Failed to parse INBOX_AGENT_MAPPINGS JSON: {e}")
            return []
    
    def get_agent_for_inbox(self, inbox_id: str) -> Optional[AgentConfig]:
        """Get the AI agent configuration for a specific inbox."""
        for mapping in self.inbox_agent_mappings:
            if mapping.inbox_id == inbox_id:
                return mapping.agent_config
        return None
    

@lru_cache()
def get_settings() -> Config:
    """Get cached application settings."""
    return Config()
