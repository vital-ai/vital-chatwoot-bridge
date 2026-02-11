"""
Test cases for GET /api/v1/chatwoot/account/summary.
"""

import time
from typing import Dict, List

from vital_chatwoot_bridge.client.client import ChatwootBridgeClient
from test_endpoint_scripts.base import TestResult


async def account_summary_cases(client: ChatwootBridgeClient, config: Dict[str, str]) -> List[TestResult]:
    """Run all account_summary test cases."""
    return [
        await _test_account_summary(client),
    ]


async def _test_account_summary(client: ChatwootBridgeClient) -> TestResult:
    """Get account summary and verify it has all expected sections."""
    name = "account_summary"
    start = time.time()
    try:
        resp = await client.account_summary()
        duration = (time.time() - start) * 1000
        if not resp.success:
            return TestResult(name, False, 200, duration, error="success=false")
        data = resp.data
        if not isinstance(data, dict):
            return TestResult(name, False, 200, duration, error=f"Expected dict, got {type(data)}")
        for key in ("contacts", "conversations", "agents", "inboxes"):
            if key not in data:
                return TestResult(name, False, 200, duration, error=f"Missing '{key}' in summary")
        return TestResult(name, True, 200, duration, response_data=data)
    except Exception as e:
        duration = (time.time() - start) * 1000
        return TestResult(name, False, getattr(e, "status_code", 0), duration, error=str(e))
