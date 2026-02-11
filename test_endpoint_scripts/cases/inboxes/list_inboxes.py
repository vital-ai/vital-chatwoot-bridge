"""
Test cases for GET /api/v1/chatwoot/inboxes.
"""

import time
from typing import Dict, List

from vital_chatwoot_bridge.client.client import ChatwootBridgeClient
from test_endpoint_scripts.base import TestResult


async def list_inboxes_cases(client: ChatwootBridgeClient, config: Dict[str, str]) -> List[TestResult]:
    """Run all list_inboxes test cases."""
    return [
        await _test_list_inboxes(client),
        await _test_list_inboxes_has_fields(client),
    ]


async def _test_list_inboxes(client: ChatwootBridgeClient) -> TestResult:
    """List all inboxes — should return a list."""
    name = "list_inboxes"
    start = time.time()
    try:
        resp = await client.list_inboxes()
        duration = (time.time() - start) * 1000
        if not resp.success:
            return TestResult(name, False, 200, duration, error="success=false")
        data = resp.data
        if not isinstance(data, list):
            return TestResult(name, False, 200, duration, error=f"Expected list, got {type(data).__name__}")
        inbox_list = [
            {"id": i.get("id"), "name": i.get("name"), "channel_type": i.get("channel_type")}
            for i in data
        ]
        return TestResult(name, True, 200, duration, response_data={"count": len(data), "inboxes": inbox_list})
    except Exception as e:
        duration = (time.time() - start) * 1000
        return TestResult(name, False, getattr(e, "status_code", 0), duration, error=str(e))


async def _test_list_inboxes_has_fields(client: ChatwootBridgeClient) -> TestResult:
    """Verify inboxes have expected fields (id, name, channel_type)."""
    name = "list_inboxes_has_fields"
    start = time.time()
    try:
        resp = await client.list_inboxes()
        duration = (time.time() - start) * 1000
        if not resp.success or not isinstance(resp.data, list):
            return TestResult(name, False, 200, duration, error="No data")
        if len(resp.data) == 0:
            return TestResult(name, False, 200, duration, error="No inboxes returned")
        first = resp.data[0]
        required = ["id", "name", "channel_type"]
        missing = [f for f in required if f not in first]
        if missing:
            return TestResult(name, False, 200, duration, error=f"Missing fields: {missing}")
        return TestResult(name, True, 200, duration, response_data={"first_inbox": first.get("name")})
    except Exception as e:
        duration = (time.time() - start) * 1000
        return TestResult(name, False, getattr(e, "status_code", 0), duration, error=str(e))
