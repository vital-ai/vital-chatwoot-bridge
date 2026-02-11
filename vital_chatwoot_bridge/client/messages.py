"""
Messages mixin for the Chatwoot Bridge client.
"""

from typing import Any, Dict, Optional

from vital_chatwoot_bridge.client.models import SingleResponse


class MessagesMixin:
    """Methods for /api/v1/chatwoot/messages and conversation message endpoints."""

    async def list_messages(self, conversation_id: int) -> SingleResponse:
        """List messages for a conversation."""
        data = await self.get(
            f"/api/v1/chatwoot/conversations/{conversation_id}/messages"
        )
        return SingleResponse(**data)

    async def get_message(
        self, conversation_id: int, message_id: int
    ) -> SingleResponse:
        """Get a single message with delivery status."""
        data = await self.get(
            f"/api/v1/chatwoot/conversations/{conversation_id}/messages/{message_id}"
        )
        return SingleResponse(**data)

    async def delete_message(
        self, conversation_id: int, message_id: int
    ) -> SingleResponse:
        """Delete a message."""
        data = await self.delete(
            f"/api/v1/chatwoot/conversations/{conversation_id}/messages/{message_id}"
        )
        return SingleResponse(**data)

    async def post_message(
        self,
        direction: str,
        contact_identifier: str,
        message_content: str,
        inbox_id: int,
        contact_name: Optional[str] = None,
        contact_email: Optional[str] = None,
        contact_phone: Optional[str] = None,
        content_type: str = "text",
        conversation_id: Optional[int] = None,
        conversation_mode: str = "reuse_newest",
        suppress_delivery: bool = False,
        to_emails: Optional[str] = None,
        cc_emails: Optional[str] = None,
        bcc_emails: Optional[str] = None,
    ) -> SingleResponse:
        """
        Post a message (inbound or outbound) to any inbox.

        Args:
            direction: 'inbound' or 'outbound'
            contact_identifier: Unique contact ID (phone or email)
            message_content: Message body text
            inbox_id: Inbox ID
            contact_name: Display name
            contact_email: Contact email
            contact_phone: Contact phone number
            content_type: 'text' or 'html'
            conversation_id: Explicit conversation ID (overrides conversation_mode)
            conversation_mode: 'reuse_newest' (default) or 'create_new'
            suppress_delivery: Log only, do not dispatch (outbound only)
            to_emails: Explicit email recipients, comma-separated
            cc_emails: CC recipients, comma-separated
            bcc_emails: BCC recipients, comma-separated
        """
        payload: Dict[str, Any] = {
            "direction": direction,
            "inbox_id": inbox_id,
            "contact": {
                "identifier": contact_identifier,
            },
            "message": {
                "content": message_content,
                "content_type": content_type,
            },
        }
        if contact_name:
            payload["contact"]["name"] = contact_name
        if contact_email:
            payload["contact"]["email"] = contact_email
        if contact_phone:
            payload["contact"]["phone_number"] = contact_phone
        if conversation_id is not None:
            payload["conversation_id"] = conversation_id
        if conversation_mode != "reuse_newest":
            payload["conversation_mode"] = conversation_mode
        if suppress_delivery:
            payload["suppress_delivery"] = True
        if to_emails:
            payload["to_emails"] = to_emails
        if cc_emails:
            payload["cc_emails"] = cc_emails
        if bcc_emails:
            payload["bcc_emails"] = bcc_emails

        data = await self.post("/api/v1/chatwoot/messages", json=payload)
        return SingleResponse(**data)
