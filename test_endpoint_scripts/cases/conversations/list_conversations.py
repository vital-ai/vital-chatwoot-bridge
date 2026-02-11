"""
Test cases for GET /api/v1/chatwoot/conversations (list conversations).
"""

import time
from typing import Dict, List

from vital_chatwoot_bridge.client.client import ChatwootBridgeClient
from test_endpoint_scripts.base import TestResult


async def list_conversations_cases(client: ChatwootBridgeClient, config: Dict[str, str]) -> List[TestResult]:
    """Run all list_conversations test cases."""
    return [
        await _test_list_conversations_default(client),
        await _test_list_conversations_by_status(client, "open"),
        await _test_list_conversations_by_status(client, "resolved"),
    ]


async def _test_list_conversations_default(client: ChatwootBridgeClient) -> TestResult:
    """List conversations page 1, no filters."""
    name = "list_conversations_default"
    start = time.time()
    try:
        resp = await client.list_conversations(page=1)
        duration = (time.time() - start) * 1000
        if not resp.success:
            return TestResult(name, False, 200, duration, error="success=false")
        if not isinstance(resp.data, list):
            return TestResult(name, False, 200, duration, error=f"Expected list, got {type(resp.data).__name__}")
        return TestResult(name, True, 200, duration, response_data={"count": len(resp.data)})
    except Exception as e:
        duration = (time.time() - start) * 1000
        return TestResult(name, False, getattr(e, "status_code", 0), duration, error=str(e))


async def _test_list_conversations_by_status(client: ChatwootBridgeClient, status: str) -> TestResult:
    """List conversations filtered by status."""
    name = f"list_conversations_status_{status}"
    start = time.time()
    try:
        resp = await client.list_conversations(page=1, status=status)
        duration = (time.time() - start) * 1000
        if not resp.success:
            return TestResult(name, False, 200, duration, error="success=false")
        return TestResult(name, True, 200, duration, response_data={"count": len(resp.data) if isinstance(resp.data, list) else 0})
    except Exception as e:
        duration = (time.time() - start) * 1000
        return TestResult(name, False, getattr(e, "status_code", 0), duration, error=str(e))
