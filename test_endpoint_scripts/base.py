"""
Base test infrastructure: TestResult, BaseRunner, and reporting utilities.
All test env vars are read from .env — no hardcoded test data.
"""

import asyncio
import logging
import os
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv

from vital_chatwoot_bridge.client.client import ChatwootBridgeClient

load_dotenv()

logger = logging.getLogger(__name__)


@dataclass
class TestResult:
    """Result of a single test case."""
    name: str
    passed: bool
    status_code: int = 0
    duration_ms: float = 0.0
    error: Optional[str] = None
    response_data: Optional[Dict[str, Any]] = None
    case_id: Optional[str] = None


def get_env(key: str, default: str = "") -> str:
    """Get an environment variable, raising if required and missing."""
    return os.getenv(key, default)


def get_env_required(key: str) -> str:
    """Get a required environment variable."""
    val = os.getenv(key)
    if not val:
        raise EnvironmentError(f"Required env var {key} is not set")
    return val


def get_test_config() -> Dict[str, str]:
    """Load all test-related env vars into a dict."""
    return {
        "bridge_base_url": get_env("BRIDGE_BASE_URL", "http://localhost:8009"),
        "keycloak_base_url": get_env("KEYCLOAK_CLIENT_BASE_URL") or get_env_required("KEYCLOAK_BASE_URL"),
        "keycloak_realm": get_env_required("KEYCLOAK_REALM"),
        "keycloak_client_id": get_env_required("KEYCLOAK_CLIENT_ID"),
        "keycloak_client_secret": get_env("KEYCLOAK_CLIENT_SECRET", ""),
        "keycloak_user": get_env("KEYCLOAK_USER", ""),
        "keycloak_password": get_env("KEYCLOAK_PASSWORD", ""),
        "test_sms_recipient": get_env("TEST_SMS_RECIPIENT", ""),
        "test_email_recipient": get_env("TEST_EMAIL_RECIPIENT", ""),
        "test_contact_name": get_env("TEST_CONTACT_NAME", "Test User"),
        "test_loopmessage_inbox_id": get_env("TEST_LOOPMESSAGE_INBOX_ID", ""),
        "test_loopmessage_phone": get_env("TEST_LOOPMESSAGE_PHONE", ""),
    }


def create_client(config: Dict[str, str]) -> ChatwootBridgeClient:
    """Create a ChatwootBridgeClient from test config."""
    return ChatwootBridgeClient(
        base_url=config["bridge_base_url"],
        keycloak_url=config["keycloak_base_url"],
        realm=config["keycloak_realm"],
        client_id=config["keycloak_client_id"],
        client_secret=config["keycloak_client_secret"] or None,
        username=config["keycloak_user"] or None,
        password=config["keycloak_password"] or None,
    )


class BaseRunner:
    """Base class for endpoint test runners."""

    def __init__(self, name: str, verbose: bool = False, case_filter: Optional[str] = None):
        self.name = name
        self.verbose = verbose
        self.case_filter = case_filter
        self.config = get_test_config()
        self.results: List[TestResult] = []

    async def run(self) -> List[TestResult]:
        """Override in subclasses to run test cases."""
        raise NotImplementedError

    async def execute(self) -> List[TestResult]:
        """Run all cases and return results."""
        client = create_client(self.config)
        try:
            self.results = await self.run_with_client(client)
        finally:
            await client.close()
        return self.results

    async def run_cases(self, case_fn, client, config) -> List[TestResult]:
        """Run a case function, filtering by --case IDs.

        --case accepts comma-separated case IDs (e.g. --case m-send-lm,c-list1).
        """
        from test_endpoint_scripts.case_registry import CASE_IDS, ID_TO_NAME

        if self.case_filter:
            requested = [c.strip() for c in self.case_filter.split(",")]
            # Resolve IDs to test names
            wanted_names = set()
            for req in requested:
                if req in ID_TO_NAME:
                    wanted_names.add(ID_TO_NAME[req])
                else:
                    wanted_names.add(req)  # allow raw name too

            results = await case_fn(client, config)
            # Auto-assign case_id from registry
            for r in results:
                if not r.case_id:
                    r.case_id = CASE_IDS.get(r.name)
            return [r for r in results if r.name in wanted_names or r.case_id in requested]

        results = await case_fn(client, config)
        for r in results:
            if not r.case_id:
                r.case_id = CASE_IDS.get(r.name)
        return results

    async def run_with_client(self, client: ChatwootBridgeClient) -> List[TestResult]:
        """Override in subclasses. Receives an initialized client."""
        raise NotImplementedError

    def print_report(self) -> None:
        """Print a summary table of test results."""
        passed = sum(1 for r in self.results if r.passed)
        failed = sum(1 for r in self.results if not r.passed)
        total = len(self.results)

        print(f"\n{'='*70}")
        print(f"  {self.name}  —  {passed}/{total} passed, {failed} failed")
        print(f"{'='*70}")

        for r in self.results:
            status = "✅ PASS" if r.passed else "❌ FAIL"
            timing = f"{r.duration_ms:.0f}ms"
            cid = f"({r.case_id})" if r.case_id else ""
            line = f"  {status}  {cid:<16} {r.name:<40} [{r.status_code}] {timing}"
            print(line)
            if not r.passed and r.error:
                print(f"         Error: {r.error}")
            if self.verbose and r.response_data:
                import json
                print(f"         Data: {json.dumps(r.response_data, indent=2)[:500]}")

        total_time = sum(r.duration_ms for r in self.results)
        print(f"\n  Total time: {total_time:.0f}ms")
        print()


def parse_runner_args() -> tuple:
    """Parse common runner CLI args: --verbose/-v, --case <ids>, --list."""
    import sys
    verbose = "--verbose" in sys.argv or "-v" in sys.argv
    case_filter = None
    if "--case" in sys.argv:
        idx = sys.argv.index("--case")
        if idx + 1 < len(sys.argv):
            case_filter = sys.argv[idx + 1]
    if "--list" in sys.argv:
        from test_endpoint_scripts.case_registry import CASE_IDS
        print(f"\n{'ID':<18} {'Test Name'}")
        print(f"{'─'*18} {'─'*40}")
        for name, cid in CASE_IDS.items():
            print(f"{cid:<18} {name}")
        print()
        sys.exit(0)
    return verbose, case_filter


def run_runner(runner: BaseRunner) -> List[TestResult]:
    """Helper to run a single runner from a sync context (e.g. __main__)."""
    results = asyncio.run(runner.execute())
    runner.print_report()
    return results
