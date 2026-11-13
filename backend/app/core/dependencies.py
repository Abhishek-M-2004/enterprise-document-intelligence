"""Centralized FastAPI dependencies for authentication, tenant context, and RBAC."""

from typing import Callable, Optional, Sequence
from uuid import UUID
from fastapi import Depends, Header, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer
import jwt
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.security import decode_access_token
from app.core.tenant_context import TenantContext, set_db_tenant_context
from app.db.session import get_db
from app.models.membership import Role
from app.models.user import User
from app.repositories.membership_repository import MembershipRepository
from app.repositories.tenant_repository import TenantRepository
from app.repositories.user_repository import UserRepository

oauth2_scheme = OAuth2PasswordBearer(
    tokenUrl=f"{settings.API_V1_STR}/auth/login",
    auto_error=False,
)


async def get_current_user(
    token: Optional[str] = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    """Validate JWT access token and retrieve current active user."""
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials or token expired.",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if not token:
        raise credentials_exception

    try:
        payload = decode_access_token(token)
        user_id_str: Optional[str] = payload.get("sub")
        if not user_id_str:
            raise credentials_exception
        user_id = UUID(user_id_str)
    except (jwt.PyJWTError, ValueError):
        raise credentials_exception

    user = await UserRepository.get_by_id(db, user_id)
    if not user:
        raise credentials_exception
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User account is deactivated.",
        )
    return user


async def get_optional_tenant_id_header(
    x_tenant_id: Optional[str] = Header(None, alias="X-Tenant-ID"),
) -> Optional[UUID]:
    """Parse X-Tenant-ID header into UUID if provided."""
    if not x_tenant_id:
        return None
    try:
        return UUID(x_tenant_id.strip())
    except (ValueError, AttributeError):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Malformed X-Tenant-ID header. Must be a valid UUID.",
        )


async def get_tenant_context(
    tenant_id: Optional[UUID] = Depends(get_optional_tenant_id_header),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> TenantContext:
    """Validate and construct tenant context from the X-Tenant-ID header.

    Enforces that the client-supplied tenant ID is verified against the database.
    """
    if not tenant_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Header 'X-Tenant-ID' is required for tenant-scoped operations.",
        )

    return await _resolve_tenant_context(tenant_id, current_user, db)


async def get_path_tenant_context(
    tenant_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> TenantContext:
    """Validate and construct tenant context when tenant_id is supplied in the URL path."""
    return await _resolve_tenant_context(tenant_id, current_user, db)


async def _resolve_tenant_context(
    tenant_id: UUID,
    user: User,
    db: AsyncSession,
) -> TenantContext:
    """Verify tenant existence, user membership, active status, and initialize RLS."""
    tenant = await TenantRepository.get_by_id(db, tenant_id)
    if not tenant or not tenant.is_active:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Organization not found or inactive.",
        )

    membership = await MembershipRepository.get_by_user_and_tenant(db, user.id, tenant_id)
    if not membership or not membership.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Forbidden: You are not an active member of this organization.",
        )

    # Set transaction-scoped PostgreSQL tenant variable
    await set_db_tenant_context(db, tenant.id)

    role = Role(membership.role)
    return TenantContext(
        tenant=tenant,
        user=user,
        membership=membership,
        role=role,
    )


def require_role(allowed_roles: Sequence[Role]) -> Callable[[TenantContext], TenantContext]:
    """Dependency factory enforcing that the authenticated user possesses an allowed role."""

    def role_checker(
        tenant_context: TenantContext = Depends(get_path_tenant_context),
    ) -> TenantContext:
        if not tenant_context.has_role(allowed_roles):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Forbidden: Insufficient privileges. Required: {[r.value for r in allowed_roles]}",
            )
        return tenant_context

    return role_checker


def require_header_role(allowed_roles: Sequence[Role]) -> Callable[[TenantContext], TenantContext]:
    """Dependency factory enforcing allowed role based on X-Tenant-ID header context."""

    def role_checker(
        tenant_context: TenantContext = Depends(get_tenant_context),
    ) -> TenantContext:
        if not tenant_context.has_role(allowed_roles):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Forbidden: Insufficient privileges. Required: {[r.value for r in allowed_roles]}",
            )
        return tenant_context

    return role_checker


def get_refresh_token_from_request(request: Request) -> Optional[str]:
    """Extract refresh token from HttpOnly cookie or X-Refresh-Token header."""
    cookie_token = request.cookies.get(settings.REFRESH_COOKIE_NAME)
    if cookie_token:
        return cookie_token.strip()

    header_token = request.headers.get("X-Refresh-Token")
    if header_token:
        return header_token.strip()

    return None
