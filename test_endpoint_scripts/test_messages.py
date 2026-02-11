"""
Runner for Messages endpoint tests.
"""

import sys
from typing import List

from vital_chatwoot_bridge.client.client import ChatwootBridgeClient
from test_endpoint_scripts.base import BaseRunner, TestResult, run_runner, parse_runner_args
from test_endpoint_scripts.cases.messages.list_messages import list_messages_cases
from test_endpoint_scripts.cases.messages.post_message import post_message_cases
from test_endpoint_scripts.cases.messages.delete_message import delete_message_cases
from test_endpoint_scripts.cases.messages.send_loopmessage import send_loopmessage_cases


class MessagesRunner(BaseRunner):
    """Runner for /api/v1/chatwoot/messages endpoints."""

    def __init__(self, verbose: bool = False, case_filter: str = None):
        super().__init__("Messages", verbose=verbose, case_filter=case_filter)

    async def run_with_client(self, client: ChatwootBridgeClient) -> List[TestResult]:
        results = []
        results.extend(await self.run_cases(list_messages_cases, client, self.config))
        results.extend(await self.run_cases(post_message_cases, client, self.config))
        results.extend(await self.run_cases(delete_message_cases, client, self.config))
        results.extend(await self.run_cases(send_loopmessage_cases, client, self.config))
        return results


if __name__ == "__main__":
    verbose, case_filter = parse_runner_args()
    runner = MessagesRunner(verbose=verbose, case_filter=case_filter)
    results = run_runner(runner)
    sys.exit(0 if all(r.passed for r in results) else 1)
