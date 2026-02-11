"""
Authentication models for JWT-based access control.
"""

from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel, Field


class AuthenticatedUser(BaseModel):
    """Authenticated user context extracted from a verified JWT token."""
    client_id: str = Field(..., description="Client identifier")
    subject: str = Field(..., description="Token subject (sub claim)")
    scopes: List[str] = Field(default_factory=list, description="Granted scopes")
    roles: List[str] = Field(default_factory=list, description="User roles")
    groups: List[str] = Field(default_factory=list, description="User groups")
    expires_at: datetime = Field(..., description="Token expiration time")
    issued_at: datetime = Field(..., description="Token issued time")
    username: Optional[str] = Field(None, description="Preferred username")
    email: Optional[str] = Field(None, description="User email")
    raw_claims: dict = Field(default_factory=dict, description="Raw JWT claims for debugging")
