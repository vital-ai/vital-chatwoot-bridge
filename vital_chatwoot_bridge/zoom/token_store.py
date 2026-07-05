"""
Token persistence for Zoom OAuth tokens via AWS Secrets Manager.

Each Zoom user account gets its own secret containing the current
access_token + refresh_token pair. Atomic writes are critical because
Zoom rotates the refresh token on every refresh call.
"""

import json
import logging
import time
from typing import Optional

import boto3
from botocore.exceptions import ClientError

from vital_chatwoot_bridge.zoom.models import ZoomTokenPair, ZoomTokenStorageConfig

logger = logging.getLogger(__name__)


class ZoomTokenStore:
    """
    Persists Zoom OAuth token pairs in AWS Secrets Manager.

    Each account's tokens are stored as a JSON secret at:
        {secret_prefix}{account_name}
    """

    def __init__(self, config: ZoomTokenStorageConfig, region: str = "us-east-1"):
        self.config = config
        self._client = boto3.client("secretsmanager", region_name=region)

    def _secret_id(self, account_name: str) -> str:
        """Build the full secret ID for an account."""
        return f"{self.config.secret_prefix}{account_name}"

    def get_token(self, account_name: str) -> Optional[ZoomTokenPair]:
        """
        Retrieve the current token pair for an account.
        Returns None if the secret doesn't exist yet (account not yet authorized).
        """
        secret_id = self._secret_id(account_name)
        try:
            response = self._client.get_secret_value(SecretId=secret_id)
            data = json.loads(response["SecretString"])
            return ZoomTokenPair(**data)
        except ClientError as e:
            error_code = e.response["Error"]["Code"]
            if error_code == "ResourceNotFoundException":
                logger.info(f"No token found for Zoom account '{account_name}' — needs authorization")
                return None
            logger.error(f"Failed to get token for '{account_name}': {e}")
            raise
        except Exception as e:
            logger.error(f"Failed to parse token for '{account_name}': {e}")
            return None

    def store_token(self, account_name: str, token: ZoomTokenPair) -> None:
        """
        Atomically store a new token pair for an account.

        CRITICAL: This must succeed before the token is used. If this fails
        after a refresh, the old refresh token is already invalidated and
        the account is bricked until manual re-auth.
        """
        secret_id = self._secret_id(account_name)
        secret_value = token.model_dump_json()

        try:
            self._client.put_secret_value(
                SecretId=secret_id,
                SecretString=secret_value,
            )
            logger.info(
                f"🔐 Stored token for Zoom account '{account_name}' "
                f"(expires_at={token.expires_at})"
            )
        except ClientError as e:
            error_code = e.response["Error"]["Code"]
            if error_code == "ResourceNotFoundException":
                # Secret doesn't exist yet — create it
                self._client.create_secret(
                    Name=secret_id,
                    SecretString=secret_value,
                    Description=f"Zoom OAuth tokens for account: {account_name}",
                )
                logger.info(f"🔐 Created new secret for Zoom account '{account_name}'")
            else:
                logger.error(f"❌ CRITICAL: Failed to store token for '{account_name}': {e}")
                raise

    def delete_token(self, account_name: str) -> None:
        """Remove stored tokens for an account (e.g., on deauthorization)."""
        secret_id = self._secret_id(account_name)
        try:
            self._client.delete_secret(
                SecretId=secret_id,
                ForceDeleteWithoutRecovery=True,
            )
            logger.info(f"🗑️ Deleted token for Zoom account '{account_name}'")
        except ClientError as e:
            error_code = e.response["Error"]["Code"]
            if error_code == "ResourceNotFoundException":
                pass  # Already gone
            else:
                logger.error(f"Failed to delete token for '{account_name}': {e}")
                raise

    def is_token_expired(self, token: ZoomTokenPair, buffer_minutes: int = 15) -> bool:
        """Check if the access token is expired or will expire within buffer_minutes."""
        buffer_seconds = buffer_minutes * 60
        return time.time() >= (token.expires_at - buffer_seconds)

    def list_accounts_with_tokens(self) -> list[str]:
        """List all account names that have stored tokens."""
        prefix = self.config.secret_prefix
        account_names = []
        try:
            paginator = self._client.get_paginator("list_secrets")
            for page in paginator.paginate(
                Filters=[{"Key": "name", "Values": [prefix]}]
            ):
                for secret in page.get("SecretList", []):
                    name = secret["Name"]
                    if name.startswith(prefix):
                        account_name = name[len(prefix):]
                        account_names.append(account_name)
        except ClientError as e:
            logger.error(f"Failed to list Zoom token secrets: {e}")
        return account_names
