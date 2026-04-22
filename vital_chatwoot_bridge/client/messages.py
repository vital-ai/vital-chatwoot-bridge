"""
Messages mixin for the Chatwoot Bridge client.
"""

from typing import Any, Dict, List, Optional

from vital_chatwoot_bridge.client.models import SingleResponse


class MessagesMixin:
    """Methods for /api/v1/chatwoot/messages and conversation message endpoints."""

    async def list_messages(
        self, conversation_id: int, before: Optional[int] = None
    ) -> SingleResponse:
        """List messages for a conversation."""
        params = {}
        if before is not None:
            params["before"] = before
        data = await self.get(
            f"/api/v1/chatwoot/conversations/{conversation_id}/messages",
            params=params or None,
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
        subject: Optional[str] = None,
        conversation_id: Optional[int] = None,
        conversation_mode: str = "reuse_newest",
        suppress_delivery: bool = False,
        to_emails: Optional[str] = None,
        cc_emails: Optional[str] = None,
        bcc_emails: Optional[str] = None,
        attachments: Optional[List[Dict[str, Any]]] = None,
        content_attributes: Optional[Dict[str, Any]] = None,
        content_mode: str = "text",
        template_name: Optional[str] = None,
        template_vars: Optional[Dict[str, Any]] = None,
        from_email: Optional[str] = None,
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
            subject: Email subject line (email inboxes only)
            conversation_id: Explicit conversation ID (overrides conversation_mode)
            conversation_mode: 'reuse_newest' (default) or 'create_new'
            suppress_delivery: Log only, do not dispatch (outbound only)
            to_emails: Explicit email recipients, comma-separated
            cc_emails: CC recipients, comma-separated
            bcc_emails: BCC recipients, comma-separated
            attachments: List of attachment dicts with 'filename', 'content_type',
                and either 'data' (base64) or 'url'
            content_attributes: Optional dict for Chatwoot content_attributes
                (e.g. {"email": {"html_content": {"reply": "<html>..."}}})
            content_mode: 'text', 'markdown', 'html', or 'template'.
                For 'html'/'template', email is sent via Mailgun and recorded in Chatwoot.
            template_name: Jinja2 template name (required when content_mode='template')
            template_vars: Template variables (used when content_mode='template')
            from_email: Sender address override (Mailgun html/template modes only)
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
        if subject:
            payload["subject"] = subject
        if to_emails:
            payload["to_emails"] = to_emails
        if cc_emails:
            payload["cc_emails"] = cc_emails
        if bcc_emails:
            payload["bcc_emails"] = bcc_emails
        if attachments:
            payload["attachments"] = attachments
        if content_attributes:
            payload["content_attributes"] = content_attributes
        if content_mode != "text":
            payload["content_mode"] = content_mode
        if template_name:
            payload["template_name"] = template_name
        if template_vars:
            payload["template_vars"] = template_vars
        if from_email:
            payload["from_email"] = from_email

        data = await self.post("/api/v1/chatwoot/messages", json=payload)
        return SingleResponse(**data)

    async def send_sms(
        self,
        phone: str,
        message: str,
        inbox_id: int,
        contact_name: Optional[str] = None,
    ) -> SingleResponse:
        """
        Convenience method to send an SMS message.

        Args:
            phone: Recipient phone number (used as contact identifier)
            message: SMS message body
            inbox_id: Twilio SMS inbox ID (required, no default)
            contact_name: Optional display name for the contact
        """
        return await self.post_message(
            direction="outbound",
            contact_identifier=phone,
            contact_phone=phone,
            contact_name=contact_name,
            message_content=message,
            inbox_id=inbox_id,
        )

    async def send_email(
        self,
        to: str,
        body: str,
        inbox_id: int,
        subject: Optional[str] = None,
        content_type: str = "text",
        content_mode: str = "text",
        contact_name: Optional[str] = None,
        cc_emails: Optional[str] = None,
        bcc_emails: Optional[str] = None,
        attachments: Optional[List[Dict[str, Any]]] = None,
        template_name: Optional[str] = None,
        template_vars: Optional[Dict[str, Any]] = None,
    ) -> SingleResponse:
        """
        Convenience method to send an email message.

        Args:
            to: Recipient email address (used as contact identifier)
            body: Email body (plain text, markdown, or HTML depending on content_mode)
            inbox_id: Email inbox ID (required, no default)
            subject: Email subject line
            content_type: 'text' or 'html' (Chatwoot content_type)
            content_mode: 'text', 'markdown', 'html', or 'template'
            contact_name: Optional display name for the contact
            cc_emails: CC recipients, comma-separated
            bcc_emails: BCC recipients, comma-separated
            attachments: List of attachment dicts with 'filename', 'content_type',
                and either 'data' (base64) or 'url'
            template_name: Jinja2 template name (required when content_mode='template')
            template_vars: Template variables (used when content_mode='template')
        """
        return await self.post_message(
            direction="outbound",
            contact_identifier=to,
            contact_email=to,
            contact_name=contact_name,
            message_content=body,
            inbox_id=inbox_id,
            subject=subject,
            content_type=content_type,
            content_mode=content_mode,
            to_emails=to,
            cc_emails=cc_emails,
            bcc_emails=bcc_emails,
            attachments=attachments,
            template_name=template_name,
            template_vars=template_vars,
        )

    async def send_templated_email(
        self,
        template_name: str,
        to: str,
        inbox_id: int,
        subject: Optional[str] = None,
        contact_name: Optional[str] = None,
        cc: Optional[str] = None,
        bcc: Optional[str] = None,
        template_vars: Optional[Dict[str, Any]] = None,
    ) -> SingleResponse:
        """
        Send an HTML email rendered from a Jinja2 template via Mailgun.

        Uses POST /messages with content_mode='template'. The server renders
        the template, sends via Mailgun, and records in Chatwoot.

        Args:
            template_name: Registered template name (configured via S3)
            to: Recipient email address
            inbox_id: Chatwoot email inbox ID
            subject: Subject line (overrides template default)
            contact_name: Display name for the contact
            cc: CC addresses, comma-separated
            bcc: BCC addresses, comma-separated
            template_vars: Variables to pass to the Jinja template
        """
        return await self.post_message(
            direction="outbound",
            contact_identifier=to,
            contact_email=to,
            contact_name=contact_name,
            message_content="",
            inbox_id=inbox_id,
            subject=subject,
            content_mode="template",
            template_name=template_name,
            template_vars=template_vars or {},
            cc_emails=cc,
            bcc_emails=bcc,
        )

    async def send_mailgun_email(
        self,
        to: str,
        subject: str,
        text: Optional[str] = None,
        html: Optional[str] = None,
        from_email: Optional[str] = None,
        cc: Optional[str] = None,
        bcc: Optional[str] = None,
        reply_to: Optional[str] = None,
    ) -> SingleResponse:
        """
        Send an email directly via Mailgun (no Chatwoot record).

        Calls POST /api/v1/inboxes/mailgun/email/send for standalone
        Mailgun sends (testing, ad-hoc, non-Chatwoot scenarios).

        Args:
            to: Recipient email address
            subject: Email subject line
            text: Plain text email body
            html: HTML email body
            from_email: Sender address (overrides config default)
            cc: CC addresses, comma-separated
            bcc: BCC addresses, comma-separated
            reply_to: Reply-to address
        """
        payload: Dict[str, Any] = {"to": to, "subject": subject}
        if text:
            payload["text"] = text
        if html:
            payload["html"] = html
        if from_email:
            payload["from_email"] = from_email
        if cc:
            payload["cc"] = cc
        if bcc:
            payload["bcc"] = bcc
        if reply_to:
            payload["reply_to"] = reply_to
        data = await self.post("/api/v1/inboxes/mailgun/email/send", json=payload)
        return SingleResponse(**data)

    async def get_communications(
        self,
        email: Optional[str] = None,
        phone: Optional[str] = None,
        inbox_id: Optional[int] = None,
        since: Optional[str] = None,
        until: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Get unified communications timeline for a contact.

        Args:
            email: Contact email address
            phone: Contact phone number
            inbox_id: Optional inbox ID filter
            since: ISO 8601 start date filter
            until: ISO 8601 end date filter

        Returns:
            Dict with 'success', 'data' containing contact, conversations, summary.
        """
        params: Dict[str, Any] = {}
        if email:
            params["email"] = email
        if phone:
            params["phone"] = phone
        if inbox_id is not None:
            params["inbox_id"] = inbox_id
        if since:
            params["since"] = since
        if until:
            params["until"] = until
        return await self.get("/api/v1/chatwoot/communications", params=params)
