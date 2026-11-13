"""Authentication service coordinating registration, login, token rotation, and logout."""

from datetime import datetime, timezone
import re
from typing import Optional, Tuple
from uuid import UUID
from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.security import (
    create_access_token,
    create_refresh_token,
    hash_password,
    hash_refresh_token,
    verify_password,
)
from app.models.membership import Membership, Role
from app.models.refresh_token import RefreshToken
from app.models.tenant import Tenant
from app.models.user import User
from app.repositories.membership_repository import MembershipRepository
from app.repositories.refresh_token_repository import RefreshTokenRepository
from app.repositories.tenant_repository import TenantRepository
from app.repositories.user_repository import UserRepository
from app.schemas.auth import LoginRequest, RegisterRequest
from app.schemas.user import TenantMembershipInfo, UserWithTenantsResponse


def _slugify(text: str) -> str:
    """Generate a clean URL-friendly slug from an organization name."""
    clean = re.sub(r"[^a-zA-Z0-9\s-]", "", text).strip().lower()
    slug = re.sub(r"[\s-]+", "-", clean)
    return slug or "org"


class AuthService:
    """Business logic for user onboarding and session management."""

    @staticmethod
    async def register(
        payload: RegisterRequest, db: AsyncSession
    ) -> Tuple[User, Tenant, str, str, int]:
        """Register a new user, create their initial organization, and assign OWNER role.

        All operations execute within a single atomic database transaction.
        """
        normalized_email = payload.email.strip().lower()

        # Check if user already exists
        existing_user = await UserRepository.get_by_email(db, normalized_email)
        if existing_user:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="An account with this email address already exists.",
            )

        # Generate unique tenant slug
        base_slug = _slugify(payload.organization_name)
        candidate_slug = base_slug
        counter = 1
        while await TenantRepository.get_by_slug(db, candidate_slug):
            candidate_slug = f"{base_slug}-{counter}"
            counter += 1

        # 1. Create User
        user = User(
            email=normalized_email,
            full_name=payload.full_name.strip(),
            hashed_password=hash_password(payload.password),
            is_active=True,
            is_verified=False,
        )
        await UserRepository.create(db, user)

        # 2. Create Tenant
        tenant = Tenant(
            name=payload.organization_name.strip(),
            slug=candidate_slug,
            is_active=True,
        )
        await TenantRepository.create(db, tenant)

        # 3. Create Membership as OWNER
        membership = Membership(
            user_id=user.id,
            tenant_id=tenant.id,
            role=Role.OWNER.value,
            is_active=True,
        )
        await MembershipRepository.create(db, membership)

        # 4. Generate Tokens
        access_token = create_access_token(user.id)
        raw_refresh, token_hash, expires_at = create_refresh_token()

        # 5. Store Refresh Token Hash
        refresh_token_record = RefreshToken(
            user_id=user.id,
            token_hash=token_hash,
            expires_at=expires_at,
        )
        await RefreshTokenRepository.create(db, refresh_token_record)

        await db.commit()
        await db.refresh(user)
        await db.refresh(tenant)

        expires_in = settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60
        return user, tenant, access_token, raw_refresh, expires_in

    @staticmethod
    async def login(
        payload: LoginRequest, db: AsyncSession
    ) -> Tuple[User, Optional[Tenant], Optional[Role], str, str, int]:
        """Authenticate user credentials and issue new session tokens."""
        normalized_email = payload.email.strip().lower()
        user = await UserRepository.get_by_email(db, normalized_email)

        # Generic authentication failure to prevent user enumeration
        auth_failed_exc = HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password.",
            headers={"WWW-Authenticate": "Bearer"},
        )

        if not user or not verify_password(payload.password, user.hashed_password):
            raise auth_failed_exc

        if not user.is_active:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="User account is deactivated. Contact organization administrator.",
            )

        # Load user's primary organization if any
        user_tenants = await TenantRepository.get_tenants_for_user(db, user.id)
        primary_tenant = user_tenants[0][0] if user_tenants else None
        primary_role = Role(user_tenants[0][1].role) if user_tenants else None

        # Issue tokens
        access_token = create_access_token(user.id)
        raw_refresh, token_hash, expires_at = create_refresh_token()

        refresh_token_record = RefreshToken(
            user_id=user.id,
            token_hash=token_hash,
            expires_at=expires_at,
        )
        await RefreshTokenRepository.create(db, refresh_token_record)
        await db.commit()

        expires_in = settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60
        return user, primary_tenant, primary_role, access_token, raw_refresh, expires_in

    @staticmethod
    async def refresh_tokens(
        raw_refresh_token: str, db: AsyncSession
    ) -> Tuple[str, str, int]:
        """Rotate refresh token with row-level database locking to prevent replay attacks."""
        if not raw_refresh_token or not raw_refresh_token.strip():
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Refresh token is missing.",
            )

        token_hash = hash_refresh_token(raw_refresh_token)

        # Atomic lock on the token row
        token_record = await RefreshTokenRepository.get_by_hash_with_lock(db, token_hash)
        if not token_record:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid refresh token.",
            )

        now = datetime.now(timezone.utc)

        # Detect reuse of revoked token (possible compromise)
        if token_record.revoked_at is not None:
            # Revoke all tokens for this user as a security safeguard
            await RefreshTokenRepository.revoke_all_for_user(db, token_record.user_id)
            await db.commit()
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Revoked refresh token presented. All active sessions invalidated for security.",
            )

        # Check expiration
        if token_record.expires_at <= now:
            token_record.revoked_at = now
            await db.commit()
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Refresh token has expired. Please log in again.",
            )

        if not token_record.user.is_active:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="User account is deactivated.",
            )

        # 1. Revoke the old token
        token_record.revoked_at = now

        # 2. Issue new rotated tokens
        new_access_token = create_access_token(token_record.user_id)
        new_raw_refresh, new_token_hash, new_expires_at = create_refresh_token()

        new_token_record = RefreshToken(
            user_id=token_record.user_id,
            token_hash=new_token_hash,
            expires_at=new_expires_at,
        )
        await RefreshTokenRepository.create(db, new_token_record)
        await db.commit()

        expires_in = settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60
        return new_access_token, new_raw_refresh, expires_in

    @staticmethod
    async def logout(raw_refresh_token: Optional[str], db: AsyncSession) -> None:
        """Revoke the current session's refresh token."""
        if not raw_refresh_token:
            return
        token_hash = hash_refresh_token(raw_refresh_token)
        token_record = await RefreshTokenRepository.get_by_hash_with_lock(db, token_hash)
        if token_record and token_record.revoked_at is None:
            token_record.revoked_at = datetime.now(timezone.utc)
            await db.commit()

    @staticmethod
    async def get_current_user_profile(
        user: User, db: AsyncSession
    ) -> UserWithTenantsResponse:
        """Construct the user profile response including all tenant memberships."""
        tenants_and_memberships = await TenantRepository.get_tenants_for_user(db, user.id)

        memberships_info = [
            TenantMembershipInfo(
                tenant_id=tenant.id,
                tenant_name=tenant.name,
                tenant_slug=tenant.slug,
                role=Role(membership.role),
                joined_at=membership.joined_at,
            )
            for tenant, membership in tenants_and_memberships
        ]

        return UserWithTenantsResponse(
            id=user.id,
            email=user.email,
            full_name=user.full_name,
            is_active=user.is_active,
            is_verified=user.is_verified,
            created_at=user.created_at,
            memberships=memberships_info,
        )
