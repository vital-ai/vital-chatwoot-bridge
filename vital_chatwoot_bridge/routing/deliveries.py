"""What happened to each inbound message: handed to its agent, failed after retries, or held because its inbox is paused.

Outcomes are posted to ``CW_BRIDGE__deliveries__report_url`` when reports are on (the default in multi mode), with a
bearer token from the bridge's own client credentials. A report that can't be posted is logged, never retried in the
request path: the receiving service also checks for messages that never got an outcome. The report carries ids,
status, attempts and the last error, never the message text.

Each agent's recent health (last success, last error, consecutive failures) is kept in memory for ``/status``.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Dict, Optional

import httpx

logger = logging.getLogger(__name__)

STATUSES = ("delivered", "failed", "paused", "unrouted")


@dataclass
class AgentHealth:
    agent_id: str
    agent_url: str
    last_ok_at: Optional[str] = None
    last_error_at: Optional[str] = None
    last_error: Optional[str] = None
    consecutive_failures: int = 0
    delivered: int = 0
    failed: int = 0


@dataclass
class DeliveryReporter:
    report_url: str = ""
    enabled: bool = False
    token_url: str = ""
    client_id: str = ""
    client_secret: str = ""
    health: Dict[str, AgentHealth] = field(default_factory=dict)
    reports_failed: int = 0
    _token: Optional[str] = None
    _token_expires: float = 0.0

    def agent_result(self, agent_id: str, agent_url: str, ok: bool, error: Optional[str] = None) -> None:
        h = self.health.setdefault(agent_id, AgentHealth(agent_id, agent_url))
        h.agent_url = agent_url
        now = datetime.now(timezone.utc).isoformat()
        if ok:
            h.last_ok_at, h.consecutive_failures, h.delivered = now, 0, h.delivered + 1
        else:
            h.last_error_at, h.last_error, h.failed = now, (error or "")[:300], h.failed + 1
            h.consecutive_failures += 1

    def agents(self) -> list:
        return [asdict(h) for h in sorted(self.health.values(), key=lambda h: h.agent_id)]

    async def _bearer(self, client: httpx.AsyncClient) -> Optional[str]:
        if not self.token_url:
            return None
        if self._token and time.time() < self._token_expires - 30:
            return self._token
        r = await client.post(self.token_url, data={"grant_type": "client_credentials", "client_id": self.client_id,
                                                    "client_secret": self.client_secret})
        r.raise_for_status()
        body = r.json()
        self._token, self._token_expires = body["access_token"], time.time() + int(body.get("expires_in", 60))
        return self._token

    async def report(self, *, app: Optional[str], account_id: int, inbox_id: str, conversation_id: Optional[int],
                     message_id: Optional[int], agent_id: Optional[str], status: str, attempts: int,
                     error: Optional[str] = None) -> None:
        """Post one outcome. Fire and forget: the webhook isn't held up by the report."""
        if not (self.enabled and self.report_url):
            return
        body = {"app": app, "chatwoot_account_id": account_id, "inbox_id": str(inbox_id),
                "conversation_id": conversation_id, "message_id": message_id, "agent_id": agent_id, "status": status,
                "attempts": attempts, "last_error": (error or None) and error[:500],
                "at": datetime.now(timezone.utc).isoformat()}
        asyncio.create_task(self._post(body))

    async def _post(self, body: dict) -> None:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                token = await self._bearer(client)
                headers = {"Authorization": f"Bearer {token}"} if token else {}
                r = await client.post(self.report_url, json=body, headers=headers)
                r.raise_for_status()
        except Exception as e:  # noqa: BLE001 - a lost report is logged; the receiver checks for gaps
            self.reports_failed += 1
            logger.warning(f"📬 DELIVERIES: report for message {body.get('message_id')} ({body['status']}) "
                           f"not posted: {type(e).__name__}")


_reporter: Optional[DeliveryReporter] = None


def get_reporter() -> DeliveryReporter:
    global _reporter
    if _reporter is None:
        from vital_chatwoot_bridge.core.config import get_settings
        s = get_settings()
        _reporter = DeliveryReporter(s.deliveries_report_url, s.deliveries_enabled, s.deliveries_token_url,
                                     s.deliveries_client_id, s.deliveries_client_secret)
    return _reporter


def set_reporter(reporter: Optional[DeliveryReporter]) -> None:
    global _reporter
    _reporter = reporter
