"""Comprehensive test suite for Role-Based Access Control (RBAC) Enforcement."""

from uuid import uuid4
from httpx import AsyncClient
import pytest


async def _setup_tenant_with_roles(
    client: AsyncClient,
) -> dict:
    """Helper to set up an organization with an OWNER, an ADMIN, and a MEMBER."""
    # 1. Register Owner
    owner_email = f"owner_{uuid4().hex[:8]}@rbac.com"
    owner_res = await client.post(
        "/api/v1/auth/register",
        json={
            "full_name": "Org Owner",
            "email": owner_email,
            "password": "Password123!",
            "organization_name": "RBAC Enterprise",
        },
    )
    assert owner_res.status_code == 201
    owner_data = owner_res.json()
    tenant_id = owner_data["organization"]["id"]
    owner_token = owner_data["access_token"]
    owner_id = owner_data["user"]["id"]

    # 2. Register future Admin user
    admin_email = f"admin_{uuid4().hex[:8]}@rbac.com"
    admin_reg = await client.post(
        "/api/v1/auth/register",
        json={
            "full_name": "Org Admin",
            "email": admin_email,
            "password": "Password123!",
            "organization_name": "Admin Personal Org",
        },
    )
    assert admin_reg.status_code == 201
    admin_token = admin_reg.json()["access_token"]
    admin_id = admin_reg.json()["user"]["id"]

    # 3. Register future Member user
    member_email = f"member_{uuid4().hex[:8]}@rbac.com"
    member_reg = await client.post(
        "/api/v1/auth/register",
        json={
            "full_name": "Org Member",
            "email": member_email,
            "password": "Password123!",
            "organization_name": "Member Personal Org",
        },
    )
    assert member_reg.status_code == 201
    member_token = member_reg.json()["access_token"]
    member_id = member_reg.json()["user"]["id"]

    # 4. Owner adds Admin as ADMIN
    add_admin_res = await client.post(
        f"/api/v1/tenants/{tenant_id}/members",
        headers={"Authorization": f"Bearer {owner_token}"},
        json={"email": admin_email, "role": "ADMIN"},
    )
    assert add_admin_res.status_code == 201

    # 5. Owner adds Member as MEMBER
    add_member_res = await client.post(
        f"/api/v1/tenants/{tenant_id}/members",
        headers={"Authorization": f"Bearer {owner_token}"},
        json={"email": member_email, "role": "MEMBER"},
    )
    assert add_member_res.status_code == 201

    return {
        "tenant_id": tenant_id,
        "owner": {"token": owner_token, "id": owner_id, "email": owner_email},
        "admin": {"token": admin_token, "id": admin_id, "email": admin_email},
        "member": {"token": member_token, "id": member_id, "email": member_email},
    }


@pytest.mark.asyncio
async def test_owner_can_update_organization(async_client: AsyncClient) -> None:
    """Verify OWNER can modify organization details."""
    setup = await _setup_tenant_with_roles(async_client)
    res = await async_client.patch(
        f"/api/v1/tenants/{setup['tenant_id']}",
        headers={"Authorization": f"Bearer {setup['owner']['token']}"},
        json={"name": "Renamed By Owner"},
    )
    assert res.status_code == 200
    assert res.json()["name"] == "Renamed By Owner"


@pytest.mark.asyncio
async def test_admin_and_member_cannot_update_organization(async_client: AsyncClient) -> None:
    """Verify neither ADMIN nor MEMBER can update organization settings."""
    setup = await _setup_tenant_with_roles(async_client)

    # Admin tries to update (Forbidden: OWNER only)
    res_admin = await async_client.patch(
        f"/api/v1/tenants/{setup['tenant_id']}",
        headers={"Authorization": f"Bearer {setup['admin']['token']}"},
        json={"name": "Hacked By Admin"},
    )
    assert res_admin.status_code == 403

    # Member tries to update
    res_member = await async_client.patch(
        f"/api/v1/tenants/{setup['tenant_id']}",
        headers={"Authorization": f"Bearer {setup['member']['token']}"},
        json={"name": "Hacked By Member"},
    )
    assert res_member.status_code == 403


@pytest.mark.asyncio
async def test_admin_can_manage_regular_members(async_client: AsyncClient) -> None:
    """Verify ADMIN can add and remove regular MEMBER users."""
    setup = await _setup_tenant_with_roles(async_client)

    # Register new user to invite
    new_email = f"new_{uuid4().hex[:8]}@rbac.com"
    await async_client.post(
        "/api/v1/auth/register",
        json={
            "full_name": "New Hire",
            "email": new_email,
            "password": "Password123!",
            "organization_name": "New Hire Org",
        },
    )

    # Admin adds new user as MEMBER
    add_res = await async_client.post(
        f"/api/v1/tenants/{setup['tenant_id']}/members",
        headers={"Authorization": f"Bearer {setup['admin']['token']}"},
        json={"email": new_email, "role": "MEMBER"},
    )
    assert add_res.status_code == 201
    new_user_id = add_res.json()["user_id"]

    # Admin removes this MEMBER
    del_res = await async_client.delete(
        f"/api/v1/tenants/{setup['tenant_id']}/members/{new_user_id}",
        headers={"Authorization": f"Bearer {setup['admin']['token']}"},
    )
    assert del_res.status_code == 200


@pytest.mark.asyncio
async def test_admin_cannot_assign_owner_role(async_client: AsyncClient) -> None:
    """Verify ADMIN cannot promote anyone to OWNER or invite an OWNER."""
    setup = await _setup_tenant_with_roles(async_client)

    new_email = f"target_{uuid4().hex[:8]}@rbac.com"
    await async_client.post(
        "/api/v1/auth/register",
        json={
            "full_name": "Target User",
            "email": new_email,
            "password": "Password123!",
            "organization_name": "Target Org",
        },
    )

    # Admin attempts to assign OWNER
    res = await async_client.post(
        f"/api/v1/tenants/{setup['tenant_id']}/members",
        headers={"Authorization": f"Bearer {setup['admin']['token']}"},
        json={"email": new_email, "role": "OWNER"},
    )
    assert res.status_code == 403
    assert "Administrators may only assign the MEMBER role" in res.json()["detail"]


@pytest.mark.asyncio
async def test_admin_cannot_modify_or_remove_owner(async_client: AsyncClient) -> None:
    """Verify ADMIN cannot alter the role of, or remove, an OWNER."""
    setup = await _setup_tenant_with_roles(async_client)

    # Admin tries to demote Owner to MEMBER
    patch_res = await async_client.patch(
        f"/api/v1/tenants/{setup['tenant_id']}/members/{setup['owner']['id']}",
        headers={"Authorization": f"Bearer {setup['admin']['token']}"},
        json={"role": "MEMBER"},
    )
    assert patch_res.status_code == 403

    # Admin tries to remove Owner
    del_res = await async_client.delete(
        f"/api/v1/tenants/{setup['tenant_id']}/members/{setup['owner']['id']}",
        headers={"Authorization": f"Bearer {setup['admin']['token']}"},
    )
    assert del_res.status_code == 403


@pytest.mark.asyncio
async def test_admin_cannot_remove_another_admin(async_client: AsyncClient) -> None:
    """Verify an ADMIN cannot remove another ADMIN."""
    setup = await _setup_tenant_with_roles(async_client)

    # Owner adds a second admin
    admin2_email = f"admin2_{uuid4().hex[:8]}@rbac.com"
    reg2 = await async_client.post(
        "/api/v1/auth/register",
        json={
            "full_name": "Admin Two",
            "email": admin2_email,
            "password": "Password123!",
            "organization_name": "Admin2 Org",
        },
    )
    admin2_id = reg2.json()["user"]["id"]
    await async_client.post(
        f"/api/v1/tenants/{setup['tenant_id']}/members",
        headers={"Authorization": f"Bearer {setup['owner']['token']}"},
        json={"email": admin2_email, "role": "ADMIN"},
    )

    # First admin tries to remove second admin
    del_res = await async_client.delete(
        f"/api/v1/tenants/{setup['tenant_id']}/members/{admin2_id}",
        headers={"Authorization": f"Bearer {setup['admin']['token']}"},
    )
    assert del_res.status_code == 403
    assert "Administrators cannot remove other administrators" in del_res.json()["detail"]


@pytest.mark.asyncio
async def test_member_cannot_manage_members(async_client: AsyncClient) -> None:
    """Verify regular MEMBER cannot list, add, update, or remove members."""
    setup = await _setup_tenant_with_roles(async_client)
    m_token = setup["member"]["token"]
    tid = setup["tenant_id"]

    # 1. List members (403)
    res_list = await async_client.get(
        f"/api/v1/tenants/{tid}/members",
        headers={"Authorization": f"Bearer {m_token}"},
    )
    assert res_list.status_code == 403

    # 2. Add member (403)
    res_add = await async_client.post(
        f"/api/v1/tenants/{tid}/members",
        headers={"Authorization": f"Bearer {m_token}"},
        json={"email": "some@user.com", "role": "MEMBER"},
    )
    assert res_add.status_code == 403

    # 3. Remove member (403)
    res_del = await async_client.delete(
        f"/api/v1/tenants/{tid}/members/{setup['admin']['id']}",
        headers={"Authorization": f"Bearer {m_token}"},
    )
    assert res_del.status_code == 403


@pytest.mark.asyncio
async def test_sole_owner_cannot_be_removed_or_demoted(async_client: AsyncClient) -> None:
    """Verify that an organization's sole OWNER cannot be removed or demoted."""
    setup = await _setup_tenant_with_roles(async_client)
    owner_token = setup["owner"]["token"]
    owner_id = setup["owner"]["id"]
    tid = setup["tenant_id"]

    # Sole owner tries to demote self to MEMBER
    patch_res = await async_client.patch(
        f"/api/v1/tenants/{tid}/members/{owner_id}",
        headers={"Authorization": f"Bearer {owner_token}"},
        json={"role": "MEMBER"},
    )
    assert patch_res.status_code == 400
    assert "must retain at least one active OWNER" in patch_res.json()["detail"]

    # Sole owner tries to remove self
    del_res = await async_client.delete(
        f"/api/v1/tenants/{tid}/members/{owner_id}",
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    assert del_res.status_code == 400
    assert "must retain at least one active OWNER" in del_res.json()["detail"]
