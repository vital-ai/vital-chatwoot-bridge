"""
Test cases for GET /api/v1/chatwoot/contacts/{contact_id} and
GET /api/v1/chatwoot/contacts/{contact_id}/conversations.
"""

import time
from typing import Dict, List

from vital_chatwoot_bridge.client.client import ChatwootBridgeClient
from vital_chatwoot_bridge.client.exceptions import NotFoundError
from test_endpoint_scripts.base import TestResult


async def get_contact_cases(client: ChatwootBridgeClient, config: Dict[str, str]) -> List[TestResult]:
    """Run all get_contact test cases."""
    # First, get a valid contact_id from list
    contact_id = await _get_first_contact_id(client)
    results = [
        await _test_get_contact_valid(client, contact_id),
        await _test_get_contact_invalid(client),
    ]
    if contact_id:
        results.append(await _test_get_contact_conversations(client, contact_id))
    return results


async def _get_first_contact_id(client: ChatwootBridgeClient) -> int:
    """Helper: get the ID of the first contact from list."""
    try:
        resp = await client.list_contacts(page=1)
        if resp.data and len(resp.data) > 0:
            return resp.data[0].get("id", 0)
    except Exception:
        pass
    return 0


async def _test_get_contact_valid(client: ChatwootBridgeClient, contact_id: int) -> TestResult:
    """Get a valid contact by ID."""
    name = "get_contact_valid"
    if not contact_id:
        return TestResult(name, False, 0, 0, error="No contact ID available from list")
    start = time.time()
    try:
        resp = await client.get_contact(contact_id)
        duration = (time.time() - start) * 1000
        if not resp.success:
            return TestResult(name, False, 200, duration, error="success=false")
        data = resp.data
        if not isinstance(data, dict):
            return TestResult(name, False, 200, duration, error=f"Expected dict, got {type(data).__name__}")
        return TestResult(name, True, 200, duration, response_data={"id": data.get("id"), "name": data.get("name")})
    except Exception as e:
        duration = (time.time() - start) * 1000
        return TestResult(name, False, getattr(e, "status_code", 0), duration, error=str(e))


async def _test_get_contact_invalid(client: ChatwootBridgeClient) -> TestResult:
    """Get a contact with an invalid ID — should return 404."""
    name = "get_contact_invalid_id"
    start = time.time()
    try:
        await client.get_contact(999999999)
        duration = (time.time() - start) * 1000
        return TestResult(name, False, 200, duration, error="Expected 404 but got success")
    except NotFoundError:
        duration = (time.time() - start) * 1000
        return TestResult(name, True, 404, duration)
    except Exception as e:
        duration = (time.time() - start) * 1000
        return TestResult(name, False, getattr(e, "status_code", 0), duration, error=str(e))


async def _test_get_contact_conversations(client: ChatwootBridgeClient, contact_id: int) -> TestResult:
    """Get conversations for a valid contact."""
    name = "get_contact_conversations"
    start = time.time()
    try:
        resp = await client.get_contact_conversations(contact_id)
        duration = (time.time() - start) * 1000
        if not resp.success:
            return TestResult(name, False, 200, duration, error="success=false")
        return TestResult(name, True, 200, duration, response_data={"count": len(resp.data) if isinstance(resp.data, list) else 0})
    except Exception as e:
        duration = (time.time() - start) * 1000
        return TestResult(name, False, getattr(e, "status_code", 0), duration, error=str(e))
