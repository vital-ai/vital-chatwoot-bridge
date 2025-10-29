"""
Webhook security utilities for Chatwoot signature verification.
"""

import hmac
import hashlib
import time
import logging
from typing import Optional

logger = logging.getLogger(__name__)


def verify_webhook_signature(
    payload: str,
    signature: Optional[str],
    timestamp: Optional[str],
    webhook_secret: str,
    enforce_signatures: bool = True,
    tolerance: int = 300
) -> bool:
    """
    Verify Chatwoot webhook signature.
    
    Args:
        payload: Raw webhook payload as string
        signature: X-Chatwoot-Signature header value
        timestamp: X-Chatwoot-Timestamp header value
        webhook_secret: Webhook secret from configuration
        enforce_signatures: Whether to enforce signature verification (default True)
        tolerance: Maximum age of webhook in seconds (default 300 = 5 minutes)
    
    Returns:
        bool: True if signature is valid, False otherwise
    """
    # Log signature verification attempt
    logger.info(f"🔐 WEBHOOK_SECURITY: Verifying webhook signature")
    logger.info(f"🔐 WEBHOOK_SECURITY: Signature header: {signature}")
    logger.info(f"🔐 WEBHOOK_SECURITY: Timestamp header: {timestamp}")
    logger.info(f"🔐 WEBHOOK_SECURITY: Payload length: {len(payload)} bytes")
    logger.info(f"🔐 WEBHOOK_SECURITY: Webhook secret configured: {bool(webhook_secret)}")
    logger.info(f"🔐 WEBHOOK_SECURITY: Signature enforcement enabled: {enforce_signatures}")
    
    # Check if signature enforcement is disabled
    if not enforce_signatures:
        logger.warning("🔐 WEBHOOK_SECURITY: Signature enforcement disabled - skipping verification")
        return True  # Allow through if enforcement is disabled
    
    # Check if webhook secret is configured
    if not webhook_secret:
        logger.warning("🔐 WEBHOOK_SECURITY: No webhook secret configured - skipping verification")
        return True  # Allow through if no secret configured (for development)
    
    # Check if signature header is present
    if not signature:
        logger.error("🔐 WEBHOOK_SECURITY: Missing X-Chatwoot-Signature header")
        return False
    
    # Check if timestamp header is present
    if not timestamp:
        logger.error("🔐 WEBHOOK_SECURITY: Missing X-Chatwoot-Timestamp header")
        return False
    
    try:
        # Check timestamp tolerance (prevent replay attacks)
        current_time = int(time.time())
        webhook_time = int(timestamp)
        age = current_time - webhook_time
        
        logger.info(f"🔐 WEBHOOK_SECURITY: Webhook age: {age} seconds (tolerance: {tolerance})")
        
        if age > tolerance:
            logger.error(f"🔐 WEBHOOK_SECURITY: Webhook too old - age {age}s exceeds tolerance {tolerance}s")
            return False
        
        # Generate expected signature
        signature_payload = f"{timestamp}.{payload}"
        expected_signature = hmac.new(
            webhook_secret.encode(),
            signature_payload.encode(),
            hashlib.sha256
        ).hexdigest()
        
        # Extract received signature (remove 'sha256=' prefix if present)
        received_signature = signature.replace('sha256=', '')
        
        logger.info(f"🔐 WEBHOOK_SECURITY: Expected signature: sha256={expected_signature}")
        logger.info(f"🔐 WEBHOOK_SECURITY: Received signature: {signature}")
        
        # Compare signatures using constant-time comparison
        is_valid = hmac.compare_digest(expected_signature, received_signature)
        
        if is_valid:
            logger.info("🔐 WEBHOOK_SECURITY: ✅ Signature verification PASSED")
        else:
            logger.error("🔐 WEBHOOK_SECURITY: ❌ Signature verification FAILED")
        
        return is_valid
        
    except ValueError as e:
        logger.error(f"🔐 WEBHOOK_SECURITY: Invalid timestamp format: {e}")
        return False
    except Exception as e:
        logger.error(f"🔐 WEBHOOK_SECURITY: Signature verification error: {e}")
        return False


def log_webhook_headers(headers: dict) -> None:
    """
    Log all webhook headers for debugging purposes.
    
    Args:
        headers: Dictionary of HTTP headers
    """
    logger.info("🔐 WEBHOOK_SECURITY: All webhook headers:")
    for key, value in headers.items():
        # Mask sensitive headers but show their presence
        if 'signature' in key.lower() or 'secret' in key.lower():
            masked_value = f"{value[:10]}..." if len(value) > 10 else "***"
            logger.info(f"🔐 WEBHOOK_SECURITY:   {key}: {masked_value}")
        else:
            logger.info(f"🔐 WEBHOOK_SECURITY:   {key}: {value}")
