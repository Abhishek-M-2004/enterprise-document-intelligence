"""Pydantic schemas for User entities."""

from datetime import datetime
from typing import List, Optional
from uuid import UUID
from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.models.membership import Role


class UserBase(BaseModel):
    """Base user attributes."""

    email: EmailStr
    full_name: str = Field(..., min_length=1, max_length=255)


class UserCreate(UserBase):
    """Payload for creating a new user account."""

    password: str = Field(..., min_length=8, max_length=128)


class UserResponse(UserBase):
    """Public user profile response (safe, zero secrets)."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    is_active: bool
    is_verified: bool
    created_at: datetime


class TenantMembershipInfo(BaseModel):
    """Summary of a user's role within an organization."""

    model_config = ConfigDict(from_attributes=True)

    tenant_id: UUID
    tenant_name: str
    tenant_slug: str
    role: Role
    joined_at: datetime


class UserWithTenantsResponse(UserResponse):
    """Complete profile of the authenticated user including memberships."""

    memberships: List[TenantMembershipInfo] = Field(default_factory=list)
