"""Tenant repository managing database operations for organizations."""

from typing import List, Optional, Tuple
from uuid import UUID
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.membership import Membership
from app.models.tenant import Tenant


class TenantRepository:
    """Encapsulates data access for Tenant entities."""

    @staticmethod
    async def get_by_id(db: AsyncSession, tenant_id: UUID) -> Optional[Tenant]:
        """Retrieve a tenant by its unique primary key."""
        stmt = select(Tenant).where(Tenant.id == tenant_id)
        result = await db.execute(stmt)
        return result.scalars().first()

    @staticmethod
    async def get_by_slug(db: AsyncSession, slug: str) -> Optional[Tenant]:
        """Retrieve a tenant by unique normalized slug."""
        normalized_slug = slug.strip().lower()
        stmt = select(Tenant).where(Tenant.slug == normalized_slug)
        result = await db.execute(stmt)
        return result.scalars().first()

    @staticmethod
    async def create(db: AsyncSession, tenant: Tenant) -> Tenant:
        """Persist a new tenant to the database."""
        db.add(tenant)
        await db.flush()
        return tenant

    @staticmethod
    async def update(db: AsyncSession, tenant: Tenant) -> Tenant:
        """Flush changes on an existing tenant."""
        await db.flush()
        return tenant

    @staticmethod
    async def get_tenants_for_user(
        db: AsyncSession, user_id: UUID
    ) -> List[Tuple[Tenant, Membership]]:
        """Retrieve all active organizations and corresponding membership roles for a given user."""
        stmt = (
            select(Tenant, Membership)
            .join(Membership, Membership.tenant_id == Tenant.id)
            .where(
                Membership.user_id == user_id,
                Membership.is_active.is_(True),
                Tenant.is_active.is_(True),
            )
            .order_by(Tenant.name.asc())
        )
        result = await db.execute(stmt)
        return [(row[0], row[1]) for row in result.all()]
