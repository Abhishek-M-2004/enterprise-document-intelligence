"""Pydantic schemas for Tenant Membership entities."""

from datetime import datetime
from typing import Optional
from uuid import UUID
from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.models.membership import Role


class MemberUserResponse(BaseModel):
    """User summary embedded in membership responses."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    email: EmailStr
    full_name: str


class MembershipCreate(BaseModel):
    """Payload to invite/add an existing registered user to an organization."""

    email: EmailStr
    role: Role = Field(default=Role.MEMBER, description="Assigned role: OWNER, ADMIN, or MEMBER")


class MembershipUpdate(BaseModel):
    """Payload to update an existing member's role."""

    role: Role


class MembershipResponse(BaseModel):
    """Membership record representation."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    user_id: UUID
    tenant_id: UUID
    role: Role
    is_active: bool
    joined_at: datetime
    user: Optional[MemberUserResponse] = None
