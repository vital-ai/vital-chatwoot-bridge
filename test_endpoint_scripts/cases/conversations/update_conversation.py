"""
Test cases for POST /api/v1/chatwoot/conversations/{conversation_id} (update conversation).
"""

import time
from typing import Dict, List

from vital_chatwoot_bridge.client.client import ChatwootBridgeClient
from vital_chatwoot_bridge.client.exceptions import NotFoundError
from test_endpoint_scripts.base import TestResult


async def update_conversation_cases(client: ChatwootBridgeClient, config: Dict[str, str]) -> List[TestResult]:
    """Run all update_conversation test cases."""
    return [
        await _test_update_conversation_status(client),
        await _test_update_conversation_invalid_id(client),
    ]


async def _test_update_conversation_status(client: ChatwootBridgeClient) -> TestResult:
    """Find an open conversation, resolve it, then reopen it."""
    name = "update_conversation_status"
    start = time.time()
    try:
        # Find an open conversation
        convs = await client.list_conversations(page=1, status="open")
        conv_list = convs.data if isinstance(convs.data, list) else []
        if not conv_list:
            duration = (time.time() - start) * 1000
            return TestResult(name, False, 0, duration, error="No open conversations available")

        conversation_id = conv_list[0].get("id")

        # Resolve it
        resolve_resp = await client.update_conversation(conversation_id, status="resolved")
        if not resolve_resp.success:
            duration = (time.time() - start) * 1000
            return TestResult(name, False, 200, duration, error="resolve returned success=false")

        # Reopen it
        reopen_resp = await client.update_conversation(conversation_id, status="open")
        duration = (time.time() - start) * 1000

        if not reopen_resp.success:
            return TestResult(name, False, 200, duration, error="reopen returned success=false")

        return TestResult(name, True, 200, duration,
                          response_data={"conversation_id": conversation_id})
    except Exception as e:
        duration = (time.time() - start) * 1000
        return TestResult(name, False, getattr(e, "status_code", 0), duration, error=str(e))


async def _test_update_conversation_invalid_id(client: ChatwootBridgeClient) -> TestResult:
    """Attempt to update a non-existent conversation — expect 404."""
    name = "update_conversation_invalid_id"
    start = time.time()
    try:
        await client.update_conversation(999999999, status="resolved")
        duration = (time.time() - start) * 1000
        return TestResult(name, False, 200, duration, error="Expected 404 but got success")
    except NotFoundError:
        duration = (time.time() - start) * 1000
        return TestResult(name, True, 404, duration)
    except Exception as e:
        duration = (time.time() - start) * 1000
        return TestResult(name, False, getattr(e, "status_code", 0), duration, error=str(e))
