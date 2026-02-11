"""
Inboxes mixin for the Chatwoot Bridge client.
"""

from vital_chatwoot_bridge.client.models import SingleResponse


class InboxesMixin:
    """Methods for /api/v1/chatwoot/inboxes endpoints."""

    async def list_inboxes(self) -> SingleResponse:
        """List all inboxes in the account."""
        data = await self.get("/api/v1/chatwoot/inboxes")
        return SingleResponse(**data)
