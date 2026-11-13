"""Pydantic schemas for Authentication workflows."""

from typing import Optional
from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.models.membership import Role
from app.schemas.tenant import TenantResponse
from app.schemas.user import UserResponse


class RegisterRequest(BaseModel):
    """Payload for registering a new user and creating their initial organization."""

    full_name: str = Field(..., min_length=1, max_length=255)
    email: EmailStr
    password: str = Field(..., min_length=8, max_length=128)
    organization_name: str = Field(..., min_length=2, max_length=255)


class LoginRequest(BaseModel):
    """Payload for user authentication."""

    email: EmailStr
    password: str = Field(..., min_length=1)


class RefreshTokenRequest(BaseModel):
    """Optional payload for explicit refresh token submission when cookies are not used."""

    refresh_token: Optional[str] = Field(None, description="Opaque refresh token string")


class TokenResponse(BaseModel):
    """Standardized bearer token response."""

    access_token: str
    token_type: str = "bearer"
    expires_in: int = Field(..., description="Access token expiration window in seconds")


class AuthSuccessResponse(TokenResponse):
    """Response returned upon successful registration or initial authentication."""

    model_config = ConfigDict(from_attributes=True)

    user: UserResponse
    organization: Optional[TenantResponse] = None
    role: Optional[Role] = None


class MessageResponse(BaseModel):
    """Generic status response message."""

    message: str
