"""
Test cases for POST /api/v1/chatwoot/conversations (create conversation).
Creates a throwaway contact, creates a conversation, verifies it exists, cleans up.
"""

import time
import uuid
from typing import Dict, List

from vital_chatwoot_bridge.client.client import ChatwootBridgeClient
from vital_chatwoot_bridge.client.exceptions import NotFoundError
from test_endpoint_scripts.base import TestResult


async def create_conversation_cases(client: ChatwootBridgeClient, config: Dict[str, str]) -> List[TestResult]:
    """Run all create_conversation test cases."""
    return [
        await _test_create_conversation(client),
    ]


async def _test_create_conversation(client: ChatwootBridgeClient) -> TestResult:
    """Create a contact, create a conversation for it, verify, clean up."""
    name = "create_conversation"
    start = time.time()
    try:
        # Create a throwaway contact
        suffix = uuid.uuid4().hex[:8]
        contact_resp = await client.create_contact(
            name=f"Conv Create Test {suffix}",
            email=f"conv_create_{suffix}@example.com",
        )
        contact = contact_resp.data
        contact_id = (
            contact.get("id")
            or contact.get("payload", {}).get("contact", {}).get("id")
        )
        if not contact_id:
            duration = (time.time() - start) * 1000
            return TestResult(name, False, 0, duration, error="Could not extract contact_id")

        # Get an inbox
        inboxes_resp = await client.list_inboxes()
        inboxes = inboxes_resp.data if isinstance(inboxes_resp.data, list) else []
        if not inboxes:
            duration = (time.time() - start) * 1000
            return TestResult(name, False, 0, duration, error="No inboxes available")
        inbox_id = inboxes[0].get("id")

        # Create conversation
        conv_resp = await client.create_conversation(
            inbox_id=inbox_id,
            contact_id=contact_id,
        )
        duration = (time.time() - start) * 1000

        if not conv_resp.success:
            return TestResult(name, False, 200, duration, error="success=false")

        conv_data = conv_resp.data
        conversation_id = conv_data.get("id")
        if not conversation_id:
            return TestResult(name, False, 200, duration, error="No conversation ID in response")

        # Verify it exists
        get_resp = await client.get_conversation(conversation_id)
        if not get_resp.success:
            return TestResult(name, False, 200, duration, error="Created conversation not found via GET")

        # Clean up
        try:
            await client.delete_conversation(conversation_id)
        except Exception:
            pass
        try:
            await client.delete_contact(contact_id)
        except Exception:
            pass

        return TestResult(
            name, True, 201, duration,
            response_data={"conversation_id": conversation_id, "contact_id": contact_id, "inbox_id": inbox_id},
        )
    except Exception as e:
        duration = (time.time() - start) * 1000
        return TestResult(name, False, getattr(e, "status_code", 0), duration, error=str(e))
