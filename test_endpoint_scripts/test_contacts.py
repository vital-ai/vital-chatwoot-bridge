"""
Runner for Contacts endpoint tests.
"""

from typing import List

from vital_chatwoot_bridge.client.client import ChatwootBridgeClient
from test_endpoint_scripts.base import BaseRunner, TestResult, run_runner, parse_runner_args
from test_endpoint_scripts.cases.contacts.list_contacts import list_contacts_cases
from test_endpoint_scripts.cases.contacts.search_contacts import search_contacts_cases
from test_endpoint_scripts.cases.contacts.get_contact import get_contact_cases
from test_endpoint_scripts.cases.contacts.create_contact import create_contact_cases
from test_endpoint_scripts.cases.contacts.delete_contact import delete_contact_cases
from test_endpoint_scripts.cases.contacts.contact_count import contact_count_cases
from test_endpoint_scripts.cases.contacts.update_contact import update_contact_cases
from test_endpoint_scripts.cases.contacts.merge_contacts import merge_contacts_cases


class ContactsRunner(BaseRunner):
    """Runner for /api/v1/chatwoot/contacts endpoints."""

    def __init__(self, verbose: bool = False, case_filter: str = None):
        super().__init__("Contacts", verbose=verbose, case_filter=case_filter)

    async def run_with_client(self, client: ChatwootBridgeClient) -> List[TestResult]:
        results = []
        results.extend(await self.run_cases(list_contacts_cases, client, self.config))
        results.extend(await self.run_cases(search_contacts_cases, client, self.config))
        results.extend(await self.run_cases(get_contact_cases, client, self.config))
        results.extend(await self.run_cases(create_contact_cases, client, self.config))
        results.extend(await self.run_cases(delete_contact_cases, client, self.config))
        results.extend(await self.run_cases(contact_count_cases, client, self.config))
        results.extend(await self.run_cases(update_contact_cases, client, self.config))
        results.extend(await self.run_cases(merge_contacts_cases, client, self.config))
        return results


if __name__ == "__main__":
    import sys
    verbose, case_filter = parse_runner_args()
    runner = ContactsRunner(verbose=verbose, case_filter=case_filter)
    results = run_runner(runner)
    sys.exit(0 if all(r.passed for r in results) else 1)
