"""
Runner for Inboxes endpoint tests.
"""

import sys
from typing import List

from vital_chatwoot_bridge.client.client import ChatwootBridgeClient
from test_endpoint_scripts.base import BaseRunner, TestResult, run_runner, parse_runner_args
from test_endpoint_scripts.cases.inboxes.list_inboxes import list_inboxes_cases


class InboxesRunner(BaseRunner):
    """Runner for /api/v1/chatwoot/inboxes endpoints."""

    def __init__(self, verbose: bool = False, case_filter: str = None):
        super().__init__("Inboxes", verbose=verbose, case_filter=case_filter)

    async def run_with_client(self, client: ChatwootBridgeClient) -> List[TestResult]:
        results = []
        results.extend(await self.run_cases(list_inboxes_cases, client, self.config))
        return results


if __name__ == "__main__":
    verbose, case_filter = parse_runner_args()
    runner = InboxesRunner(verbose=verbose, case_filter=case_filter)
    results = run_runner(runner)
    sys.exit(0 if all(r.passed for r in results) else 1)
