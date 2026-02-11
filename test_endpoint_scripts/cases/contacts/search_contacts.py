"""
Test cases for GET /api/v1/chatwoot/contacts/search.
"""

import time
from typing import Dict, List

from vital_chatwoot_bridge.client.client import ChatwootBridgeClient
from vital_chatwoot_bridge.client.exceptions import BridgeClientError
from test_endpoint_scripts.base import TestResult


async def search_contacts_cases(client: ChatwootBridgeClient, config: Dict[str, str]) -> List[TestResult]:
    """Run all search_contacts test cases."""
    results = [
        await _test_search_by_email(client, config),
        await _test_search_no_results(client),
    ]
    if config.get("test_sms_recipient"):
        results.append(await _test_search_by_phone(client, config))
    return results


async def _test_search_by_email(client: ChatwootBridgeClient, config: Dict[str, str]) -> TestResult:
    """Search contacts by email — should return results if contact exists."""
    name = "search_contacts_by_email"
    email = config.get("test_email_recipient", "test@example.com")
    start = time.time()
    try:
        resp = await client.search_contacts(q=email)
        duration = (time.time() - start) * 1000
        if not resp.success:
            return TestResult(name, False, 200, duration, error="success=false")
        return TestResult(name, True, 200, duration, response_data={"count": len(resp.data)})
    except Exception as e:
        duration = (time.time() - start) * 1000
        return TestResult(name, False, getattr(e, "status_code", 0), duration, error=str(e))


async def _test_search_by_phone(client: ChatwootBridgeClient, config: Dict[str, str]) -> TestResult:
    """Search contacts by phone number."""
    name = "search_contacts_by_phone"
    phone = config.get("test_sms_recipient", "")
    start = time.time()
    try:
        resp = await client.search_contacts(q=phone)
        duration = (time.time() - start) * 1000
        if not resp.success:
            return TestResult(name, False, 200, duration, error="success=false")
        return TestResult(name, True, 200, duration, response_data={"count": len(resp.data)})
    except Exception as e:
        duration = (time.time() - start) * 1000
        return TestResult(name, False, getattr(e, "status_code", 0), duration, error=str(e))


async def _test_search_no_results(client: ChatwootBridgeClient) -> TestResult:
    """Search with a query that should return no results."""
    name = "search_contacts_no_results"
    start = time.time()
    try:
        resp = await client.search_contacts(q="zzz_nonexistent_query_12345")
        duration = (time.time() - start) * 1000
        if not resp.success:
            return TestResult(name, False, 200, duration, error="success=false")
        if not isinstance(resp.data, list):
            return TestResult(name, False, 200, duration, error=f"Expected list, got {type(resp.data).__name__}")
        return TestResult(name, True, 200, duration, response_data={"count": len(resp.data)})
    except Exception as e:
        duration = (time.time() - start) * 1000
        return TestResult(name, False, getattr(e, "status_code", 0), duration, error=str(e))
