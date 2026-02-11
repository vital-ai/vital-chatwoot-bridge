"""
Test cases for GET /api/v1/chatwoot/contacts (list contacts).
"""

import time
from typing import Dict, List

from vital_chatwoot_bridge.client.client import ChatwootBridgeClient
from test_endpoint_scripts.base import TestResult


async def list_contacts_cases(client: ChatwootBridgeClient, config: Dict[str, str]) -> List[TestResult]:
    """Run all list_contacts test cases."""
    return [
        await _test_list_contacts_page_1(client),
        await _test_list_contacts_page_2(client),
    ]


async def _test_list_contacts_page_1(client: ChatwootBridgeClient) -> TestResult:
    """List contacts page 1 — should return data and pagination meta."""
    name = "list_contacts_page_1"
    start = time.time()
    try:
        resp = await client.list_contacts(page=1)
        duration = (time.time() - start) * 1000

        if not resp.success:
            return TestResult(name, False, 200, duration, error="success=false")

        if not isinstance(resp.data, list):
            return TestResult(name, False, 200, duration, error=f"Expected list, got {type(resp.data).__name__}")

        if resp.meta is None:
            return TestResult(name, False, 200, duration, error="Missing pagination meta")

        return TestResult(name, True, 200, duration, response_data={"count": len(resp.data)})

    except Exception as e:
        duration = (time.time() - start) * 1000
        return TestResult(name, False, getattr(e, "status_code", 0), duration, error=str(e))


async def _test_list_contacts_page_2(client: ChatwootBridgeClient) -> TestResult:
    """List contacts page 2 — should return data (possibly empty)."""
    name = "list_contacts_page_2"
    start = time.time()
    try:
        resp = await client.list_contacts(page=2)
        duration = (time.time() - start) * 1000

        if not resp.success:
            return TestResult(name, False, 200, duration, error="success=false")

        return TestResult(name, True, 200, duration, response_data={"count": len(resp.data)})

    except Exception as e:
        duration = (time.time() - start) * 1000
        return TestResult(name, False, getattr(e, "status_code", 0), duration, error=str(e))
