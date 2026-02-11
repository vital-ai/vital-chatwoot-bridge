"""
Test cases for GET /api/v1/chatwoot/conversations/count.
"""

import time
from typing import Dict, List

from vital_chatwoot_bridge.client.client import ChatwootBridgeClient
from test_endpoint_scripts.base import TestResult


async def conversation_count_cases(client: ChatwootBridgeClient, config: Dict[str, str]) -> List[TestResult]:
    """Run all conversation_count test cases."""
    return [
        await _test_conversation_count(client),
    ]


async def _test_conversation_count(client: ChatwootBridgeClient) -> TestResult:
    """Get conversation counts by status and verify structure."""
    name = "conversation_count"
    start = time.time()
    try:
        resp = await client.conversation_count()
        duration = (time.time() - start) * 1000
        if not resp.success:
            return TestResult(name, False, 200, duration, error="success=false")
        data = resp.data
        if not isinstance(data, dict) or "total" not in data:
            return TestResult(name, False, 200, duration, error=f"Missing 'total' key: {data}")
        # Verify expected status keys
        for key in ("open", "resolved", "pending", "total"):
            if key not in data:
                return TestResult(name, False, 200, duration, error=f"Missing '{key}' in counts")
        return TestResult(name, True, 200, duration, response_data=data)
    except Exception as e:
        duration = (time.time() - start) * 1000
        return TestResult(name, False, getattr(e, "status_code", 0), duration, error=str(e))
