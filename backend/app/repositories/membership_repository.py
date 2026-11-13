"""Membership repository managing role assignments and user-tenant associations."""

from typing import List, Optional
from uuid import UUID
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.models.membership import Membership, Role


class MembershipRepository:
    """Encapsulates data access for Membership entities."""

    @staticmethod
    async def get_by_user_and_tenant(
        db: AsyncSession, user_id: UUID, tenant_id: UUID
    ) -> Optional[Membership]:
        """Retrieve a user's membership in a specific organization."""
        stmt = (
            select(Membership)
            .where(
                Membership.user_id == user_id,
                Membership.tenant_id == tenant_id,
            )
            .options(joinedload(Membership.tenant), joinedload(Membership.user))
        )
        result = await db.execute(stmt)
        return result.scalars().first()

    @staticmethod
    async def get_memberships_for_user(
        db: AsyncSession, user_id: UUID
    ) -> List[Membership]:
        """Retrieve all active memberships for a user."""
        stmt = (
            select(Membership)
            .where(
                Membership.user_id == user_id,
                Membership.is_active.is_(True),
            )
            .options(joinedload(Membership.tenant))
        )
        result = await db.execute(stmt)
        return list(result.scalars().all())

    @staticmethod
    async def get_members_for_tenant(
        db: AsyncSession, tenant_id: UUID
    ) -> List[Membership]:
        """Retrieve all active memberships for a tenant."""
        stmt = (
            select(Membership)
            .where(
                Membership.tenant_id == tenant_id,
                Membership.is_active.is_(True),
            )
            .options(joinedload(Membership.user))
            .order_by(Membership.joined_at.asc())
        )
        result = await db.execute(stmt)
        return list(result.scalars().all())

    @staticmethod
    async def count_owners_for_tenant(db: AsyncSession, tenant_id: UUID) -> int:
        """Count how many active OWNERs exist for a tenant."""
        stmt = (
            select(func.count(Membership.id))
            .where(
                Membership.tenant_id == tenant_id,
                Membership.role == Role.OWNER.value,
                Membership.is_active.is_(True),
            )
        )
        result = await db.execute(stmt)
        return result.scalar_one() or 0

    @staticmethod
    async def create(db: AsyncSession, membership: Membership) -> Membership:
        """Persist a new membership."""
        db.add(membership)
        await db.flush()
        return membership

    @staticmethod
    async def update(db: AsyncSession, membership: Membership) -> Membership:
        """Flush changes on an existing membership."""
        await db.flush()
        return membership

    @staticmethod
    async def delete(db: AsyncSession, membership: Membership) -> None:
        """Remove a membership."""
        await db.delete(membership)
        await db.flush()
