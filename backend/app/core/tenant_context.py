"""Tenant context encapsulation and database-level RLS setting utilities."""

from dataclasses import dataclass
from typing import Sequence
from uuid import UUID
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.membership import Membership, Role
from app.models.tenant import Tenant
from app.models.user import User


@dataclass
class TenantContext:
    """Request-scoped verified tenant context."""

    tenant: Tenant
    user: User
    membership: Membership
    role: Role

    @property
    def tenant_id(self) -> UUID:
        return self.tenant.id

    @property
    def user_id(self) -> UUID:
        return self.user.id

    def is_owner(self) -> bool:
        return self.role == Role.OWNER

    def is_admin(self) -> bool:
        return self.role == Role.ADMIN

    def has_role(self, allowed_roles: Sequence[Role]) -> bool:
        return self.role in allowed_roles


async def set_db_tenant_context(session: AsyncSession, tenant_id: UUID) -> None:
    """Apply session-scoped PostgreSQL tenant setting for Row-Level Security.

    Uses `set_config('app.current_tenant_id', :tid, false)` to ensure tenant context
    persists across multiple transactions/commits within the same HTTP request session
    (e.g., commit + refresh). The session provider executes `RESET app.current_tenant_id`
    on session closure to guarantee zero leakage across pooled connections.
    """
    await session.execute(
        text("SELECT set_config('app.current_tenant_id', :tid, false)"),
        {"tid": str(tenant_id)},
    )
