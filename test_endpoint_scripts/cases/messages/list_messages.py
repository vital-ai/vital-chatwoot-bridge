"""
Test cases for GET /api/v1/chatwoot/conversations/{conversation_id}/messages.
"""

import time
from typing import Dict, List

from vital_chatwoot_bridge.client.client import ChatwootBridgeClient
from test_endpoint_scripts.base import TestResult


async def list_messages_cases(client: ChatwootBridgeClient, config: Dict[str, str]) -> List[TestResult]:
    """Run all list_messages test cases."""
    conv_id = await _get_first_conversation_id(client)
    return [
        await _test_list_messages(client, conv_id),
    ]


async def _get_first_conversation_id(client: ChatwootBridgeClient) -> int:
    try:
        resp = await client.list_conversations(page=1)
        if resp.data and len(resp.data) > 0:
            return resp.data[0].get("id", 0)
    except Exception:
        pass
    return 0


async def _test_list_messages(client: ChatwootBridgeClient, conv_id: int) -> TestResult:
    """List messages for a conversation."""
    name = "list_messages"
    if not conv_id:
        return TestResult(name, False, 0, 0, error="No conversation ID available from list")
    start = time.time()
    try:
        resp = await client.list_messages(conv_id)
        duration = (time.time() - start) * 1000
        if not resp.success:
            return TestResult(name, False, 200, duration, error="success=false")
        msg_count = len(resp.data) if isinstance(resp.data, list) else 0
        return TestResult(name, True, 200, duration, response_data={"conversation_id": conv_id, "count": msg_count})
    except Exception as e:
        duration = (time.time() - start) * 1000
        return TestResult(name, False, getattr(e, "status_code", 0), duration, error=str(e))
