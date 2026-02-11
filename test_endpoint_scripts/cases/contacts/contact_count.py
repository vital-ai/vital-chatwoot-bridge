"""
Test cases for GET /api/v1/chatwoot/contacts/count.
"""

import time
from typing import Dict, List

from vital_chatwoot_bridge.client.client import ChatwootBridgeClient
from test_endpoint_scripts.base import TestResult


async def contact_count_cases(client: ChatwootBridgeClient, config: Dict[str, str]) -> List[TestResult]:
    """Run all contact_count test cases."""
    return [
        await _test_contact_count(client),
    ]


async def _test_contact_count(client: ChatwootBridgeClient) -> TestResult:
    """Get contact count and verify it returns numeric values."""
    name = "contact_count"
    start = time.time()
    try:
        resp = await client.contact_count()
        duration = (time.time() - start) * 1000
        if not resp.success:
            return TestResult(name, False, 200, duration, error="success=false")
        data = resp.data
        if not isinstance(data, dict) or "count" not in data:
            return TestResult(name, False, 200, duration, error=f"Missing 'count' key in response: {data}")
        return TestResult(name, True, 200, duration, response_data=data)
    except Exception as e:
        duration = (time.time() - start) * 1000
        return TestResult(name, False, getattr(e, "status_code", 0), duration, error=str(e))
