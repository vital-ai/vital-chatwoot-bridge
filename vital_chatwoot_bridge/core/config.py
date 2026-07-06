"""
Configuration settings for the Vital Chatwoot Bridge application.

All configuration is read from ``CW_BRIDGE__*`` environment variables parsed
into a nested dict by :func:`parse_env_tree`.  See ``planning/config_update.md``
for the full migration table.
"""

import json
import logging
from typing import List, Optional, Dict, Any
from functools import lru_cache
from pydantic import BaseModel, Field

from vital_chatwoot_bridge.utils.env_parser import parse_env_tree, coerce_dict
from vital_chatwoot_bridge.email.models import (
    EmailTemplatesConfig, EmailTemplateDef, MailgunConfig,
    GmailConfig, GmailSender, GmailTrackingConfig,
)
from vital_chatwoot_bridge.zoom.models import (
    ZoomConfig, ZoomOAuthConfig, ZoomAccount,
    ZoomTokenStorageConfig, ZoomTokenRefreshConfig,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class BotConfig(BaseModel):
    """Configuration for a Chatwoot agent bot."""
    access_token: str = Field(..., description="Bot's Chatwoot access_token (HMAC signing key)")
    name: str = Field(default="", description="Human-readable bot name")


class AgentConfig(BaseModel):
    """Configuration for an AI agent."""
    agent_id: str = Field(..., description="Unique identifier for the AI agent")
    websocket_url: str = Field(..., description="WebSocket URL for the AI agent")
    timeout_seconds: int = Field(default=30, description="Response timeout in seconds")
    behavior: str = Field(default="default", description="Agent behavior mode (for mock agents)")
    bot: Optional[str] = Field(default=None, description="Reference to bot name in CW_BRIDGE__bots__")


class InboxMapping(BaseModel):
    """Mapping between Chatwoot inbox and AI agent."""
    inbox_id: str = Field(..., description="Chatwoot inbox identifier as string")
    inbox_name: str = Field(default="", description="Human-readable inbox name (e.g. CarlyAgent)")
    aimp_intent_type: str = Field(
        default="http://vital.ai/ontology/vital-aimp#AIMPIntentType_CHAT",
        description="AIMP intent type URI sent to the agent for this inbox",
    )
    from_email: Optional[str] = Field(default=None, description="Mailgun sender address for this inbox (e.g. carly@mg.cardiff.co)")
    from_phone: Optional[str] = Field(default=None, description="Twilio sender phone number in E.164 format (e.g. +18887894154)")
    agent_config: AgentConfig = Field(..., description="AI agent configuration")


class APIInboxConfig(BaseModel):
    """Configuration for an API inbox."""
    inbox_identifier: str = Field(..., description="API inbox identifier from Chatwoot")
    chatwoot_inbox_id: Optional[str] = Field(None, description="Internal Chatwoot inbox ID for webhook mapping")
    name: str = Field(..., description="Human-readable inbox name")
    message_types: List[str] = Field(..., description="Supported message types (email, sms, imessage)")
    contact_identifier_field: str = Field(..., description="Field to use for contact identification")
    supports_outbound: bool = Field(default=False, description="Whether outbound messages are supported")
    outbound_webhook_url: Optional[str] = Field(None, description="URL for outbound message delivery")
    webhook_events: Optional[Dict[str, str]] = Field(None, description="Supported webhook events and their directions")
    supports_email_replies: bool = Field(default=False, description="Whether email replies are supported outside webhooks")
    description: Optional[str] = Field(None, description="Inbox description")
    hmac_secret: Optional[str] = Field(None, description="HMAC secret for webhook verification")


class MemoryDBConfig(BaseModel):
    """AWS MemoryDB (Redis-compatible) cluster configuration."""
    url: str = Field(..., description="MemoryDB connection URL (rediss://user:pass@host:port)")
    ssl: bool = Field(default=True, description="Enable TLS (MemoryDB always requires TLS)")
    ssl_cert_reqs: str = Field(default="none", description="SSL certificate verification mode")


class DebounceConfig(BaseModel):
    """Message debounce configuration."""
    enabled: bool = Field(default=True, description="Enable message debouncing")
    window_seconds: float = Field(default=3.0, description="Quiet window before draining")
    max_window_seconds: float = Field(default=10.0, description="Hard cap on buffering time")
    max_batch_size: int = Field(default=10, description="Maximum messages to batch")
    dedup_ttl_seconds: int = Field(default=60, description="TTL for message ID deduplication")
    drain_poll_interval: float = Field(default=1.0, description="Seconds between drain poll cycles")
    sms_inbox_ids: List[str] = Field(default_factory=list, description="Inbox IDs to debounce (empty = all)")


class MessageWebhookConfig(BaseModel):
    """Configuration for the general-purpose message event webhook."""
    enabled: bool = Field(default=False, description="Enable message event webhooks")
    url: str = Field(default="", description="Destination URL for message events")
    secret: str = Field(default="", description="HMAC-SHA256 signing secret")
    timeout_seconds: int = Field(default=10, description="HTTP timeout per attempt")
    max_retries: int = Field(default=3, description="Retry count on failure")
    retry_delay_seconds: int = Field(default=5, description="Base delay between retries")


class URLShortenerConfig(BaseModel):
    """URL shortener configuration."""
    provider: str = Field(default="short_io", description="Shortener provider (short_io)")
    api_key: str = Field(..., description="Provider API key")
    domain: str = Field(..., description="Custom branded domain for short links")
    enabled: bool = Field(default=True, description="Enable/disable URL shortening")
    sms_only: bool = Field(default=True, description="Only shorten URLs in SMS messages")
    sms_inbox_ids: List[str] = Field(default_factory=list, description="Chatwoot inbox IDs that are SMS (for sms_only filtering)")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get(tree: Dict[str, Any], *path: str, default: str = "") -> str:
    """Get a leaf value from a nested dict by path segments, returning *default* if missing."""
    node = tree
    for segment in path:
        if not isinstance(node, dict) or segment not in node:
            return default
        node = node[segment]
    return node if isinstance(node, str) else default


def _get_bool(tree: Dict[str, Any], *path: str, default: bool = False) -> bool:
    val = _get(tree, *path, default=str(default).lower())
    return val.lower() == "true"


def _get_int(tree: Dict[str, Any], *path: str, default: int = 0) -> int:
    val = _get(tree, *path, default=str(default))
    try:
        return int(val)
    except ValueError:
        return default


def _get_float(tree: Dict[str, Any], *path: str, default: float = 0.0) -> float:
    val = _get(tree, *path, default=str(default))
    try:
        return float(val)
    except ValueError:
        return default


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

class Config:
    """Configuration class — reads everything from CW_BRIDGE__* env vars."""

    def __init__(self):
        env_tree = parse_env_tree("CW_BRIDGE")

        # -- App settings (CW_BRIDGE__app__*) --
        self.app_name = "Vital Chatwoot Bridge"
        self.debug = _get_bool(env_tree, "app", "debug", default=False)
        self.host = _get(env_tree, "app", "host", default="0.0.0.0")
        self.port = _get_int(env_tree, "app", "port", default=8000)
        self.log_level = _get(env_tree, "app", "log_level", default="INFO")
        self.log_format = _get(env_tree, "app", "log_format", default="text")
        self.environment = _get(env_tree, "app", "environment", default="development")
        cors_env = _get(env_tree, "app", "cors_allowed_origins", default="*")
        self.allowed_origins = [o.strip() for o in cors_env.split(",")]

        # -- Chatwoot (CW_BRIDGE__chatwoot__*) --
        self.chatwoot_base_url = _get(env_tree, "chatwoot", "base_url")
        self.chatwoot_user_access_token = _get(env_tree, "chatwoot", "user_access_token")
        self.chatwoot_account_id = _get(env_tree, "chatwoot", "account_id", default="1")
        self.enforce_webhook_signatures = _get_bool(env_tree, "chatwoot", "enforce_webhook_signatures", default=True)
        client_api = _get(env_tree, "chatwoot", "client_api_base_url")
        self.chatwoot_client_api_base_url = (
            client_api if client_api
            else f"{self.chatwoot_base_url.rstrip('/')}/public/api/v1" if self.chatwoot_base_url
            else ""
        )

        # -- Keycloak (CW_BRIDGE__keycloak__*) --
        self.keycloak_base_url = _get(env_tree, "keycloak", "base_url", default="http://localhost:8085")
        self.keycloak_realm = _get(env_tree, "keycloak", "realm")
        self.keycloak_client_id = _get(env_tree, "keycloak", "client_id")
        self.keycloak_client_secret = _get(env_tree, "keycloak", "client_secret")
        self.keycloak_user = _get(env_tree, "keycloak", "user")
        self.keycloak_password = _get(env_tree, "keycloak", "password")
        _allowed_azps_raw = _get(env_tree, "keycloak", "allowed_azps", default="")
        self.keycloak_allowed_azps: list[str] = [
            s.strip() for s in _allowed_azps_raw.split(",") if s.strip()
        ]

        # -- LoopMessage (CW_BRIDGE__loopmessage__*) --
        self.loopmessage_api_url = _get(env_tree, "loopmessage", "api_url", default="https://server.loopmessage.com/api/v1")
        self.loopmessage_authorization_key = _get(env_tree, "loopmessage", "authorization_key")
        self.loopmessage_secret_key = _get(env_tree, "loopmessage", "secret_key")
        self.loopmessage_sender_name = _get(env_tree, "loopmessage", "sender_name")

        # -- Timeouts (CW_BRIDGE__timeouts__*) --
        self.default_response_timeout = _get_int(env_tree, "timeouts", "response", default=30)
        self.max_sync_response_time = _get_int(env_tree, "timeouts", "max_sync", default=25)

        # -- WebSocket (CW_BRIDGE__websocket__*) --
        self.websocket_connect_timeout = _get_int(env_tree, "websocket", "connect_timeout", default=10)
        self.websocket_ping_interval = _get_int(env_tree, "websocket", "ping_interval", default=30)
        self.websocket_ping_timeout = _get_int(env_tree, "websocket", "ping_timeout", default=10)
        self.websocket_max_reconnect_attempts = _get_int(env_tree, "websocket", "max_reconnect_attempts", default=5)

        # -- Structured config sections --
        self.bots = self._parse_bots(env_tree.get("bots", {}))
        self.inbox_agent_mappings = self._parse_inbox_agents(env_tree.get("inbox_agents", {}))
        self.api_inboxes = self._parse_api_inboxes(env_tree.get("api_inboxes", {}))

        # -- AWS (CW_BRIDGE__aws__*) --
        self.aws_access_key_id = _get(env_tree, "aws", "access_key_id")
        self.aws_secret_access_key = _get(env_tree, "aws", "secret_access_key")
        self.aws_region = _get(env_tree, "aws", "region", default="us-east-1")

        # -- Mailgun (CW_BRIDGE__mailgun__*) --
        self.mailgun: Optional[MailgunConfig] = self._parse_mailgun(
            env_tree.get("mailgun", {})
        )

        # -- Email Templates (CW_BRIDGE__email_templates__*) --
        self.email_templates: Optional[EmailTemplatesConfig] = self._parse_email_templates(
            env_tree.get("email_templates", {})
        )

        # -- Google / Gmail (CW_BRIDGE__google__*) --
        self.google: Optional[GmailConfig] = self._parse_google(
            env_tree.get("google", {})
        )

        # -- MemoryDB (CW_BRIDGE__memorydb__*) --
        self.memorydb: Optional[MemoryDBConfig] = self._parse_memorydb(
            env_tree.get("memorydb", {})
        )

        # -- Debounce (CW_BRIDGE__debounce__*) --
        self.debounce: Optional[DebounceConfig] = self._parse_debounce(
            env_tree.get("debounce", {})
        )

        # -- Message Webhook (CW_BRIDGE__message_webhook__*) --
        self.message_webhook: Optional[MessageWebhookConfig] = self._parse_message_webhook(
            env_tree.get("message_webhook", {})
        )

        # -- URL Shortener (CW_BRIDGE__url_shortener__*) --
        self.url_shortener: Optional[URLShortenerConfig] = self._parse_url_shortener(
            env_tree.get("url_shortener", {})
        )

        # -- Zoom Phone SMS (CW_BRIDGE__zoom__*) --
        self.zoom: Optional[ZoomConfig] = self._parse_zoom(
            env_tree.get("zoom", {})
        )

        # -- Rate Limiting (CW_BRIDGE__rate_limiting__*) --
        rl = env_tree.get("rate_limiting", {})
        self.rl_queue_backend = _get(rl, "queue_backend", default="memory")  # "memory" or "redis"
        self.rl_redis_url = _get(rl, "redis_url")  # required when queue_backend=redis
        self.rl_redis_queue_key = _get(rl, "redis_queue_key", default="cw_bridge:attentive_queue")
        self.rl_max_chatwoot_concurrency = _get_int(rl, "max_chatwoot_concurrency", default=3)
        self.rl_attentive_workers = _get_int(rl, "attentive_workers", default=3)
        self.rl_attentive_queue_size = _get_int(rl, "attentive_queue_size", default=5000)
        self.rl_attentive_max_per_second = _get_float(rl, "attentive_max_per_second", default=1.5)
        allowed_events_str = _get(rl, "attentive_allowed_events", default="sms.sent,sms.inbound_message")
        self.rl_attentive_allowed_events = [e.strip() for e in allowed_events_str.split(",") if e.strip()]
        self.rl_contact_cache_ttl = _get_int(rl, "contact_cache_ttl", default=300)
        self.rl_retry_max_attempts = _get_int(rl, "retry_max_attempts", default=3)
        self.rl_retry_base_delay = _get_float(rl, "retry_base_delay", default=1.0)
        logger.info(
            f"📋 CONFIG: Rate limiting — backend={self.rl_queue_backend}, "
            f"concurrency={self.rl_max_chatwoot_concurrency}, "
            f"workers={self.rl_attentive_workers}, "
            f"max_per_second={self.rl_attentive_max_per_second}, "
            f"allowed_events={self.rl_attentive_allowed_events}"
        )

    # -------------------------------------------------------------------
    # Parsers for structured sections
    # -------------------------------------------------------------------

    @staticmethod
    def _parse_bots(bots_tree: Dict[str, Any]) -> Dict[str, BotConfig]:
        """Build BotConfig dict from CW_BRIDGE__bots__<name>__* env vars."""
        bots: Dict[str, BotConfig] = {}
        for bot_name, fields in bots_tree.items():
            if not isinstance(fields, dict):
                continue
            try:
                bots[bot_name] = BotConfig(**fields)
                logger.info(f"📋 CONFIG: Loaded bot '{bot_name}': {fields.get('name', bot_name)}")
            except Exception as e:
                logger.error(f"❌ CONFIG: Failed to parse bot config for '{bot_name}': {e}")
        logger.info(f"📋 CONFIG: {len(bots)} bot configurations loaded")
        return bots

    @staticmethod
    def _parse_inbox_agents(agents_tree: Dict[str, Any]) -> List[InboxMapping]:
        """Build InboxMapping list from CW_BRIDGE__inbox_agents__<id>__* env vars."""
        mappings: List[InboxMapping] = []
        for inbox_id, fields in agents_tree.items():
            if not isinstance(fields, dict):
                continue
            try:
                agent_fields = coerce_dict(fields)
                inbox_name = agent_fields.pop("inbox_name", "")
                aimp_intent_type = agent_fields.pop("aimp_intent_type", "http://vital.ai/ontology/vital-aimp#AIMPIntentType_CHAT")
                from_email = agent_fields.pop("from_email", None)
                from_phone = agent_fields.pop("from_phone", None)
                agent_config = AgentConfig(**agent_fields)
                mappings.append(InboxMapping(
                    inbox_id=inbox_id,
                    inbox_name=inbox_name,
                    aimp_intent_type=aimp_intent_type,
                    from_email=from_email,
                    from_phone=from_phone,
                    agent_config=agent_config,
                ))
                logger.info(f"📋 CONFIG: Loaded inbox agent mapping: inbox {inbox_id} → {agent_config.agent_id}")
            except Exception as e:
                logger.error(f"❌ CONFIG: Failed to parse inbox agent mapping for inbox {inbox_id}: {e}")
        logger.info(f"📋 CONFIG: {len(mappings)} inbox agent mappings loaded")
        return mappings

    @staticmethod
    def _parse_api_inboxes(inboxes_tree: Dict[str, Any]) -> Dict[str, APIInboxConfig]:
        """Build APIInboxConfig dict from CW_BRIDGE__api_inboxes__<type>__* env vars."""
        api_inboxes: Dict[str, APIInboxConfig] = {}
        for inbox_type, fields in inboxes_tree.items():
            if not isinstance(fields, dict):
                continue
            try:
                prepared = dict(fields)
                # Handle comma-separated list fields
                if "message_types" in prepared and isinstance(prepared["message_types"], str):
                    prepared["message_types"] = [t.strip() for t in prepared["message_types"].split(",")]
                # Handle boolean fields (Pydantic strict mode won't coerce strings)
                for bool_field in ("supports_outbound", "supports_email_replies"):
                    if bool_field in prepared and isinstance(prepared[bool_field], str):
                        prepared[bool_field] = prepared[bool_field].lower() == "true"
                api_inboxes[inbox_type] = APIInboxConfig(**prepared)
                logger.info(f"📋 CONFIG: Loaded API inbox '{inbox_type}': {prepared.get('name', 'Unknown')}")
            except Exception as e:
                logger.error(f"❌ CONFIG: Failed to parse API inbox config for '{inbox_type}': {e}")
        logger.info(f"📋 CONFIG: {len(api_inboxes)} API inbox configurations loaded")
        return api_inboxes

    @staticmethod
    def _parse_mailgun(mg_tree: Dict[str, Any]) -> Optional[MailgunConfig]:
        """Build MailgunConfig from CW_BRIDGE__mailgun__* env vars."""
        if not isinstance(mg_tree, dict) or "api_key" not in mg_tree:
            return None
        try:
            config = MailgunConfig(**mg_tree)
            logger.info(
                f"📧 CONFIG: Mailgun configured — domain={config.domain}, "
                f"from={config.from_email}"
            )
            return config
        except Exception as e:
            logger.error(f"❌ CONFIG: Failed to parse Mailgun config: {e}")
            return None

    @staticmethod
    def _parse_email_templates(tpl_tree: Dict[str, Any]) -> Optional[EmailTemplatesConfig]:
        """Build EmailTemplatesConfig from CW_BRIDGE__email_templates__* env vars."""
        if not isinstance(tpl_tree, dict) or "s3_bucket" not in tpl_tree:
            return None
        try:
            # Convert nested template dicts into EmailTemplateDef instances
            raw_templates = tpl_tree.get("templates", {})
            parsed_templates: Dict[str, EmailTemplateDef] = {}
            if isinstance(raw_templates, dict):
                for name, fields in raw_templates.items():
                    if isinstance(fields, dict):
                        parsed_templates[name] = EmailTemplateDef(**fields)

            config = EmailTemplatesConfig(
                s3_bucket=tpl_tree["s3_bucket"],
                s3_region=tpl_tree.get("s3_region", "us-east-1"),
                asset_base_url=tpl_tree.get("asset_base_url", ""),
                defaults=tpl_tree.get("defaults", {}),
                templates=parsed_templates,
            )
            logger.info(
                f"📧 CONFIG: Email templates configured — bucket={config.s3_bucket}, "
                f"{len(config.templates)} template(s)"
            )
            return config
        except Exception as e:
            logger.error(f"❌ CONFIG: Failed to parse email templates config: {e}")
            return None

    @staticmethod
    def _parse_google(google_tree: Dict[str, Any]) -> Optional[GmailConfig]:
        """Build GmailConfig from CW_BRIDGE__google__* env vars."""
        if not isinstance(google_tree, dict):
            return None
        sa_json = google_tree.get("service_account_json")
        if not sa_json:
            return None
        try:
            sa_info = json.loads(sa_json) if isinstance(sa_json, str) else sa_json

            senders: Dict[str, GmailSender] = {}
            for name, fields in google_tree.get("senders", {}).items():
                if isinstance(fields, dict):
                    prepared = dict(fields)
                    if "default_inbox_id" in prepared and isinstance(prepared["default_inbox_id"], str):
                        prepared["default_inbox_id"] = int(prepared["default_inbox_id"])
                    senders[name] = GmailSender(**prepared)

            tracking_tree = google_tree.get("tracking", {})
            tracking = GmailTrackingConfig(
                pixel_url=tracking_tree.get("pixel_url", "") if isinstance(tracking_tree, dict) else "",
                click_url=tracking_tree.get("click_url", "") if isinstance(tracking_tree, dict) else "",
                default_campaign=tracking_tree.get("default_campaign", "") if isinstance(tracking_tree, dict) else "",
            )

            config = GmailConfig(
                service_account_info=sa_info,
                senders=senders,
                tracking=tracking,
            )
            sender_emails = [s.email for s in senders.values()]
            logger.info(
                f"📧 CONFIG: Google/Gmail configured — "
                f"{len(senders)} sender(s): {sender_emails}"
            )
            return config
        except Exception as e:
            logger.error(f"❌ CONFIG: Failed to parse Google config: {e}")
            return None

    @staticmethod
    def _parse_memorydb(tree: Dict[str, Any]) -> Optional[MemoryDBConfig]:
        """Build MemoryDBConfig from CW_BRIDGE__memorydb__* env vars."""
        if not isinstance(tree, dict) or "url" not in tree:
            return None
        try:
            prepared = dict(tree)
            if "ssl" in prepared and isinstance(prepared["ssl"], str):
                prepared["ssl"] = prepared["ssl"].lower() == "true"
            config = MemoryDBConfig(**prepared)
            logger.info(f"🗄️  CONFIG: MemoryDB configured — ssl={config.ssl}")
            return config
        except Exception as e:
            logger.error(f"❌ CONFIG: Failed to parse MemoryDB config: {e}")
            return None

    @staticmethod
    def _parse_debounce(tree: Dict[str, Any]) -> Optional[DebounceConfig]:
        """Build DebounceConfig from CW_BRIDGE__debounce__* env vars."""
        if not isinstance(tree, dict):
            return None
        try:
            prepared = dict(tree)
            if "enabled" in prepared and isinstance(prepared["enabled"], str):
                prepared["enabled"] = prepared["enabled"].lower() == "true"
            for float_field in ("window_seconds", "max_window_seconds", "drain_poll_interval"):
                if float_field in prepared and isinstance(prepared[float_field], str):
                    prepared["" + float_field] = float(prepared[float_field])
            for int_field in ("max_batch_size", "dedup_ttl_seconds"):
                if int_field in prepared and isinstance(prepared[int_field], str):
                    prepared[int_field] = int(prepared[int_field])
            if "sms_inbox_ids" in prepared and isinstance(prepared["sms_inbox_ids"], str):
                prepared["sms_inbox_ids"] = [s.strip() for s in prepared["sms_inbox_ids"].split(",") if s.strip()]
            config = DebounceConfig(**prepared)
            logger.info(
                f"⏱️  CONFIG: Debounce configured — enabled={config.enabled}, "
                f"window={config.window_seconds}s, max_window={config.max_window_seconds}s, "
                f"poll_interval={config.drain_poll_interval}s"
            )
            return config
        except Exception as e:
            logger.error(f"❌ CONFIG: Failed to parse debounce config: {e}")
            return None

    @staticmethod
    def _parse_message_webhook(tree: Dict[str, Any]) -> Optional[MessageWebhookConfig]:
        """Build MessageWebhookConfig from CW_BRIDGE__message_webhook__* env vars."""
        if not isinstance(tree, dict) or "url" not in tree:
            return None
        try:
            prepared = dict(tree)
            if "enabled" in prepared and isinstance(prepared["enabled"], str):
                prepared["enabled"] = prepared["enabled"].lower() == "true"
            for int_field in ("timeout_seconds", "max_retries", "retry_delay_seconds"):
                if int_field in prepared and isinstance(prepared[int_field], str):
                    prepared[int_field] = int(prepared[int_field])
            config = MessageWebhookConfig(**prepared)
            logger.info(
                f"📋 CONFIG: Message webhook configured — "
                f"url={config.url}, enabled={config.enabled}"
            )
            return config
        except Exception as e:
            logger.error(f"❌ CONFIG: Failed to parse message webhook config: {e}")
            return None

    @staticmethod
    def _parse_url_shortener(tree: Dict[str, Any]) -> Optional[URLShortenerConfig]:
        """Build URLShortenerConfig from CW_BRIDGE__url_shortener__* env vars."""
        if not isinstance(tree, dict) or "api_key" not in tree:
            return None
        try:
            prepared = dict(tree)
            # Handle boolean fields
            for bool_field in ("enabled", "sms_only"):
                if bool_field in prepared and isinstance(prepared[bool_field], str):
                    prepared[bool_field] = prepared[bool_field].lower() == "true"
            # Handle comma-separated sms_inbox_ids
            if "sms_inbox_ids" in prepared and isinstance(prepared["sms_inbox_ids"], str):
                prepared["sms_inbox_ids"] = [s.strip() for s in prepared["sms_inbox_ids"].split(",") if s.strip()]
            config = URLShortenerConfig(**prepared)
            logger.info(
                f"🔗 CONFIG: URL shortener configured — provider={config.provider}, "
                f"domain={config.domain}, enabled={config.enabled}"
            )
            return config
        except Exception as e:
            logger.error(f"❌ CONFIG: Failed to parse URL shortener config: {e}")
            return None

    @staticmethod
    def _parse_zoom(zoom_tree: Dict[str, Any]) -> Optional[ZoomConfig]:
        """Build ZoomConfig from CW_BRIDGE__zoom__* env vars."""
        if not isinstance(zoom_tree, dict):
            return None
        # Require at minimum client_id to consider Zoom configured
        oauth_tree = zoom_tree.get("oauth", {})
        if not isinstance(oauth_tree, dict) or "client_id" not in oauth_tree:
            return None
        try:
            oauth = ZoomOAuthConfig(
                client_id=oauth_tree["client_id"],
                client_secret=oauth_tree.get("client_secret", ""),
                redirect_uri=oauth_tree.get("redirect_uri", ""),
            )

            accounts: Dict[str, ZoomAccount] = {}
            for name, fields in zoom_tree.get("accounts", {}).items():
                if isinstance(fields, dict):
                    prepared = dict(fields)
                    if "enabled" in prepared and isinstance(prepared["enabled"], str):
                        prepared["enabled"] = prepared["enabled"].lower() == "true"
                    accounts[name] = ZoomAccount(**prepared)

            storage_tree = zoom_tree.get("token_storage", {})
            token_storage = ZoomTokenStorageConfig(
                backend=storage_tree.get("backend", "secrets_manager") if isinstance(storage_tree, dict) else "secrets_manager",
                secret_prefix=storage_tree.get("secret_prefix", "vital-bridge/zoom-tokens/") if isinstance(storage_tree, dict) else "vital-bridge/zoom-tokens/",
            )

            refresh_tree = zoom_tree.get("token_refresh", {})
            token_refresh = ZoomTokenRefreshConfig(
                refresh_interval_minutes=int(refresh_tree.get("refresh_interval_minutes", 30)) if isinstance(refresh_tree, dict) else 30,
                refresh_buffer_minutes=int(refresh_tree.get("refresh_buffer_minutes", 15)) if isinstance(refresh_tree, dict) else 15,
                weekly_force_refresh=refresh_tree.get("weekly_force_refresh", "true").lower() == "true" if isinstance(refresh_tree, dict) else True,
            )

            config = ZoomConfig(
                oauth=oauth,
                accounts=accounts,
                token_storage=token_storage,
                token_refresh=token_refresh,
            )
            account_names = list(accounts.keys())
            logger.info(
                f"\U0001f4f1 CONFIG: Zoom Phone SMS configured \u2014 "
                f"{len(accounts)} account(s): {account_names}"
            )
            return config
        except Exception as e:
            logger.error(f"\u274c CONFIG: Failed to parse Zoom config: {e}")
            return None

    # -------------------------------------------------------------------
    # Lookup helpers
    # -------------------------------------------------------------------

    def get_agent_for_inbox(self, inbox_id: str) -> Optional[AgentConfig]:
        """Get the AI agent configuration for a specific inbox."""
        for mapping in self.inbox_agent_mappings:
            if mapping.inbox_id == inbox_id:
                return mapping.agent_config
        return None

    def get_inbox_mapping(self, inbox_id: str) -> Optional[InboxMapping]:
        """Get the full InboxMapping (including inbox_name) for a specific inbox."""
        for mapping in self.inbox_agent_mappings:
            if mapping.inbox_id == inbox_id:
                return mapping
        return None

    def get_webhook_secret_for_inbox(self, inbox_id: str) -> Optional[str]:
        """Look up inbox → bot → access_token for webhook signature verification."""
        agent_config = self.get_agent_for_inbox(inbox_id)
        if agent_config and agent_config.bot:
            bot = self.bots.get(agent_config.bot)
            if bot:
                return bot.access_token
        return None

    def get_api_inbox_config(self, inbox_type: str) -> Optional[APIInboxConfig]:
        """Get the API inbox configuration for a specific inbox type."""
        return self.api_inboxes.get(inbox_type)

    def get_api_inbox_by_identifier(self, inbox_identifier: str) -> Optional[APIInboxConfig]:
        """Get the API inbox configuration by Chatwoot inbox identifier."""
        for config in self.api_inboxes.values():
            if config.inbox_identifier == inbox_identifier:
                return config
        return None

    def get_api_inbox_by_chatwoot_id(self, chatwoot_inbox_id: str) -> Optional[APIInboxConfig]:
        """Get the API inbox configuration by Chatwoot internal inbox ID."""
        for config in self.api_inboxes.values():
            if config.chatwoot_inbox_id == chatwoot_inbox_id:
                return config
        return None

    def is_sms_inbox(self, inbox_id: str) -> bool:
        """Return True if *inbox_id* is configured as an SMS/Twilio inbox."""
        if self.url_shortener and self.url_shortener.sms_inbox_ids:
            return str(inbox_id) in self.url_shortener.sms_inbox_ids
        return False


@lru_cache()
def get_settings() -> Config:
    """Get cached application settings."""
    return Config()
