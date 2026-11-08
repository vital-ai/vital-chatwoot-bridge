"""Which agent handles which inbox: the route table.

Two account modes (``CW_BRIDGE__chatwoot__account_mode``):

- ``single`` (the default, and the bridge's original behaviour): one Chatwoot account, ``chatwoot.account_id``, with
  routes from the ``CW_BRIDGE__inbox_agents__<inbox_id>__*`` settings.
- ``multi``: several Chatwoot accounts, typically one per application. Routes come from route files
  (``CW_BRIDGE__routing__files``), one per application, each naming its Chatwoot account and its inboxes. The files are
  read at start and again on ``POST /api/v1/routes/reload``. A file that doesn't validate is refused, and the bridge
  keeps the routes it had.

A route file::

    app: example                    # a name for logs, status and delivery reports
    chatwoot_account_id: 3
    bot: example-bot                # optional: a bot in CW_BRIDGE__bots__, whose token signs this account's webhooks
    agent_auth:                     # optional: the token this app's agents expect, sent inside each message
      token_url: https://keycloak.example.com/realms/example/protocol/openid-connect/token
      client_id: chatwoot-bridge
      client_secret_env: EXAMPLE_AGENT_CLIENT_SECRET   # the environment variable holding the secret
    inboxes:
      - inbox_id: 12
        name: support-email
        retries: 2                  # extra attempts to hand a message to the agent (default 0)
        agent:
          agent_id: support-agent
          websocket_url: ws://support-agent:8080/ws
          timeout_seconds: 120
        aimp_intent_type: http://vital.ai/ontology/vital-aimp#AIMPIntentType_CHAT   # optional
        from_email: support@example.com                                              # optional
        reply_subject: Your message to support    # optional: an API inbox's replies are emailed from from_email

In an API inbox (a contact form, say) a reply reaches the contact only if the route has ``from_email``: then each public
reply is also emailed to the contact from that address, once (the message id is the idempotency key).

Pausing an inbox is separate runtime state (``routing/pauses.py``): reloading the routes never changes it.
"""

from __future__ import annotations

import logging
import os
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import yaml
from pydantic import BaseModel, Field, ValidationError, field_validator

from vital_chatwoot_bridge.core.config import AgentConfig, Config, InboxMapping, get_settings

logger = logging.getLogger(__name__)

DEFAULT_INTENT = "http://vital.ai/ontology/vital-aimp#AIMPIntentType_CHAT"


class RouteFileError(ValueError):
    """A route file that can't be used. The routes already loaded stay in place."""


class InboxRouteSpec(BaseModel):
    inbox_id: str
    name: str = ""
    retries: int = Field(default=0, ge=0, le=10)
    agent: AgentConfig
    aimp_intent_type: str = DEFAULT_INTENT
    from_email: Optional[str] = None
    from_phone: Optional[str] = None
    reply_subject: Optional[str] = Field(default=None, max_length=200)

    @field_validator("inbox_id", mode="before")
    @classmethod
    def _as_text(cls, v):
        return str(v)


class AgentAuthSpec(BaseModel):
    token_url: str
    client_id: str
    client_secret_env: str = Field(pattern=r"^[A-Z][A-Z0-9_]*$")


class RouteFileSpec(BaseModel):
    app: str = Field(min_length=1, max_length=64)
    chatwoot_account_id: int = Field(gt=0)
    bot: Optional[str] = None
    agent_auth: Optional[AgentAuthSpec] = None
    inboxes: List[InboxRouteSpec] = Field(min_length=1)


@dataclass(frozen=True)
class Route:
    account_id: int
    inbox_id: str
    inbox_name: str
    app: Optional[str]
    agent: AgentConfig
    aimp_intent_type: str
    from_email: Optional[str]
    from_phone: Optional[str]
    retries: int
    bot: Optional[str]
    source: str                      # "settings", or the route file's path
    agent_auth: Optional[dict] = None   # token_url, client_id, client_secret_env
    reply_subject: Optional[str] = None

    @property
    def key(self) -> Tuple[int, str]:
        return (self.account_id, self.inbox_id)

    def mapping(self) -> InboxMapping:
        """The route as the webhook handler's InboxMapping."""
        return InboxMapping(inbox_id=self.inbox_id, inbox_name=self.inbox_name, aimp_intent_type=self.aimp_intent_type,
                            from_email=self.from_email, from_phone=self.from_phone, agent_config=self.agent)

    def describe(self) -> dict:
        return {"account_id": self.account_id, "inbox_id": self.inbox_id, "inbox_name": self.inbox_name, "app": self.app,
                "agent_id": self.agent.agent_id, "agent_url": self.agent.websocket_url,
                "timeout_seconds": self.agent.timeout_seconds, "retries": self.retries, "source": self.source,
                "agent_auth": {k: v for k, v in (self.agent_auth or {}).items() if k != "client_secret_env"} or None}


def _route_files(paths: List[str]) -> List[Path]:
    """Each entry is a file, or a directory searched for chatwoot_bridge.yml (one level down too) or *.yml."""
    found: List[Path] = []
    for raw in paths:
        p = Path(raw).expanduser()
        if p.is_dir():
            named = sorted([*p.glob("chatwoot_bridge.yml"), *p.glob("*/chatwoot_bridge.yml")])
            found += named or sorted(p.glob("*.yml"))
        elif p.exists():
            found.append(p)
        else:
            raise RouteFileError(f"route file {p} doesn't exist")
    return found


def load_route_files(paths: List[str]) -> Dict[Tuple[int, str], Route]:
    routes: Dict[Tuple[int, str], Route] = {}
    apps_by_account: Dict[int, str] = {}
    for path in _route_files(paths):
        try:
            spec = RouteFileSpec(**(yaml.safe_load(path.read_text(encoding="utf-8")) or {}))
        except (OSError, yaml.YAMLError, ValidationError, TypeError) as e:
            raise RouteFileError(f"{path}: {e}") from None
        if spec.agent_auth and not os.environ.get(spec.agent_auth.client_secret_env):
            raise RouteFileError(f"{path}: agent_auth's secret ({spec.agent_auth.client_secret_env}) isn't set")
        other = apps_by_account.setdefault(spec.chatwoot_account_id, spec.app)
        if other != spec.app:
            raise RouteFileError(f"{path}: Chatwoot account {spec.chatwoot_account_id} is already {other}'s")
        for inbox in spec.inboxes:
            key = (spec.chatwoot_account_id, inbox.inbox_id)
            if key in routes:
                raise RouteFileError(f"{path}: inbox {inbox.inbox_id} of account {spec.chatwoot_account_id} is routed twice")
            routes[key] = Route(spec.chatwoot_account_id, inbox.inbox_id, inbox.name, spec.app, inbox.agent,
                                inbox.aimp_intent_type, inbox.from_email, inbox.from_phone, inbox.retries, spec.bot,
                                str(path), spec.agent_auth.model_dump() if spec.agent_auth else None, inbox.reply_subject)
    return routes


def routes_from_settings(settings: Config) -> Dict[Tuple[int, str], Route]:
    account = int(settings.chatwoot_account_id)
    return {(account, m.inbox_id): Route(account, m.inbox_id, m.inbox_name, None, m.agent_config, m.aimp_intent_type,
                                         m.from_email, m.from_phone, 0, m.agent_config.bot, "settings")
            for m in settings.inbox_agent_mappings}


class RouteTable:
    def __init__(self, settings: Optional[Config] = None):
        self.settings = settings or get_settings()
        self.mode = self.settings.chatwoot_account_mode
        self._routes: Dict[Tuple[int, str], Route] = {}
        self._lock = threading.Lock()
        self.loaded_from: List[str] = []
        self.load()

    def load(self) -> Dict[str, int]:
        """Read the routes again. In multi mode a bad file raises RouteFileError and nothing changes."""
        if self.mode == "multi":
            routes = load_route_files(self.settings.routing_files)
            missing = sorted({a for a, _ in routes} - set(self.settings.chatwoot_account_tokens))
            if missing and not self.settings.chatwoot_user_access_token:
                raise RouteFileError(f"no API token for Chatwoot account(s) {missing}")
            sources = sorted({r.source for r in routes.values()})
        else:
            routes = routes_from_settings(self.settings)
            sources = ["settings"]
        with self._lock:
            self._routes = routes
            self.loaded_from = sources
        logger.info(f"🧭 ROUTES: {len(routes)} route(s) in {self.mode} mode from {', '.join(sources) or 'nothing'}")
        return {"routes": len(routes), "accounts": len({a for a, _ in routes})}

    def get(self, account_id: Optional[int], inbox_id: str) -> Optional[Route]:
        """The route for an inbox. In single mode the account may be left out; another account than the configured
        one has no routes."""
        if account_id is None:
            if self.mode == "multi":
                return None
            account_id = int(self.settings.chatwoot_account_id)
        return self._routes.get((int(account_id), str(inbox_id)))

    def all(self) -> List[Route]:
        return sorted(self._routes.values(), key=lambda r: (r.account_id, r.inbox_id))

    def accounts(self) -> List[int]:
        if self.mode == "single":
            return [int(self.settings.chatwoot_account_id)]
        return sorted({a for a, _ in self._routes})

    def webhook_secret(self, account_id: Optional[int], inbox_id: str) -> Optional[str]:
        """The token that signs this inbox's webhooks: its route's bot's access token."""
        route = self.get(account_id, inbox_id)
        if route and route.bot:
            bot = self.settings.bots.get(route.bot)
            if bot:
                return bot.access_token
        return None


_table: Optional[RouteTable] = None


def get_route_table() -> RouteTable:
    global _table
    if _table is None:
        _table = RouteTable()
    return _table


def set_route_table(table: Optional[RouteTable]) -> None:
    """For tests, and to start over."""
    global _table
    _table = table
