"""Comprehensive database integrity, constraints, and Row-Level Security (RLS) test suite."""

from uuid import uuid4
import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.core.security import hash_password
from app.db.session import AsyncSessionLocal
from app.models.membership import Membership, Role
from app.models.tenant import Tenant
from app.models.user import User


@pytest.mark.asyncio
async def test_duplicate_membership_constraint_enforced() -> None:
    """Verify unique constraint on (user_id, tenant_id) blocks duplicate memberships."""
    async with AsyncSessionLocal() as session:
        user = User(
            email=f"db_uq_{uuid4().hex[:8]}@test.com",
            full_name="Unique Test User",
            hashed_password=hash_password("Password123!"),
        )
        tenant = Tenant(
            name="Constraint Test Tenant",
            slug=f"uq-tenant-{uuid4().hex[:8]}",
        )
        session.add_all([user, tenant])
        await session.flush()

        m1 = Membership(
            user_id=user.id,
            tenant_id=tenant.id,
            role=Role.MEMBER.value,
        )
        session.add(m1)
        await session.flush()

        m2 = Membership(
            user_id=user.id,
            tenant_id=tenant.id,
            role=Role.ADMIN.value,
        )
        session.add(m2)

        with pytest.raises(IntegrityError):
            await session.flush()

        await session.rollback()


@pytest.mark.asyncio
async def test_tenant_slug_uniqueness_enforced() -> None:
    """Verify unique constraint on tenant slug blocks duplicate slug insertion."""
    slug = f"unique-slug-{uuid4().hex[:8]}"
    async with AsyncSessionLocal() as session:
        t1 = Tenant(name="Company One", slug=slug)
        session.add(t1)
        await session.flush()

        t2 = Tenant(name="Company Two", slug=slug)
        session.add(t2)

        with pytest.raises(IntegrityError):
            await session.flush()

        await session.rollback()


@pytest.mark.asyncio
async def test_postgresql_row_level_security_enforcement() -> None:
    """Verify real PostgreSQL Row-Level Security (RLS) on tenant-scoped tables.

    Tests fail-closed behavior, cross-tenant isolation, and successful query
    when transaction-local `set_config('app.current_tenant_id', ...)` matches.
    Uses non-superuser role to test RLS without superuser bypass.
    """
    tenant_a_id = uuid4()
    tenant_b_id = uuid4()

    async with AsyncSessionLocal() as session:
        # Prepare a dedicated non-superuser role to verify RLS policies
        await session.execute(
            text(
                "DO $$ BEGIN "
                "IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'rls_app_user') THEN "
                "CREATE ROLE rls_app_user WITH NOSUPERUSER NOBYPASSRLS; "
                "END IF; END $$;"
            )
        )
        await session.execute(text("GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO rls_app_user"))

        # Create two real tenants
        t_a = Tenant(id=tenant_a_id, name="RLS Tenant A", slug=f"rls-a-{uuid4().hex[:8]}")
        t_b = Tenant(id=tenant_b_id, name="RLS Tenant B", slug=f"rls-b-{uuid4().hex[:8]}")
        session.add_all([t_a, t_b])
        await session.flush()

        # Seed confidential record for Tenant A (setting tenant context so WITH CHECK passes)
        await session.execute(
            text("SELECT set_config('app.current_tenant_id', :tid, false)"),
            {"tid": str(tenant_a_id)},
        )
        await session.execute(
            text(
                "INSERT INTO tenant_audit_logs (id, tenant_id, action, details) "
                "VALUES (:id, :tid, :act, :det)"
            ),
            {
                "id": uuid4(),
                "tid": tenant_a_id,
                "act": "DOCUMENT_ACCESS",
                "det": "Confidential Tenant A audit log",
            },
        )
        await session.commit()
        await session.execute(text("RESET app.current_tenant_id"))
        await session.commit()

    # 1. New transaction with NO tenant set (Fail-Closed verification under rls_app_user)
    async with AsyncSessionLocal() as session:
        await session.execute(text("SET LOCAL ROLE rls_app_user"))
        result = await session.execute(
            text("SELECT count(*) FROM tenant_audit_logs WHERE tenant_id = :tid"),
            {"tid": tenant_a_id},
        )
        count_no_ctx = result.scalar_one()
        assert count_no_ctx == 0, "RLS must fail-closed when app.current_tenant_id is missing"

    # 2. Transaction with Tenant B set (Cross-Tenant blocked verification)
    async with AsyncSessionLocal() as session:
        await session.execute(text("SET LOCAL ROLE rls_app_user"))
        await session.execute(
            text("SELECT set_config('app.current_tenant_id', :tid, true)"),
            {"tid": str(tenant_b_id)},
        )
        result = await session.execute(
            text("SELECT count(*) FROM tenant_audit_logs WHERE tenant_id = :tid"),
            {"tid": tenant_a_id},
        )
        count_tenant_b = result.scalar_one()
        assert count_tenant_b == 0, "RLS must block access to Tenant A rows when Tenant B context is active"

    # 3. Transaction with Tenant A set (Authorized tenant query)
    async with AsyncSessionLocal() as session:
        await session.execute(text("SET LOCAL ROLE rls_app_user"))
        await session.execute(
            text("SELECT set_config('app.current_tenant_id', :tid, true)"),
            {"tid": str(tenant_a_id)},
        )
        result = await session.execute(
            text("SELECT count(*) FROM tenant_audit_logs WHERE tenant_id = :tid"),
            {"tid": tenant_a_id},
        )
        count_tenant_a = result.scalar_one()
        assert count_tenant_a == 1, "RLS must permit access when app.current_tenant_id matches row tenant_id"
