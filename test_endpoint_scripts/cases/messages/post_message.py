"""
Test cases for POST /api/v1/chatwoot/messages (post message inbound/outbound).
"""

import time
import uuid
from typing import Dict, List

from vital_chatwoot_bridge.client.client import ChatwootBridgeClient
from vital_chatwoot_bridge.client.exceptions import ValidationError
from test_endpoint_scripts.base import TestResult


async def post_message_cases(client: ChatwootBridgeClient, config: Dict[str, str]) -> List[TestResult]:
    """Run all post_message test cases."""
    results = [
        await _test_post_message_missing_direction(client),
    ]
    if config.get("test_email_recipient"):
        results.append(await _test_post_outbound_email_suppress(client, config))
    if config.get("test_sms_recipient"):
        results.append(await _test_post_outbound_sms_suppress(client, config))
    return results


async def _test_post_message_missing_direction(client: ChatwootBridgeClient) -> TestResult:
    """Post message without direction — should fail validation."""
    name = "post_message_missing_direction"
    start = time.time()
    try:
        await client.post_message(
            direction="",
            contact_identifier="test@example.com",
            message_content="test",
            inbox_id=1,
        )
        duration = (time.time() - start) * 1000
        return TestResult(name, False, 200, duration, error="Expected validation error")
    except (ValidationError, Exception) as e:
        duration = (time.time() - start) * 1000
        sc = getattr(e, "status_code", 0)
        if sc == 422:
            return TestResult(name, True, 422, duration)
        return TestResult(name, False, sc, duration, error=str(e))


async def _test_post_message_missing_inbox(client: ChatwootBridgeClient) -> TestResult:
    """Post message without inbox_type or inbox_id — should fail validation."""
    name = "post_message_missing_inbox"
    start = time.time()
    try:
        await client.post_message(
            direction="outbound",
            contact_identifier="test@example.com",
            message_content="test",
        )
        duration = (time.time() - start) * 1000
        return TestResult(name, False, 200, duration, error="Expected validation error")
    except (ValidationError, Exception) as e:
        duration = (time.time() - start) * 1000
        sc = getattr(e, "status_code", 0)
        if sc == 422:
            return TestResult(name, True, 422, duration)
        return TestResult(name, False, sc, duration, error=str(e))


async def _test_post_outbound_email_suppress(client: ChatwootBridgeClient, config: Dict[str, str]) -> TestResult:
    """Post outbound email with suppress_delivery=True — logs only, no dispatch."""
    name = "post_outbound_email_suppress_delivery"
    email = config["test_email_recipient"]
    contact_name = config.get("test_contact_name", "Test User")
    start = time.time()
    try:
        resp = await client.post_message(
            direction="outbound",
            contact_identifier=email,
            contact_name=contact_name,
            contact_email=email,
            message_content=f"Suppressed test message {uuid.uuid4().hex[:8]}",
            inbox_id=1,
            suppress_delivery=True,
        )
        duration = (time.time() - start) * 1000
        if not resp.success:
            return TestResult(name, False, 201, duration, error="success=false")
        return TestResult(name, True, 201, duration, response_data=resp.data)
    except Exception as e:
        duration = (time.time() - start) * 1000
        return TestResult(name, False, getattr(e, "status_code", 0), duration, error=str(e))


async def _test_post_outbound_sms_suppress(client: ChatwootBridgeClient, config: Dict[str, str]) -> TestResult:
    """Post outbound SMS with suppress_delivery=True — logs only, no dispatch."""
    name = "post_outbound_sms_suppress_delivery"
    phone = config["test_sms_recipient"]
    contact_name = config.get("test_contact_name", "Test User")
    start = time.time()
    try:
        resp = await client.post_message(
            direction="outbound",
            contact_identifier=phone,
            contact_name=contact_name,
            contact_phone=phone,
            message_content=f"Suppressed SMS test {uuid.uuid4().hex[:8]}",
            inbox_id=2,
            suppress_delivery=True,
        )
        duration = (time.time() - start) * 1000
        if not resp.success:
            return TestResult(name, False, 201, duration, error="success=false")
        return TestResult(name, True, 201, duration, response_data=resp.data)
    except Exception as e:
        duration = (time.time() - start) * 1000
        return TestResult(name, False, getattr(e, "status_code", 0), duration, error=str(e))
