"""
Background worker that periodically refreshes Zoom OAuth tokens.

Ensures tokens stay alive without manual intervention. Key behaviors:
- Checks all accounts on a configurable interval (default 30 min)
- Refreshes tokens that will expire within buffer_minutes
- Force-refreshes all tokens weekly to prevent 90-day refresh token expiry
- Alerts (logs error) on refresh failure so we can investigate
"""

import asyncio
import logging
import time
from datetime import datetime, timezone

from vital_chatwoot_bridge.zoom.models import ZoomConfig, ZoomTokenRefreshConfig
from vital_chatwoot_bridge.zoom.oauth import ZoomOAuthManager, ZoomOAuthError
from vital_chatwoot_bridge.zoom.token_store import ZoomTokenStore

logger = logging.getLogger(__name__)

# Refresh all tokens at least once per week (seconds)
WEEKLY_SECONDS = 7 * 24 * 60 * 60


class ZoomTokenRefreshWorker:
    """
    Async background task that keeps Zoom OAuth tokens alive.
    """

    def __init__(
        self,
        config: ZoomConfig,
        oauth_manager: ZoomOAuthManager,
        token_store: ZoomTokenStore,
    ):
        self.config = config
        self.refresh_config: ZoomTokenRefreshConfig = config.token_refresh
        self.oauth_manager = oauth_manager
        self.token_store = token_store
        self._task: asyncio.Task | None = None
        self._last_weekly_refresh: float = 0.0

    def start(self) -> None:
        """Start the background refresh loop."""
        if self._task is not None:
            logger.warning("Zoom token refresh worker already running")
            return
        self._task = asyncio.create_task(self._run_loop())
        logger.info(
            f"🔄 Zoom token refresh worker started "
            f"(interval={self.refresh_config.refresh_interval_minutes}m, "
            f"buffer={self.refresh_config.refresh_buffer_minutes}m)"
        )

    async def stop(self) -> None:
        """Stop the background refresh loop."""
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
            logger.info("🔄 Zoom token refresh worker stopped")

    async def _run_loop(self) -> None:
        """Main loop — runs indefinitely until cancelled."""
        interval_seconds = self.refresh_config.refresh_interval_minutes * 60
        while True:
            try:
                await self._refresh_all_accounts()
            except Exception as e:
                logger.error(f"❌ Zoom refresh worker error: {e}", exc_info=True)

            await asyncio.sleep(interval_seconds)

    async def _refresh_all_accounts(self) -> None:
        """Check all configured accounts and refresh as needed."""
        now = time.time()
        force_weekly = (
            self.refresh_config.weekly_force_refresh
            and (now - self._last_weekly_refresh) >= WEEKLY_SECONDS
        )

        if force_weekly:
            logger.info("🔄 Weekly force-refresh of all Zoom tokens")
            self._last_weekly_refresh = now

        account_names = list(self.config.accounts.keys())
        refreshed = 0
        failed = 0

        for account_name in account_names:
            account = self.config.accounts[account_name]
            if not account.enabled:
                continue

            token = self.token_store.get_token(account_name)
            if token is None:
                logger.warning(
                    f"⚠️ Zoom account '{account_name}' has no token — needs authorization"
                )
                continue

            needs_refresh = (
                force_weekly
                or self.token_store.is_token_expired(
                    token, self.refresh_config.refresh_buffer_minutes
                )
            )

            if needs_refresh:
                try:
                    await self.oauth_manager.refresh_token(account_name)
                    refreshed += 1
                except ZoomOAuthError as e:
                    failed += 1
                    logger.error(
                        f"🚨 ALERT: Failed to refresh Zoom token for '{account_name}': {e}. "
                        f"This account may need manual re-authorization!"
                    )

        if refreshed > 0 or failed > 0:
            logger.info(
                f"🔄 Zoom token refresh cycle complete: "
                f"{refreshed} refreshed, {failed} failed, "
                f"{len(account_names)} total accounts"
            )
