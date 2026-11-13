"""Authentication endpoints for user registration, login, token refresh, and profile inspection."""

from typing import Optional
from fastapi import APIRouter, Depends, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.dependencies import get_current_user, get_refresh_token_from_request
from app.core.rate_limiter import auth_rate_limiter
from app.db.session import get_db
from app.models.user import User
from app.schemas.auth import (
    AuthSuccessResponse,
    LoginRequest,
    MessageResponse,
    RefreshTokenRequest,
    RegisterRequest,
    TokenResponse,
)
from app.schemas.tenant import TenantResponse
from app.schemas.user import UserResponse, UserWithTenantsResponse
from app.services.auth_service import AuthService

router = APIRouter()


def _set_refresh_cookie(response: Response, raw_token: str) -> None:
    """Set secure HttpOnly cookie containing the raw refresh token."""
    response.set_cookie(
        key=settings.REFRESH_COOKIE_NAME,
        value=raw_token,
        httponly=True,
        secure=settings.COOKIE_SECURE,
        samesite=settings.COOKIE_SAMESITE,
        domain=settings.COOKIE_DOMAIN,
        max_age=settings.REFRESH_TOKEN_EXPIRE_DAYS * 86400,
        path="/api/v1/auth",
    )


def _clear_refresh_cookie(response: Response) -> None:
    """Clear the refresh token cookie upon logout."""
    response.delete_cookie(
        key=settings.REFRESH_COOKIE_NAME,
        path="/api/v1/auth",
        domain=settings.COOKIE_DOMAIN,
    )


@router.post(
    "/register",
    response_model=AuthSuccessResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register User and Initial Tenant Organization",
    description="Registers an enterprise user, provisions an isolated tenant, and assigns OWNER role in an atomic transaction.",
    dependencies=[Depends(auth_rate_limiter)],
)
async def register(
    payload: RegisterRequest,
    response: Response,
    db: AsyncSession = Depends(get_db),
) -> AuthSuccessResponse:
    """Atomic registration endpoint."""
    user, tenant, access_token, raw_refresh, expires_in = await AuthService.register(
        payload, db
    )
    _set_refresh_cookie(response, raw_refresh)

    return AuthSuccessResponse(
        access_token=access_token,
        token_type="bearer",
        expires_in=expires_in,
        user=UserResponse.model_validate(user),
        organization=TenantResponse.model_validate(tenant),
        role=tenant.memberships[0].role if tenant.memberships else None,
    )


@router.post(
    "/login",
    response_model=AuthSuccessResponse,
    summary="User Login",
    description="Authenticates credentials with Argon2 and issues short-lived JWT access and secure refresh tokens.",
    dependencies=[Depends(auth_rate_limiter)],
)
async def login(
    payload: LoginRequest,
    response: Response,
    db: AsyncSession = Depends(get_db),
) -> AuthSuccessResponse:
    """User login endpoint."""
    user, tenant, role, access_token, raw_refresh, expires_in = await AuthService.login(
        payload, db
    )
    _set_refresh_cookie(response, raw_refresh)

    return AuthSuccessResponse(
        access_token=access_token,
        token_type="bearer",
        expires_in=expires_in,
        user=UserResponse.model_validate(user),
        organization=TenantResponse.model_validate(tenant) if tenant else None,
        role=role,
    )


@router.post(
    "/refresh",
    response_model=TokenResponse,
    summary="Rotate Refresh Token",
    description="Validates the active session refresh token, revokes it, and issues rotated tokens with anti-replay protection.",
)
async def refresh_token(
    request: Request,
    response: Response,
    payload: Optional[RefreshTokenRequest] = None,
    db: AsyncSession = Depends(get_db),
) -> TokenResponse:
    """Refresh token rotation endpoint."""
    token = None
    if payload and payload.refresh_token:
        token = payload.refresh_token
    else:
        token = get_refresh_token_from_request(request)

    new_access, new_refresh, expires_in = await AuthService.refresh_tokens(token, db)
    _set_refresh_cookie(response, new_refresh)

    return TokenResponse(
        access_token=new_access,
        token_type="bearer",
        expires_in=expires_in,
    )


@router.post(
    "/logout",
    response_model=MessageResponse,
    summary="User Logout",
    description="Revokes the active session refresh token and clears client cookies.",
)
async def logout(
    request: Request,
    response: Response,
    payload: Optional[RefreshTokenRequest] = None,
    db: AsyncSession = Depends(get_db),
) -> MessageResponse:
    """Session logout endpoint."""
    token = None
    if payload and payload.refresh_token:
        token = payload.refresh_token
    else:
        token = get_refresh_token_from_request(request)

    await AuthService.logout(token, db)
    _clear_refresh_cookie(response)

    return MessageResponse(message="Successfully logged out.")


@router.get(
    "/me",
    response_model=UserWithTenantsResponse,
    summary="Current Authenticated User Profile",
    description="Returns the authenticated user's details and active memberships with associated roles across all tenants.",
)
async def get_me(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> UserWithTenantsResponse:
    """Retrieve current user profile with tenant memberships."""
    return await AuthService.get_current_user_profile(current_user, db)
