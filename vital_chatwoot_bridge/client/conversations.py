"""
Conversations mixin for the Chatwoot Bridge client.
"""

from typing import Any, Dict, Optional

from vital_chatwoot_bridge.client.models import PaginatedResponse, SingleResponse


class ConversationsMixin:
    """Methods for /api/v1/chatwoot/conversations endpoints."""

    async def list_conversations(
        self,
        page: int = 1,
        status: Optional[str] = None,
        assignee_type: Optional[str] = None,
    ) -> PaginatedResponse:
        """List conversations (paginated, filterable by status)."""
        params: Dict[str, Any] = {"page": page}
        if status:
            params["status"] = status
        if assignee_type:
            params["assignee_type"] = assignee_type
        data = await self.get("/api/v1/chatwoot/conversations", params=params)
        return PaginatedResponse(**data)

    async def get_conversation(self, conversation_id: int) -> SingleResponse:
        """Get conversation details."""
        data = await self.get(f"/api/v1/chatwoot/conversations/{conversation_id}")
        return SingleResponse(**data)

    async def conversation_count(self) -> SingleResponse:
        """Get conversation counts by status."""
        data = await self.get("/api/v1/chatwoot/conversations/count")
        return SingleResponse(**data)

    async def update_conversation(
        self,
        conversation_id: int,
        status: Optional[str] = None,
        assignee_id: Optional[int] = None,
        team_id: Optional[int] = None,
        label: Optional[str] = None,
        custom_attributes: Optional[Dict[str, Any]] = None,
    ) -> SingleResponse:
        """Update a conversation (status, assignee, etc.)."""
        payload: Dict[str, Any] = {}
        if status is not None:
            payload["status"] = status
        if assignee_id is not None:
            payload["assignee_id"] = assignee_id
        if team_id is not None:
            payload["team_id"] = team_id
        if label is not None:
            payload["label"] = label
        if custom_attributes is not None:
            payload["custom_attributes"] = custom_attributes
        data = await self.post(f"/api/v1/chatwoot/conversations/{conversation_id}", json=payload)
        return SingleResponse(**data)

    async def account_summary(self) -> SingleResponse:
        """Get account summary: contacts, conversations, agents, inboxes."""
        data = await self.get("/api/v1/chatwoot/account/summary")
        return SingleResponse(**data)

    async def delete_conversation(self, conversation_id: int) -> SingleResponse:
        """Delete a conversation by ID."""
        data = await self.delete(f"/api/v1/chatwoot/conversations/{conversation_id}")
        return SingleResponse(**data)

    async def create_conversation(
        self,
        inbox_id: int,
        contact_id: int,
        source_id: Optional[str] = None,
        custom_attributes: Optional[Dict[str, Any]] = None,
    ) -> SingleResponse:
        """Create a new conversation."""
        payload: Dict[str, Any] = {
            "inbox_id": inbox_id,
            "contact_id": contact_id,
        }
        if source_id:
            payload["source_id"] = source_id
        if custom_attributes:
            payload["custom_attributes"] = custom_attributes
        data = await self.post("/api/v1/chatwoot/conversations", json=payload)
        return SingleResponse(**data)
