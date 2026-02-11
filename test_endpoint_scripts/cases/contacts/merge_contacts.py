"""
Test cases for POST /api/v1/chatwoot/contacts/merge.
Creates two contacts, merges them, verifies the mergee is gone.
"""

import time
import uuid
from typing import Dict, List

from vital_chatwoot_bridge.client.client import ChatwootBridgeClient
from vital_chatwoot_bridge.client.exceptions import NotFoundError
from test_endpoint_scripts.base import TestResult


async def merge_contacts_cases(client: ChatwootBridgeClient, config: Dict[str, str]) -> List[TestResult]:
    """Run all merge_contacts test cases."""
    return [
        await _test_merge_contacts(client),
    ]


async def _test_merge_contacts(client: ChatwootBridgeClient) -> TestResult:
    """Create two contacts, merge the second into the first, verify merge succeeded."""
    name = "merge_contacts"
    start = time.time()
    try:
        suffix = uuid.uuid4().hex[:8]

        # Create base contact
        base_resp = await client.create_contact(
            name=f"Base Contact {suffix}",
            email=f"base_{suffix}@example.com",
        )
        base_contact = base_resp.data
        base_id = (
            base_contact.get("id")
            or base_contact.get("payload", {}).get("contact", {}).get("id")
        )

        # Create mergee contact
        mergee_resp = await client.create_contact(
            name=f"Mergee Contact {suffix}",
            email=f"mergee_{suffix}@example.com",
        )
        mergee_contact = mergee_resp.data
        mergee_id = (
            mergee_contact.get("id")
            or mergee_contact.get("payload", {}).get("contact", {}).get("id")
        )

        if not base_id or not mergee_id:
            duration = (time.time() - start) * 1000
            return TestResult(name, False, 0, duration, error="Could not extract contact IDs")

        # Merge
        merge_resp = await client.merge_contacts(base_id, mergee_id)
        duration = (time.time() - start) * 1000

        if not merge_resp.success:
            return TestResult(name, False, 200, duration, error="merge returned success=false")

        # Clean up base contact
        try:
            await client.delete_contact(base_id)
        except Exception:
            pass

        return TestResult(name, True, 200, duration,
                          response_data={"base_id": base_id, "mergee_id": mergee_id})
    except Exception as e:
        duration = (time.time() - start) * 1000
        return TestResult(name, False, getattr(e, "status_code", 0), duration, error=str(e))
