"""
Test case for sending a message via the LoopMessage (iMessage) API inbox.

Requires env vars:
  TEST_LOOPMESSAGE_INBOX_ID  — Chatwoot inbox ID for the LoopMessage API inbox
  TEST_LOOPMESSAGE_PHONE     — Phone number to send the test iMessage to

The test sends an outbound message through POST /messages targeting the
LoopMessage inbox. Chatwoot handles dispatching to the LoopMessage API
integration. The test verifies the bridge + Chatwoot side succeeded.
"""

import time
from typing import Dict, List

from vital_chatwoot_bridge.client.client import ChatwootBridgeClient
from test_endpoint_scripts.base import TestResult


async def send_loopmessage_cases(client: ChatwootBridgeClient, config: Dict[str, str]) -> List[TestResult]:
    """Run LoopMessage send test cases."""
    inbox_id = config.get("test_loopmessage_inbox_id", "")
    phone = config.get("test_loopmessage_phone", "")

    if not inbox_id or not phone:
        return [
            TestResult(
                "send_loopmessage",
                False,
                0,
                0.0,
                error="SKIPPED — set TEST_LOOPMESSAGE_INBOX_ID and TEST_LOOPMESSAGE_PHONE in .env",
            )
        ]

    return [
        await _test_send_loopmessage(client, int(inbox_id), phone),
    ]


async def _test_send_loopmessage(
    client: ChatwootBridgeClient, inbox_id: int, phone: str
) -> TestResult:
    """Send an outbound iMessage via the LoopMessage API inbox."""
    name = "send_loopmessage"
    start = time.time()
    try:
        resp = await client.post_message(
            direction="outbound",
            inbox_id=inbox_id,
            contact_identifier=phone,
            contact_phone=phone,
            contact_name="LoopMessage Test",
            message_content="Test iMessage from vital-chatwoot-bridge",
        )
        duration = (time.time() - start) * 1000

        if not resp.success:
            return TestResult(name, False, 200, duration, error="success=false")

        data = resp.data
        msg_id = data.get("id") or data.get("message_id")
        conv_id = data.get("conversation_id")

        return TestResult(
            name,
            True,
            201,
            duration,
            response_data={"message_id": msg_id, "conversation_id": conv_id},
        )
    except Exception as e:
        duration = (time.time() - start) * 1000
        return TestResult(name, False, getattr(e, "status_code", 0), duration, error=str(e))
