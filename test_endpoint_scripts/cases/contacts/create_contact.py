"""
Test cases for POST /api/v1/chatwoot/contacts (create contact).
Cleans up existing contacts (by email/phone) before creating to avoid duplicates.
"""

import logging
import time
import uuid
from typing import Dict, List, Optional

from vital_chatwoot_bridge.client.client import ChatwootBridgeClient
from vital_chatwoot_bridge.client.exceptions import BridgeClientError
from test_endpoint_scripts.base import TestResult

logger = logging.getLogger(__name__)

FULL_CONTACT_EMAIL = "test_full_contact@example.com"
FULL_CONTACT_PHONE = "+15550001234"


async def _cleanup_existing_contact(
    client: ChatwootBridgeClient, search_key: str
) -> None:
    """Search for a contact by email/phone and delete if found."""
    try:
        resp = await client.search_contacts(q=search_key)
        for contact in resp.data:
            contact_id = contact.get("id") if isinstance(contact, dict) else None
            if contact_id:
                logger.info(f"Deleting existing contact {contact_id} (matched '{search_key}')")
                try:
                    await client.delete_contact(contact_id)
                except Exception:
                    logger.warning(f"Failed to delete contact {contact_id}, continuing")
    except Exception:
        pass


async def create_contact_cases(client: ChatwootBridgeClient, config: Dict[str, str]) -> List[TestResult]:
    """Run all create_contact test cases."""
    return [
        await _test_create_contact_minimal(client),
        await _test_create_contact_full(client, config),
    ]


async def _test_create_contact_minimal(client: ChatwootBridgeClient) -> TestResult:
    """Create a contact with only a name."""
    name = "create_contact_minimal"
    unique_name = f"Test Contact {uuid.uuid4().hex[:8]}"
    start = time.time()
    try:
        resp = await client.create_contact(name=unique_name)
        duration = (time.time() - start) * 1000
        if not resp.success:
            return TestResult(name, False, 201, duration, error="success=false")
        return TestResult(name, True, 201, duration, response_data={"created": resp.data})
    except Exception as e:
        duration = (time.time() - start) * 1000
        return TestResult(name, False, getattr(e, "status_code", 0), duration, error=str(e))


async def _test_create_contact_full(client: ChatwootBridgeClient, config: Dict[str, str]) -> TestResult:
    """Create a contact with all fields. Deletes existing contacts with same email/phone first."""
    name = "create_contact_full_fields"

    await _cleanup_existing_contact(client, FULL_CONTACT_EMAIL)
    await _cleanup_existing_contact(client, FULL_CONTACT_PHONE)

    unique_suffix = uuid.uuid4().hex[:8]
    start = time.time()
    try:
        resp = await client.create_contact(
            name=f"Full Contact {unique_suffix}",
            email=FULL_CONTACT_EMAIL,
            phone_number=FULL_CONTACT_PHONE,
            identifier=f"ext_{unique_suffix}",
        )
        duration = (time.time() - start) * 1000
        if not resp.success:
            return TestResult(name, False, 201, duration, error="success=false")
        return TestResult(name, True, 201, duration, response_data={"created": resp.data})
    except Exception as e:
        duration = (time.time() - start) * 1000
        return TestResult(name, False, getattr(e, "status_code", 0), duration, error=str(e))
