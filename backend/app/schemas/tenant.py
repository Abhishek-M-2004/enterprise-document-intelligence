"""Pydantic schemas for Tenant entities."""

import re
from datetime import datetime
from typing import Optional
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.membership import Role

SLUG_REGEX = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


class TenantBase(BaseModel):
    """Base tenant attributes."""

    name: str = Field(..., min_length=2, max_length=255)
    slug: str = Field(..., min_length=2, max_length=100)

    @field_validator("slug")
    @classmethod
    def validate_slug(cls, v: str) -> str:
        normalized = v.strip().lower()
        if not SLUG_REGEX.match(normalized):
            raise ValueError(
                "Tenant slug must be alphanumeric lowercase and may contain hyphens (e.g., 'acme-corp')."
            )
        return normalized


class TenantCreate(TenantBase):
    """Payload for creating a new tenant."""
    pass


class TenantUpdate(BaseModel):
    """Payload for updating organization details (OWNER only)."""

    name: Optional[str] = Field(None, min_length=2, max_length=255)
    slug: Optional[str] = Field(None, min_length=2, max_length=100)

    @field_validator("slug")
    @classmethod
    def validate_slug(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        normalized = v.strip().lower()
        if not SLUG_REGEX.match(normalized):
            raise ValueError("Tenant slug must be alphanumeric lowercase and may contain hyphens.")
        return normalized


class TenantResponse(TenantBase):
    """Public tenant information representation."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    is_active: bool
    created_at: datetime


class TenantDetailResponse(TenantResponse):
    """Tenant information including the requester's role."""

    current_user_role: Optional[Role] = None
