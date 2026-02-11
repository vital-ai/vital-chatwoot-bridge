"""
Test cases for GET /api/v1/chatwoot/conversations/{conversation_id}.
"""

import time
from typing import Dict, List

from vital_chatwoot_bridge.client.client import ChatwootBridgeClient
from vital_chatwoot_bridge.client.exceptions import NotFoundError
from test_endpoint_scripts.base import TestResult


async def get_conversation_cases(client: ChatwootBridgeClient, config: Dict[str, str]) -> List[TestResult]:
    """Run all get_conversation test cases."""
    conv_id = await _get_first_conversation_id(client)
    results = [
        await _test_get_conversation_valid(client, conv_id),
        await _test_get_conversation_invalid(client),
    ]
    return results


async def _get_first_conversation_id(client: ChatwootBridgeClient) -> int:
    """Helper: get the ID of the first conversation from list."""
    try:
        resp = await client.list_conversations(page=1)
        if resp.data and len(resp.data) > 0:
            return resp.data[0].get("id", 0)
    except Exception:
        pass
    return 0


async def _test_get_conversation_valid(client: ChatwootBridgeClient, conv_id: int) -> TestResult:
    """Get a valid conversation by ID."""
    name = "get_conversation_valid"
    if not conv_id:
        return TestResult(name, False, 0, 0, error="No conversation ID available from list")
    start = time.time()
    try:
        resp = await client.get_conversation(conv_id)
        duration = (time.time() - start) * 1000
        if not resp.success:
            return TestResult(name, False, 200, duration, error="success=false")
        return TestResult(name, True, 200, duration, response_data={"id": conv_id})
    except Exception as e:
        duration = (time.time() - start) * 1000
        return TestResult(name, False, getattr(e, "status_code", 0), duration, error=str(e))


async def _test_get_conversation_invalid(client: ChatwootBridgeClient) -> TestResult:
    """Get a conversation with an invalid ID — should return 404."""
    name = "get_conversation_invalid_id"
    start = time.time()
    try:
        await client.get_conversation(999999999)
        duration = (time.time() - start) * 1000
        return TestResult(name, False, 200, duration, error="Expected 404 but got success")
    except NotFoundError:
        duration = (time.time() - start) * 1000
        return TestResult(name, True, 404, duration)
    except Exception as e:
        duration = (time.time() - start) * 1000
        return TestResult(name, False, getattr(e, "status_code", 0), duration, error=str(e))
