"""Tenant and membership management endpoints with strict RBAC enforcement."""

from typing import List
from uuid import UUID
from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import (
    get_current_user,
    get_path_tenant_context,
    require_role,
)
from app.core.tenant_context import TenantContext
from app.db.session import get_db
from app.models.membership import Role
from app.models.user import User
from app.schemas.auth import MessageResponse
from app.schemas.membership import (
    MembershipCreate,
    MembershipResponse,
    MembershipUpdate,
)
from app.schemas.tenant import (
    TenantDetailResponse,
    TenantResponse,
    TenantUpdate,
)
from app.services.membership_service import MembershipService
from app.services.tenant_service import TenantService

router = APIRouter()


@router.get(
    "",
    response_model=List[TenantDetailResponse],
    summary="List User Organizations",
    description="Returns all active organizations that the authenticated user belongs to, including their role.",
)
async def list_user_tenants(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> List[TenantDetailResponse]:
    """Retrieve organizations the user is a member of."""
    return await TenantService.get_user_tenants(current_user.id, db)


@router.get(
    "/{tenant_id}",
    response_model=TenantDetailResponse,
    summary="Get Organization Details",
    description="Retrieves organization information. Enforces that the user is an active member of this organization.",
)
async def get_tenant_details(
    tenant_context: TenantContext = Depends(get_path_tenant_context),
) -> TenantDetailResponse:
    """Retrieve tenant details for verified members."""
    return await TenantService.get_tenant_details(tenant_context)


@router.patch(
    "/{tenant_id}",
    response_model=TenantResponse,
    summary="Update Organization Profile",
    description="Allows an organization OWNER to update organization name or slug.",
)
async def update_tenant(
    payload: TenantUpdate,
    tenant_context: TenantContext = Depends(require_role([Role.OWNER])),
    db: AsyncSession = Depends(get_db),
) -> TenantResponse:
    """Update organization settings (OWNER only)."""
    return await TenantService.update_tenant(payload, tenant_context, db)


# ==============================================================================
# Membership & Member Management Sub-Routes
# ==============================================================================


@router.get(
    "/{tenant_id}/members",
    response_model=List[MembershipResponse],
    summary="List Organization Members",
    description="Lists all active members in the organization. Requires OWNER or ADMIN role.",
)
async def list_tenant_members(
    tenant_context: TenantContext = Depends(require_role([Role.OWNER, Role.ADMIN])),
    db: AsyncSession = Depends(get_db),
) -> List[MembershipResponse]:
    """List members of the organization."""
    return await MembershipService.list_members(tenant_context, db)


@router.post(
    "/{tenant_id}/members",
    response_model=MembershipResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Add Organization Member",
    description="Adds an existing platform user to the organization. OWNER can assign any role; ADMIN can only assign MEMBER.",
)
async def add_tenant_member(
    payload: MembershipCreate,
    tenant_context: TenantContext = Depends(require_role([Role.OWNER, Role.ADMIN])),
    db: AsyncSession = Depends(get_db),
) -> MembershipResponse:
    """Add existing user as an organization member."""
    return await MembershipService.add_member(payload, tenant_context, db)


@router.patch(
    "/{tenant_id}/members/{user_id}",
    response_model=MembershipResponse,
    summary="Update Member Role",
    description="Updates a member's role. Enforces last-owner preservation and admin privilege boundaries.",
)
async def update_member_role(
    user_id: UUID,
    payload: MembershipUpdate,
    tenant_context: TenantContext = Depends(require_role([Role.OWNER, Role.ADMIN])),
    db: AsyncSession = Depends(get_db),
) -> MembershipResponse:
    """Modify role for a tenant member."""
    return await MembershipService.update_member_role(
        user_id, payload, tenant_context, db
    )


@router.delete(
    "/{tenant_id}/members/{user_id}",
    response_model=MessageResponse,
    summary="Remove Member from Organization",
    description="Removes a member from the organization without deleting their platform account. Enforces last-owner preservation.",
)
async def remove_tenant_member(
    user_id: UUID,
    tenant_context: TenantContext = Depends(require_role([Role.OWNER, Role.ADMIN])),
    db: AsyncSession = Depends(get_db),
) -> MessageResponse:
    """Remove member from tenant."""
    await MembershipService.remove_member(user_id, tenant_context, db)
    return MessageResponse(message="Member successfully removed from organization.")
