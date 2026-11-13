"""Refresh token repository managing session tokens and database locking."""

from datetime import datetime, timezone
from typing import Optional
from uuid import UUID
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.models.refresh_token import RefreshToken


class RefreshTokenRepository:
    """Encapsulates data access and atomic locking for refresh tokens."""

    @staticmethod
    async def create(db: AsyncSession, refresh_token: RefreshToken) -> RefreshToken:
        """Persist a new hashed refresh token."""
        db.add(refresh_token)
        await db.flush()
        return refresh_token

    @staticmethod
    async def get_by_hash_with_lock(
        db: AsyncSession, token_hash: str
    ) -> Optional[RefreshToken]:
        """Retrieve token record with row-level lock (FOR UPDATE OF refresh_tokens) to prevent race conditions."""
        stmt = (
            select(RefreshToken)
            .where(RefreshToken.token_hash == token_hash)
            .with_for_update(of=RefreshToken)
            .options(joinedload(RefreshToken.user))
        )
        result = await db.execute(stmt)
        return result.scalars().first()

    @staticmethod
    async def revoke(db: AsyncSession, token: RefreshToken) -> None:
        """Revoke a single refresh token record."""
        token.revoked_at = datetime.now(timezone.utc)
        await db.flush()

    @staticmethod
    async def revoke_all_for_user(db: AsyncSession, user_id: UUID) -> None:
        """Revoke all active refresh tokens belonging to a user."""
        now = datetime.now(timezone.utc)
        stmt = (
            update(RefreshToken)
            .where(
                RefreshToken.user_id == user_id,
                RefreshToken.revoked_at.is_(None),
            )
            .values(revoked_at=now)
        )
        await db.execute(stmt)
        await db.flush()
