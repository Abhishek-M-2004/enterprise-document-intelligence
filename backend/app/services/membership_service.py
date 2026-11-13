"""Membership service managing member invitations, role transitions, and member removals."""

from typing import List
from uuid import UUID
from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.tenant_context import TenantContext
from app.models.membership import Membership, Role
from app.repositories.membership_repository import MembershipRepository
from app.repositories.user_repository import UserRepository
from app.schemas.membership import (
    MembershipCreate,
    MembershipResponse,
    MembershipUpdate,
    MemberUserResponse,
)


class MembershipService:
    """Business logic for Tenant Membership administration and RBAC enforcement."""

    @staticmethod
    async def list_members(
        tenant_context: TenantContext, db: AsyncSession
    ) -> List[MembershipResponse]:
        """List members of the organization (allowed for OWNER and ADMIN)."""
        if not tenant_context.has_role([Role.OWNER, Role.ADMIN]):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Forbidden: Only organization OWNERs and ADMINs can view the member list.",
            )

        members = await MembershipRepository.get_members_for_tenant(
            db, tenant_context.tenant_id
        )

        return [
            MembershipResponse(
                id=m.id,
                user_id=m.user_id,
                tenant_id=m.tenant_id,
                role=Role(m.role),
                is_active=m.is_active,
                joined_at=m.joined_at,
                user=MemberUserResponse(
                    id=m.user.id,
                    email=m.user.email,
                    full_name=m.user.full_name,
                )
                if m.user
                else None,
            )
            for m in members
        ]

    @staticmethod
    async def add_member(
        payload: MembershipCreate,
        tenant_context: TenantContext,
        db: AsyncSession,
    ) -> MembershipResponse:
        """Add an existing platform user to the organization with RBAC validation."""
        if not tenant_context.has_role([Role.OWNER, Role.ADMIN]):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Forbidden: Only organization OWNERs and ADMINs can add members.",
            )

        # RBAC Constraint: ADMIN can only assign the MEMBER role
        if tenant_context.is_admin() and payload.role in (Role.OWNER, Role.ADMIN):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Forbidden: Administrators may only assign the MEMBER role. Only OWNER can assign OWNER or ADMIN roles.",
            )

        normalized_email = payload.email.strip().lower()
        target_user = await UserRepository.get_by_email(db, normalized_email)
        if not target_user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User with this email is not registered on the platform.",
            )

        # Check for existing membership
        existing_membership = await MembershipRepository.get_by_user_and_tenant(
            db, target_user.id, tenant_context.tenant_id
        )
        if existing_membership:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="User is already a member of this organization.",
            )

        # Create new membership
        membership = Membership(
            user_id=target_user.id,
            tenant_id=tenant_context.tenant_id,
            role=payload.role.value,
            is_active=True,
        )
        await MembershipRepository.create(db, membership)
        await db.commit()
        await db.refresh(membership)

        return MembershipResponse(
            id=membership.id,
            user_id=membership.user_id,
            tenant_id=membership.tenant_id,
            role=Role(membership.role),
            is_active=membership.is_active,
            joined_at=membership.joined_at,
            user=MemberUserResponse(
                id=target_user.id,
                email=target_user.email,
                full_name=target_user.full_name,
            ),
        )

    @staticmethod
    async def update_member_role(
        target_user_id: UUID,
        payload: MembershipUpdate,
        tenant_context: TenantContext,
        db: AsyncSession,
    ) -> MembershipResponse:
        """Modify an existing member's role with RBAC and last-owner safety checks."""
        if not tenant_context.has_role([Role.OWNER, Role.ADMIN]):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Forbidden: Only organization OWNERs and ADMINs can modify member roles.",
            )

        target_membership = await MembershipRepository.get_by_user_and_tenant(
            db, target_user_id, tenant_context.tenant_id
        )
        if not target_membership:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Membership record not found.",
            )

        target_current_role = Role(target_membership.role)

        # RBAC Constraints for ADMIN:
        if tenant_context.is_admin():
            if target_current_role in (Role.OWNER, Role.ADMIN):
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Forbidden: Administrators cannot modify another ADMIN or OWNER.",
                )
            if payload.role in (Role.OWNER, Role.ADMIN):
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Forbidden: Administrators cannot promote members to ADMIN or OWNER.",
                )

        # Last Owner Protection:
        if target_current_role == Role.OWNER and payload.role != Role.OWNER:
            owner_count = await MembershipRepository.count_owners_for_tenant(
                db, tenant_context.tenant_id
            )
            if owner_count <= 1:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Cannot change role: Organization must retain at least one active OWNER.",
                )

        target_membership.role = payload.role.value
        await MembershipRepository.update(db, target_membership)
        await db.commit()
        await db.refresh(target_membership)

        return MembershipResponse(
            id=target_membership.id,
            user_id=target_membership.user_id,
            tenant_id=target_membership.tenant_id,
            role=Role(target_membership.role),
            is_active=target_membership.is_active,
            joined_at=target_membership.joined_at,
            user=MemberUserResponse(
                id=target_membership.user.id,
                email=target_membership.user.email,
                full_name=target_membership.user.full_name,
            )
            if target_membership.user
            else None,
        )

    @staticmethod
    async def remove_member(
        target_user_id: UUID,
        tenant_context: TenantContext,
        db: AsyncSession,
    ) -> None:
        """Remove a user's membership in the organization without deleting their account."""
        if not tenant_context.has_role([Role.OWNER, Role.ADMIN]):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Forbidden: Only organization OWNERs and ADMINs can remove members.",
            )

        target_membership = await MembershipRepository.get_by_user_and_tenant(
            db, target_user_id, tenant_context.tenant_id
        )
        if not target_membership:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Membership record not found.",
            )

        target_role = Role(target_membership.role)

        # RBAC Constraints for ADMIN:
        if tenant_context.is_admin():
            if target_role == Role.OWNER:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Forbidden: Administrators cannot remove an organization OWNER.",
                )
            if target_role == Role.ADMIN and target_user_id != tenant_context.user_id:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Forbidden: Administrators cannot remove other administrators.",
                )

        # Last Owner Protection:
        if target_role == Role.OWNER:
            owner_count = await MembershipRepository.count_owners_for_tenant(
                db, tenant_context.tenant_id
            )
            if owner_count <= 1:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Cannot remove member: Organization must retain at least one active OWNER.",
                )

        await MembershipRepository.delete(db, target_membership)
        await db.commit()
