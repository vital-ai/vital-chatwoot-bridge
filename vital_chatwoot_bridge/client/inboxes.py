"""
Inboxes mixin for the Chatwoot Bridge client.
"""

from typing import Optional

from vital_chatwoot_bridge.client.models import SingleResponse


class InboxesMixin:
    """Methods for /api/v1/chatwoot/inboxes endpoints."""

    async def list_inboxes(self) -> SingleResponse:
        """List all inboxes in the account."""
        data = await self.get("/api/v1/chatwoot/inboxes")
        return SingleResponse(**data)

    async def list_inbound_messages(
        self,
        inbox_id: int,
        before: Optional[int] = None,
        limit: int = 10,
        status: Optional[str] = None,
    ) -> SingleResponse:
        """List recent inbound messages for an inbox with cursor pagination.

        Args:
            inbox_id: Chatwoot inbox ID.
            before: Message ID cursor — return messages older than this.
            limit: Max messages per page (default 50, max 200).
            status: Conversation status filter (open, resolved, pending).
        """
        params = {"limit": limit}
        if before is not None:
            params["before"] = before
        if status:
            params["status"] = status
        data = await self.get(f"/api/v1/chatwoot/inboxes/{inbox_id}/messages/inbound", params=params)
        return SingleResponse(**data)
