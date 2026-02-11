"""
Runner for Conversations endpoint tests.
"""

import sys
from typing import List

from vital_chatwoot_bridge.client.client import ChatwootBridgeClient
from test_endpoint_scripts.base import BaseRunner, TestResult, run_runner, parse_runner_args
from test_endpoint_scripts.cases.conversations.list_conversations import list_conversations_cases
from test_endpoint_scripts.cases.conversations.get_conversation import get_conversation_cases
from test_endpoint_scripts.cases.conversations.delete_conversation import delete_conversation_cases
from test_endpoint_scripts.cases.conversations.conversation_count import conversation_count_cases
from test_endpoint_scripts.cases.conversations.update_conversation import update_conversation_cases
from test_endpoint_scripts.cases.conversations.account_summary import account_summary_cases
from test_endpoint_scripts.cases.conversations.create_conversation import create_conversation_cases


class ConversationsRunner(BaseRunner):
    """Runner for /api/v1/chatwoot/conversations endpoints."""

    def __init__(self, verbose: bool = False, case_filter: str = None):
        super().__init__("Conversations", verbose=verbose, case_filter=case_filter)

    async def run_with_client(self, client: ChatwootBridgeClient) -> List[TestResult]:
        results = []
        results.extend(await self.run_cases(list_conversations_cases, client, self.config))
        results.extend(await self.run_cases(get_conversation_cases, client, self.config))
        results.extend(await self.run_cases(delete_conversation_cases, client, self.config))
        results.extend(await self.run_cases(conversation_count_cases, client, self.config))
        results.extend(await self.run_cases(update_conversation_cases, client, self.config))
        results.extend(await self.run_cases(account_summary_cases, client, self.config))
        results.extend(await self.run_cases(create_conversation_cases, client, self.config))
        return results


if __name__ == "__main__":
    verbose, case_filter = parse_runner_args()
    runner = ConversationsRunner(verbose=verbose, case_filter=case_filter)
    results = run_runner(runner)
    sys.exit(0 if all(r.passed for r in results) else 1)
