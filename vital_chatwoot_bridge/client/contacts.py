"""
Contacts mixin for the Chatwoot Bridge client.
"""

from typing import Any, Dict, Optional

from vital_chatwoot_bridge.client.models import PaginatedResponse, SingleResponse


class ContactsMixin:
    """Methods for /api/v1/chatwoot/contacts endpoints."""

    async def list_contacts(
        self, page: int = 1, sort: Optional[str] = None
    ) -> PaginatedResponse:
        """List contacts (paginated)."""
        params: Dict[str, Any] = {"page": page}
        if sort:
            params["sort"] = sort
        data = await self.get("/api/v1/chatwoot/contacts", params=params)
        return PaginatedResponse(**data)

    async def search_contacts(self, q: str, page: int = 1) -> PaginatedResponse:
        """Search contacts by name, email, or phone."""
        params = {"q": q, "page": page}
        data = await self.get("/api/v1/chatwoot/contacts/search", params=params)
        return PaginatedResponse(**data)

    async def get_contact(self, contact_id: int) -> SingleResponse:
        """Get contact details."""
        data = await self.get(f"/api/v1/chatwoot/contacts/{contact_id}")
        return SingleResponse(**data)

    async def get_contact_conversations(
        self, contact_id: int, page: int = 1
    ) -> PaginatedResponse:
        """List conversations for a contact."""
        params: Dict[str, Any] = {"page": page}
        data = await self.get(
            f"/api/v1/chatwoot/contacts/{contact_id}/conversations", params=params
        )
        return PaginatedResponse(**data)

    async def contact_count(self) -> SingleResponse:
        """Get total contact count."""
        data = await self.get("/api/v1/chatwoot/contacts/count")
        return SingleResponse(**data)

    async def update_contact(
        self,
        contact_id: int,
        name: Optional[str] = None,
        email: Optional[str] = None,
        phone_number: Optional[str] = None,
        identifier: Optional[str] = None,
        custom_attributes: Optional[Dict[str, Any]] = None,
    ) -> SingleResponse:
        """Update an existing contact."""
        payload: Dict[str, Any] = {}
        if name is not None:
            payload["name"] = name
        if email is not None:
            payload["email"] = email
        if phone_number is not None:
            payload["phone_number"] = phone_number
        if identifier is not None:
            payload["identifier"] = identifier
        if custom_attributes is not None:
            payload["custom_attributes"] = custom_attributes
        data = await self.post(f"/api/v1/chatwoot/contacts/{contact_id}", json=payload)
        return SingleResponse(**data)

    async def merge_contacts(
        self, base_contact_id: int, mergee_contact_id: int
    ) -> SingleResponse:
        """Merge two contacts. The mergee is merged into the base contact."""
        payload = {
            "base_contact_id": base_contact_id,
            "mergee_contact_id": mergee_contact_id,
        }
        data = await self.post("/api/v1/chatwoot/contacts/merge", json=payload)
        return SingleResponse(**data)

    async def delete_contact(self, contact_id: int) -> SingleResponse:
        """Delete a contact by ID."""
        data = await self.delete(f"/api/v1/chatwoot/contacts/{contact_id}")
        return SingleResponse(**data)

    async def create_contact(
        self,
        name: str,
        email: Optional[str] = None,
        phone_number: Optional[str] = None,
        identifier: Optional[str] = None,
        inbox_id: Optional[int] = None,
        custom_attributes: Optional[Dict[str, Any]] = None,
    ) -> SingleResponse:
        """Create a new contact."""
        payload: Dict[str, Any] = {"name": name}
        if email:
            payload["email"] = email
        if phone_number:
            payload["phone_number"] = phone_number
        if identifier:
            payload["identifier"] = identifier
        if inbox_id:
            payload["inbox_id"] = inbox_id
        if custom_attributes:
            payload["custom_attributes"] = custom_attributes
        data = await self.post("/api/v1/chatwoot/contacts", json=payload)
        return SingleResponse(**data)
