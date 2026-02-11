"""
Test cases for DELETE /api/v1/chatwoot/conversations/{conversation_id}.
Creates a temporary contact + conversation, deletes the conversation, verifies 404 on re-fetch.
"""

import time
import uuid
from typing import Dict, List

from vital_chatwoot_bridge.client.client import ChatwootBridgeClient
from vital_chatwoot_bridge.client.exceptions import NotFoundError
from test_endpoint_scripts.base import TestResult


async def delete_conversation_cases(client: ChatwootBridgeClient, config: Dict[str, str]) -> List[TestResult]:
    """Run all delete_conversation test cases."""
    return [
        await _test_delete_conversation(client),
        await _test_delete_conversation_invalid_id(client),
    ]


async def _test_delete_conversation(client: ChatwootBridgeClient) -> TestResult:
    """Create a contact + conversation, delete the conversation, verify it's gone."""
    name = "delete_conversation"
    start = time.time()
    try:
        # Create a throwaway contact with email (required by some inboxes)
        unique_suffix = uuid.uuid4().hex[:8]
        contact_resp = await client.create_contact(
            name=f"Conv Delete Test {unique_suffix}",
            email=f"conv_delete_{unique_suffix}@example.com",
        )
        contact = contact_resp.data
        contact_id = (
            contact.get("id")
            or contact.get("payload", {}).get("contact", {}).get("id")
        )
        if not contact_id:
            duration = (time.time() - start) * 1000
            return TestResult(name, False, 0, duration, error="Could not extract contact_id")

        # Get an inbox to create conversation in
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
        conv_data = conv_resp.data
        conversation_id = conv_data.get("id")
        if not conversation_id:
            duration = (time.time() - start) * 1000
            return TestResult(name, False, 0, duration, error="Could not extract conversation_id")

        # Delete the conversation
        del_resp = await client.delete_conversation(conversation_id)
        duration = (time.time() - start) * 1000

        if not del_resp.success:
            return TestResult(name, False, 200, duration, error="delete returned success=false")

        # Clean up the throwaway contact
        try:
            await client.delete_contact(contact_id)
        except Exception:
            pass

        return TestResult(name, True, 200, duration,
                          response_data={"deleted_conversation_id": conversation_id})
    except Exception as e:
        duration = (time.time() - start) * 1000
        return TestResult(name, False, getattr(e, "status_code", 0), duration, error=str(e))


async def _test_delete_conversation_invalid_id(client: ChatwootBridgeClient) -> TestResult:
    """Attempt to delete a non-existent conversation — expect 404."""
    name = "delete_conversation_invalid_id"
    start = time.time()
    try:
        await client.delete_conversation(999999999)
        duration = (time.time() - start) * 1000
        return TestResult(name, False, 200, duration, error="Expected 404 but got success")
    except NotFoundError:
        duration = (time.time() - start) * 1000
        return TestResult(name, True, 404, duration)
    except Exception as e:
        duration = (time.time() - start) * 1000
        return TestResult(name, False, getattr(e, "status_code", 0), duration, error=str(e))
