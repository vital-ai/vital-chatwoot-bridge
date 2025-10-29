"""
JWT authentication utilities for Keycloak integration.
"""

import requests
import json
import base64
import logging
from typing import Optional, Dict, Any
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


class JWTTokenManager:
    """Manages JWT token retrieval and caching from Keycloak."""
    
    def __init__(self, keycloak_base_url: str, realm: str, client_id: str, 
                 client_secret: str, username: str, password: str):
        self.keycloak_base_url = keycloak_base_url
        self.realm = realm
        self.client_id = client_id
        self.client_secret = client_secret
        self.username = username
        self.password = password
        self.token_url = f"{keycloak_base_url}/realms/{realm}/protocol/openid-connect/token"
        
        # Token caching
        self._cached_token = None
        self._token_expires_at = None
    
    def get_keycloak_token(self) -> Optional[str]:
        """
        Get JWT token from Keycloak with caching.
        
        Returns:
            str: Access token if successful, None otherwise
        """
        # Check if we have a valid cached token
        if self._cached_token and self._token_expires_at:
            if datetime.now() < self._token_expires_at - timedelta(minutes=1):  # 1 minute buffer
                logger.info("🔑 JWT: Using cached token")
                return self._cached_token
        
        logger.info("🔑 JWT: Requesting new token from Keycloak")
        
        data = {
            'grant_type': 'password',
            'client_id': self.client_id,
            'username': self.username,
            'password': self.password,
            'scope': 'openid profile email'
        }
        
        if self.client_secret:
            data['client_secret'] = self.client_secret
        
        try:
            logger.info(f"🔑 JWT: Making token request to {self.token_url}")
            logger.info(f"🔑 JWT: Request data - grant_type: {data['grant_type']}, client_id: {data['client_id']}, username: {data['username']}")
            
            response = requests.post(self.token_url, data=data, timeout=10)
            logger.info(f"🔑 JWT: Token response status: {response.status_code}")
            
            if response.status_code != 200:
                logger.error(f"🔑 JWT: Token request failed with status {response.status_code}")
                logger.error(f"🔑 JWT: Response body: {response.text}")
                return None
            
            response.raise_for_status()
            
            token_response = response.json()
            access_token = token_response.get('access_token')
            expires_in = token_response.get('expires_in', 3600)  # Default 1 hour
            
            if access_token:
                # Cache the token
                self._cached_token = access_token
                self._token_expires_at = datetime.now() + timedelta(seconds=expires_in)
                
                logger.info(f"🔑 JWT: Successfully obtained token (expires in {expires_in}s)")
                logger.info(f"🔑 JWT: Token length: {len(access_token)} characters")
                
                # Log token details for debugging
                payload = self._decode_jwt_payload(access_token)
                if payload:
                    logger.info(f"🔑 JWT: Token subject: {payload.get('sub', 'N/A')}")
                    logger.info(f"🔑 JWT: Token username: {payload.get('preferred_username', 'N/A')}")
                    logger.info(f"🔑 JWT: Token issuer: {payload.get('iss', 'N/A')}")
                    logger.info(f"🔑 JWT: Token audience: {payload.get('aud', 'N/A')}")
                
                return access_token
            else:
                logger.error("🔑 JWT: No access token in Keycloak response")
                logger.error(f"🔑 JWT: Full response: {token_response}")
                return None
                
        except requests.exceptions.RequestException as e:
            logger.error(f"🔑 JWT: Error getting token from Keycloak: {e}")
            if hasattr(e, 'response') and e.response is not None:
                logger.error(f"🔑 JWT: Response: {e.response.text}")
            return None
        except Exception as e:
            logger.error(f"🔑 JWT: Unexpected error getting token: {e}")
            return None
    
    def _decode_jwt_payload(self, token: str) -> Optional[Dict[str, Any]]:
        """
        Decode JWT payload (without verification for inspection).
        
        Args:
            token: JWT token string
            
        Returns:
            dict: Decoded payload or None if failed
        """
        try:
            # Split token into parts
            parts = token.split('.')
            if len(parts) != 3:
                return None
            
            # Decode payload (add padding if needed)
            payload = parts[1]
            payload += '=' * (4 - len(payload) % 4)
            decoded = base64.urlsafe_b64decode(payload)
            return json.loads(decoded)
        except Exception as e:
            logger.warning(f"🔑 JWT: Error decoding JWT payload: {e}")
            return None
    
    def is_token_valid(self) -> bool:
        """Check if the cached token is still valid."""
        if not self._cached_token or not self._token_expires_at:
            return False
        return datetime.now() < self._token_expires_at - timedelta(minutes=1)
    
    def clear_cache(self):
        """Clear the token cache."""
        self._cached_token = None
        self._token_expires_at = None
        logger.info("🔑 JWT: Token cache cleared")


def create_jwt_manager_from_config(config) -> Optional[JWTTokenManager]:
    """
    Create JWT token manager from configuration.
    
    Args:
        config: Configuration object with Keycloak settings
        
    Returns:
        JWTTokenManager instance or None if configuration is incomplete
    """
    required_fields = ['keycloak_base_url', 'keycloak_realm', 'keycloak_client_id', 
                      'keycloak_user', 'keycloak_password']
    
    for field in required_fields:
        if not getattr(config, field, None):
            logger.warning(f"🔑 JWT: Missing required Keycloak configuration: {field}")
            return None
    
    return JWTTokenManager(
        keycloak_base_url=config.keycloak_base_url,
        realm=config.keycloak_realm,
        client_id=config.keycloak_client_id,
        client_secret=config.keycloak_client_secret,
        username=config.keycloak_user,
        password=config.keycloak_password
    )
