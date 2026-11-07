"""Conversation operations for the Chatwoot Bridge client: notes, replies, labels, status, assignment, contact lookup,
attachments and recent inbound messages. Use ``client.for_account(account_id)`` when the bridge runs in multi-account
mode."""

from datetime import datetime
from typing import Any, Dict, List, Optional

import httpx

from vital_chatwoot_bridge.client.models import PaginatedResponse, SingleResponse

P = "/api/v1/chatwoot"


class SupportOpsMixin:
    async def add_note(self, conversation_id: int, content: str, content_attributes: Optional[Dict[str, Any]] = None,
                       idempotency_key: Optional[str] = None) -> SingleResponse:
        """A private note: staff see it in Chatwoot, the contact never does. A repeat with the same key writes nothing."""
        body: Dict[str, Any] = {"content": content}
        if content_attributes:
            body["content_attributes"] = content_attributes
        data = await self.post(f"{P}/conversations/{conversation_id}/notes", json=body,
                               headers={"Idempotency-Key": idempotency_key} if idempotency_key else None)
        return SingleResponse(**data)

    async def reply(self, conversation_id: int, content: str, content_attributes: Optional[Dict[str, Any]] = None,
                    idempotency_key: Optional[str] = None) -> SingleResponse:
        """A reply to the contact through the conversation's inbox. With a key, it's never sent twice."""
        body: Dict[str, Any] = {"content": content}
        if content_attributes:
            body["content_attributes"] = content_attributes
        data = await self.post(f"{P}/conversations/{conversation_id}/replies", json=body,
                               headers={"Idempotency-Key": idempotency_key} if idempotency_key else None)
        return SingleResponse(**data)

    async def labels(self, conversation_id: int) -> List[str]:
        return (await self.get(f"{P}/conversations/{conversation_id}/labels"))["data"]["labels"]

    async def add_labels(self, conversation_id: int, labels: List[str]) -> List[str]:
        return (await self.post(f"{P}/conversations/{conversation_id}/labels", json={"labels": labels}))["data"]["labels"]

    async def remove_label(self, conversation_id: int, label: str) -> List[str]:
        return (await self.delete(f"{P}/conversations/{conversation_id}/labels/{label}"))["data"]["labels"]

    async def set_status(self, conversation_id: int, status: str, snoozed_until: Optional[int] = None) -> SingleResponse:
        """open, pending, resolved or snoozed."""
        body: Dict[str, Any] = {"status": status}
        if snoozed_until is not None:
            body["snoozed_until"] = snoozed_until
        return SingleResponse(**await self.post(f"{P}/conversations/{conversation_id}/status", json=body))

    async def assign(self, conversation_id: int, assignee_id: Optional[int] = None,
                     team_id: Optional[int] = None) -> SingleResponse:
        body = {k: v for k, v in (("assignee_id", assignee_id), ("team_id", team_id)) if v is not None}
        return SingleResponse(**await self.post(f"{P}/conversations/{conversation_id}/assignee", json=body))

    async def find_contacts(self, email: Optional[str] = None, vital_member_id: Optional[str] = None,
                            page: int = 1) -> PaginatedResponse:
        """Contacts matching an email, or the vital_member_id custom attribute, exactly."""
        params: Dict[str, Any] = {"page": page}
        if email:
            params["email"] = email
        if vital_member_id:
            params["vital_member_id"] = vital_member_id
        return PaginatedResponse(**await self.get(f"{P}/contacts", params=params))

    async def open_attachment(self, conversation_id: int, message_id: int, attachment_id: int) -> httpx.Response:
        """The attachment's bytes, streamed: read ``aiter_bytes()``, then ``aclose()``."""
        return await self.stream(f"{P}/conversations/{conversation_id}/messages/{message_id}/attachments/{attachment_id}")

    async def inbound_messages(self, inbox_id: int, since: Optional[datetime] = None, before: Optional[int] = None,
                               limit: int = 50) -> SingleResponse:
        params: Dict[str, Any] = {"limit": limit}
        if since:
            params["since"] = since.isoformat()
        if before:
            params["before"] = before
        return SingleResponse(**await self.get(f"{P}/inboxes/{inbox_id}/messages/inbound", params=params))
