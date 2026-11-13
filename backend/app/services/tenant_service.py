"""Tenant management service for querying and updating organization profiles."""

from typing import List
from uuid import UUID
from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.tenant_context import TenantContext
from app.models.membership import Role
from app.repositories.membership_repository import MembershipRepository
from app.repositories.tenant_repository import TenantRepository
from app.schemas.tenant import TenantDetailResponse, TenantResponse, TenantUpdate


class TenantService:
    """Business logic for Tenant organization administration."""

    @staticmethod
    async def get_user_tenants(
        user_id: UUID, db: AsyncSession
    ) -> List[TenantDetailResponse]:
        """List all active organizations associated with the user."""
        tenants_and_memberships = await TenantRepository.get_tenants_for_user(db, user_id)
        return [
            TenantDetailResponse(
                id=tenant.id,
                name=tenant.name,
                slug=tenant.slug,
                is_active=tenant.is_active,
                created_at=tenant.created_at,
                current_user_role=Role(membership.role),
            )
            for tenant, membership in tenants_and_memberships
        ]

    @staticmethod
    async def get_tenant_details(
        tenant_context: TenantContext,
    ) -> TenantDetailResponse:
        """Return details of the organization after verified tenant context."""
        return TenantDetailResponse(
            id=tenant_context.tenant.id,
            name=tenant_context.tenant.name,
            slug=tenant_context.tenant.slug,
            is_active=tenant_context.tenant.is_active,
            created_at=tenant_context.tenant.created_at,
            current_user_role=tenant_context.role,
        )

    @staticmethod
    async def update_tenant(
        payload: TenantUpdate,
        tenant_context: TenantContext,
        db: AsyncSession,
    ) -> TenantResponse:
        """Update organization name or slug (strictly reserved for OWNER role)."""
        if not tenant_context.is_owner():
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Forbidden: Only an organization OWNER can modify organization settings.",
            )

        tenant = tenant_context.tenant

        if payload.name is not None:
            tenant.name = payload.name.strip()

        if payload.slug is not None:
            new_slug = payload.slug.strip().lower()
            if new_slug != tenant.slug:
                existing = await TenantRepository.get_by_slug(db, new_slug)
                if existing and existing.id != tenant.id:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="An organization with this slug already exists.",
                    )
                tenant.slug = new_slug

        await TenantRepository.update(db, tenant)
        await db.commit()
        await db.refresh(tenant)

        return TenantResponse.model_validate(tenant)
