"""
Response models for the Chatwoot Bridge client library.
Mirrors the server-side management_models.py for typed responses.
"""

from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class PaginationMeta(BaseModel):
    """Pagination metadata."""
    page: int = Field(default=1)
    per_page: int = Field(default=25)
    total_count: Optional[int] = Field(default=None)
    total_pages: Optional[int] = Field(default=None)


class PaginatedResponse(BaseModel):
    """Paginated response envelope."""
    success: bool = Field(default=True)
    data: Any = Field(default=None)
    meta: Optional[PaginationMeta] = Field(default=None)


class SingleResponse(BaseModel):
    """Single-item response envelope."""
    success: bool = Field(default=True)
    data: Any = Field(default=None)


class PostMessageResult(BaseModel):
    """Result from the post-message endpoint."""
    contact_id: Optional[int] = Field(default=None)
    conversation_id: Optional[int] = Field(default=None)
    message: Optional[Dict[str, Any]] = Field(default=None)
