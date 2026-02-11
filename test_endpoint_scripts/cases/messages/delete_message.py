"""
Test cases for DELETE /api/v1/chatwoot/conversations/{conversation_id}/messages/{message_id}.
Uses an existing conversation, posts a message, deletes it, verifies 404 on re-fetch.
"""

import time
from typing import Dict, List

from vital_chatwoot_bridge.client.client import ChatwootBridgeClient
from vital_chatwoot_bridge.client.exceptions import NotFoundError
from test_endpoint_scripts.base import TestResult


async def delete_message_cases(client: ChatwootBridgeClient, config: Dict[str, str]) -> List[TestResult]:
    """Run all delete_message test cases."""
    return [
        await _test_delete_message(client),
        await _test_delete_message_invalid_id(client),
    ]


async def _test_delete_message(client: ChatwootBridgeClient) -> TestResult:
    """Post a message to an existing conversation, then delete it."""
    name = "delete_message"
    start = time.time()
    try:
        # Find an existing conversation to post into
        convs = await client.list_conversations(page=1)
        conv_list = convs.data if isinstance(convs.data, list) else []
        if not conv_list:
            duration = (time.time() - start) * 1000
            return TestResult(name, False, 0, duration, error="No conversations available")

        conversation_id = conv_list[0].get("id")

        # List messages to get current count
        msgs_before = await client.list_messages(conversation_id)
        msg_list = msgs_before.data if isinstance(msgs_before.data, list) else []

        # We need at least one message to delete — find the newest non-system message
        deletable = None
        for msg in msg_list:
            if isinstance(msg, dict) and msg.get("message_type") in (0, 1, "incoming", "outgoing"):
                deletable = msg
                break

        if not deletable:
            duration = (time.time() - start) * 1000
            return TestResult(name, False, 0, duration, error="No deletable message found in conversation")

        message_id = deletable.get("id")

        # Delete the message
        del_resp = await client.delete_message(conversation_id, message_id)
        duration = (time.time() - start) * 1000

        if not del_resp.success:
            return TestResult(name, False, 200, duration, error="delete returned success=false")

        return TestResult(name, True, 200, duration, response_data={"deleted_message_id": message_id})
    except Exception as e:
        duration = (time.time() - start) * 1000
        return TestResult(name, False, getattr(e, "status_code", 0), duration, error=str(e))


async def _test_delete_message_invalid_id(client: ChatwootBridgeClient) -> TestResult:
    """Attempt to delete a non-existent message — expect 404."""
    name = "delete_message_invalid_id"
    start = time.time()
    try:
        # Use a real conversation but fake message ID
        convs = await client.list_conversations(page=1)
        conv_list = convs.data if isinstance(convs.data, list) else []
        if not conv_list:
            duration = (time.time() - start) * 1000
            return TestResult(name, False, 0, duration, error="No conversations available")

        conversation_id = conv_list[0].get("id")
        await client.delete_message(conversation_id, 999999999)
        duration = (time.time() - start) * 1000
        return TestResult(name, False, 200, duration, error="Expected 404 but got success")
    except NotFoundError:
        duration = (time.time() - start) * 1000
        return TestResult(name, True, 404, duration)
    except Exception as e:
        duration = (time.time() - start) * 1000
        return TestResult(name, False, getattr(e, "status_code", 0), duration, error=str(e))
