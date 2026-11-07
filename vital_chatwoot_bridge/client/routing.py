"""The bridge's routing API for the Chatwoot Bridge client: routes, pausing an inbox, reloading, retrying a message."""

from typing import Any, Dict, Optional

R = "/api/v1"


class RoutingMixin:
    async def routes(self) -> Dict[str, Any]:
        """Every route with its pause state, the account mode and where the routes came from."""
        return await self.get(f"{R}/routes")

    async def reload_routes(self) -> Dict[str, Any]:
        """Read the route files again; a file that doesn't validate changes nothing (ValidationError)."""
        return await self.post(f"{R}/routes/reload")

    async def pause_inbox(self, account_id: int, inbox_id: int, by: str, reason: str) -> Dict[str, Any]:
        return await self.post(f"{R}/routes/{account_id}/{inbox_id}/pause", json={"by": by, "reason": reason})

    async def resume_inbox(self, account_id: int, inbox_id: int, by: str) -> Dict[str, Any]:
        return await self.post(f"{R}/routes/{account_id}/{inbox_id}/resume", json={"by": by})

    async def retry_delivery(self, message_id: int, conversation_id: int,
                             account_id: Optional[int] = None) -> Dict[str, Any]:
        """Hand one incoming message to its inbox's agent again."""
        return await self.post(f"{R}/deliveries/{message_id}/retry",
                               json={"account_id": account_id, "conversation_id": conversation_id})

    async def status(self) -> Dict[str, Any]:
        return await self.get("/status")
