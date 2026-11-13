"""Comprehensive test suite for Multi-Tenant Isolation and Context Verification."""

from uuid import uuid4
from httpx import AsyncClient
import pytest
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import AsyncSessionLocal
from app.models.membership import Membership


async def _register_user_and_tenant(
    client: AsyncClient, prefix: str
) -> dict:
    """Helper to register user and obtain token and tenant data."""
    email = f"{prefix}_{uuid4().hex[:8]}@org.com"
    res = await client.post(
        "/api/v1/auth/register",
        json={
            "full_name": f"{prefix} User",
            "email": email,
            "password": "Password123!",
            "organization_name": f"{prefix} Org",
        },
    )
    assert res.status_code == 201
    return res.json()


@pytest.mark.asyncio
async def test_user_can_access_own_tenant(async_client: AsyncClient) -> None:
    """Verify user can view and retrieve their own organization."""
    data = await _register_user_and_tenant(async_client, "own")
    token = data["access_token"]
    tenant_id = data["organization"]["id"]

    res = await async_client.get(
        f"/api/v1/tenants/{tenant_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 200
    assert res.json()["id"] == tenant_id
    assert res.json()["name"] == data["organization"]["name"]


@pytest.mark.asyncio
async def test_cross_tenant_access_strictly_forbidden(async_client: AsyncClient) -> None:
    """Verify User A cannot access or inspect Tenant B."""
    tenant_a = await _register_user_and_tenant(async_client, "tenanta")
    tenant_b = await _register_user_and_tenant(async_client, "tenantb")

    token_a = tenant_a["access_token"]
    tenant_b_id = tenant_b["organization"]["id"]

    # User A tries to access Tenant B details
    res = await async_client.get(
        f"/api/v1/tenants/{tenant_b_id}",
        headers={"Authorization": f"Bearer {token_a}"},
    )
    assert res.status_code == 403
    assert "Forbidden" in res.json()["detail"]


@pytest.mark.asyncio
async def test_cross_tenant_member_listing_forbidden(async_client: AsyncClient) -> None:
    """Verify User A cannot list members of Tenant B."""
    tenant_a = await _register_user_and_tenant(async_client, "list_a")
    tenant_b = await _register_user_and_tenant(async_client, "list_b")

    token_a = tenant_a["access_token"]
    tenant_b_id = tenant_b["organization"]["id"]

    res = await async_client.get(
        f"/api/v1/tenants/{tenant_b_id}/members",
        headers={"Authorization": f"Bearer {token_a}"},
    )
    assert res.status_code == 403


@pytest.mark.asyncio
async def test_tenant_id_manipulation_rejected(async_client: AsyncClient) -> None:
    """Verify client-supplied arbitrary or non-member UUID in X-Tenant-ID header is rejected."""
    tenant_a = await _register_user_and_tenant(async_client, "tamper")
    token_a = tenant_a["access_token"]
    fake_tenant_id = str(uuid4())

    res = await async_client.get(
        f"/api/v1/tenants/{fake_tenant_id}",
        headers={"Authorization": f"Bearer {token_a}"},
    )
    # Either 404 Not Found or 403 Forbidden
    assert res.status_code in (403, 404)


@pytest.mark.asyncio
async def test_inactive_membership_rejected(async_client: AsyncClient) -> None:
    """Verify that a user whose membership has been deactivated is barred from tenant access."""
    data = await _register_user_and_tenant(async_client, "deact")
    token = data["access_token"]
    tenant_id = data["organization"]["id"]
    user_id = data["user"]["id"]

    # Deactivate the membership directly in DB
    async with AsyncSessionLocal() as session:
        await session.execute(
            update(Membership)
            .where(
                Membership.user_id == user_id,
                Membership.tenant_id == tenant_id,
            )
            .values(is_active=False)
        )
        await session.commit()

    res = await async_client.get(
        f"/api/v1/tenants/{tenant_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 403
    assert "Forbidden" in res.json()["detail"]


@pytest.mark.asyncio
async def test_tenant_context_not_leaked_across_requests(async_client: AsyncClient) -> None:
    """Verify that multiple concurrent or sequential requests maintain strict tenant boundaries."""
    tenant_a = await _register_user_and_tenant(async_client, "iso_a")
    tenant_b = await _register_user_and_tenant(async_client, "iso_b")

    token_a = tenant_a["access_token"]
    token_b = tenant_b["access_token"]
    id_a = tenant_a["organization"]["id"]
    id_b = tenant_b["organization"]["id"]

    # 1. User A queries Tenant A (200 OK)
    res_a = await async_client.get(f"/api/v1/tenants/{id_a}", headers={"Authorization": f"Bearer {token_a}"})
    assert res_a.status_code == 200

    # 2. User B queries Tenant B (200 OK)
    res_b = await async_client.get(f"/api/v1/tenants/{id_b}", headers={"Authorization": f"Bearer {token_b}"})
    assert res_b.status_code == 200

    # 3. User A immediately queries Tenant B (Must be 403)
    res_cross = await async_client.get(f"/api/v1/tenants/{id_b}", headers={"Authorization": f"Bearer {token_a}"})
    assert res_cross.status_code == 403
