"""
Test cases for DELETE /api/v1/chatwoot/contacts/{contact_id}.
Creates a temporary contact, then deletes it, then verifies 404 on re-fetch.
"""

import time
import uuid
from typing import Dict, List

from vital_chatwoot_bridge.client.client import ChatwootBridgeClient
from vital_chatwoot_bridge.client.exceptions import NotFoundError
from test_endpoint_scripts.base import TestResult


async def delete_contact_cases(client: ChatwootBridgeClient, config: Dict[str, str]) -> List[TestResult]:
    """Run all delete_contact test cases."""
    return [
        await _test_delete_contact(client),
        await _test_delete_contact_invalid_id(client),
    ]


async def _test_delete_contact(client: ChatwootBridgeClient) -> TestResult:
    """Create a contact, delete it, verify it's gone."""
    name = "delete_contact"
    start = time.time()
    try:
        # Create a throwaway contact
        unique_name = f"Delete Me {uuid.uuid4().hex[:8]}"
        create_resp = await client.create_contact(name=unique_name)
        contact = create_resp.data
        contact_id = (
            contact.get("id")
            or contact.get("payload", {}).get("contact", {}).get("id")
        )
        if not contact_id:
            duration = (time.time() - start) * 1000
            return TestResult(name, False, 0, duration, error="Could not extract contact_id from create response")

        # Delete it
        del_resp = await client.delete_contact(contact_id)
        duration = (time.time() - start) * 1000

        if not del_resp.success:
            return TestResult(name, False, 200, duration, error="delete returned success=false")

        # Verify it's gone
        try:
            await client.get_contact(contact_id)
            return TestResult(name, False, 200, duration, error="Contact still exists after delete")
        except NotFoundError:
            pass  # Expected

        return TestResult(name, True, 200, duration)
    except Exception as e:
        duration = (time.time() - start) * 1000
        return TestResult(name, False, getattr(e, "status_code", 0), duration, error=str(e))


async def _test_delete_contact_invalid_id(client: ChatwootBridgeClient) -> TestResult:
    """Attempt to delete a non-existent contact — expect 404."""
    name = "delete_contact_invalid_id"
    start = time.time()
    try:
        await client.delete_contact(999999999)
        duration = (time.time() - start) * 1000
        return TestResult(name, False, 200, duration, error="Expected 404 but got success")
    except NotFoundError:
        duration = (time.time() - start) * 1000
        return TestResult(name, True, 404, duration)
    except Exception as e:
        duration = (time.time() - start) * 1000
        return TestResult(name, False, getattr(e, "status_code", 0), duration, error=str(e))
