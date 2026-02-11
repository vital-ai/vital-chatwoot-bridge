"""
Test cases for GET /api/v1/chatwoot/agents.
"""

import time
from typing import Dict, List

from vital_chatwoot_bridge.client.client import ChatwootBridgeClient
from test_endpoint_scripts.base import TestResult


async def list_agents_cases(client: ChatwootBridgeClient, config: Dict[str, str]) -> List[TestResult]:
    """Run all list_agents test cases."""
    return [
        await _test_list_agents(client),
    ]


async def _test_list_agents(client: ChatwootBridgeClient) -> TestResult:
    """List all agents — should return a list."""
    name = "list_agents"
    start = time.time()
    try:
        resp = await client.list_agents()
        duration = (time.time() - start) * 1000
        if not resp.success:
            return TestResult(name, False, 200, duration, error="success=false")
        data = resp.data
        if not isinstance(data, list):
            return TestResult(name, False, 200, duration, error=f"Expected list, got {type(data).__name__}")
        return TestResult(name, True, 200, duration, response_data={"count": len(data)})
    except Exception as e:
        duration = (time.time() - start) * 1000
        return TestResult(name, False, getattr(e, "status_code", 0), duration, error=str(e))
