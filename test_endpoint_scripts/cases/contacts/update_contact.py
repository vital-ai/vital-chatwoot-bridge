"""
Test cases for POST /api/v1/chatwoot/contacts/{contact_id} (update contact).
"""

import time
import uuid
from typing import Dict, List

from vital_chatwoot_bridge.client.client import ChatwootBridgeClient
from vital_chatwoot_bridge.client.exceptions import NotFoundError, ValidationError
from test_endpoint_scripts.base import TestResult


async def update_contact_cases(client: ChatwootBridgeClient, config: Dict[str, str]) -> List[TestResult]:
    """Run all update_contact test cases."""
    return [
        await _test_update_contact_name(client),
        await _test_update_contact_invalid_id(client),
    ]


async def _test_update_contact_name(client: ChatwootBridgeClient) -> TestResult:
    """Create a contact, update its name, verify the change."""
    name = "update_contact_name"
    start = time.time()
    try:
        # Create a throwaway contact
        suffix = uuid.uuid4().hex[:8]
        create_resp = await client.create_contact(name=f"Before Update {suffix}")
        contact = create_resp.data
        contact_id = (
            contact.get("id")
            or contact.get("payload", {}).get("contact", {}).get("id")
        )
        if not contact_id:
            duration = (time.time() - start) * 1000
            return TestResult(name, False, 0, duration, error="Could not extract contact_id")

        # Update the name
        new_name = f"After Update {suffix}"
        update_resp = await client.update_contact(contact_id, name=new_name)

        duration = (time.time() - start) * 1000

        if not update_resp.success:
            return TestResult(name, False, 200, duration, error="update returned success=false")

        # Verify the name in the update response (nested under payload)
        updated = update_resp.data
        if isinstance(updated, dict) and "payload" in updated:
            updated = updated["payload"]
        actual_name = updated.get("name", "") if isinstance(updated, dict) else ""
        if actual_name != new_name:
            return TestResult(name, False, 200, duration,
                              error=f"Expected name '{new_name}', got '{actual_name}'")

        # Clean up
        try:
            await client.delete_contact(contact_id)
        except Exception:
            pass

        return TestResult(name, True, 200, duration, response_data={"updated_name": actual_name})
    except Exception as e:
        duration = (time.time() - start) * 1000
        return TestResult(name, False, getattr(e, "status_code", 0), duration, error=str(e))


async def _test_update_contact_invalid_id(client: ChatwootBridgeClient) -> TestResult:
    """Attempt to update a non-existent contact — expect 404."""
    name = "update_contact_invalid_id"
    start = time.time()
    try:
        await client.update_contact(999999999, name="Ghost")
        duration = (time.time() - start) * 1000
        return TestResult(name, False, 200, duration, error="Expected 404 but got success")
    except NotFoundError:
        duration = (time.time() - start) * 1000
        return TestResult(name, True, 404, duration)
    except Exception as e:
        duration = (time.time() - start) * 1000
        return TestResult(name, False, getattr(e, "status_code", 0), duration, error=str(e))
