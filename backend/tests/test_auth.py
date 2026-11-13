"""Comprehensive test suite for Authentication and JWT Lifecycle."""

from datetime import datetime, timedelta, timezone
from uuid import uuid4
from httpx import AsyncClient
import pytest

from app.core.config import settings
from app.core.security import create_access_token


@pytest.mark.asyncio
async def test_successful_registration(async_client: AsyncClient) -> None:
    """Verify registration creates user, organization, owner membership, and issues tokens."""
    email = f"owner_{uuid4().hex[:8]}@enterprise.com"
    payload = {
        "full_name": "Alice Enterprise",
        "email": email,
        "password": "StrongPassword123!",
        "organization_name": "Acme Global Dynamics",
    }
    response = await async_client.post("/api/v1/auth/register", json=payload)
    assert response.status_code == 201
    data = response.json()
    assert "access_token" in data
    assert data["token_type"] == "bearer"
    assert data["user"]["email"] == email
    assert data["user"]["full_name"] == "Alice Enterprise"
    assert data["organization"]["name"] == "Acme Global Dynamics"
    assert data["role"] == "OWNER"
    # Verify secure cookie set
    assert settings.REFRESH_COOKIE_NAME in response.cookies


@pytest.mark.asyncio
async def test_duplicate_email_registration_rejected(async_client: AsyncClient) -> None:
    """Verify that registering with an existing email returns 400 Bad Request."""
    email = f"dup_{uuid4().hex[:8]}@enterprise.com"
    payload = {
        "full_name": "Bob Duplicate",
        "email": email,
        "password": "StrongPassword123!",
        "organization_name": "First Organization",
    }
    first_res = await async_client.post("/api/v1/auth/register", json=payload)
    assert first_res.status_code == 201

    dup_payload = {
        "full_name": "Bob Clone",
        "email": email,
        "password": "AnotherPassword456!",
        "organization_name": "Second Organization",
    }
    dup_res = await async_client.post("/api/v1/auth/register", json=dup_payload)
    assert dup_res.status_code == 400
    assert "already exists" in dup_res.json()["detail"]


@pytest.mark.asyncio
async def test_successful_login(async_client: AsyncClient) -> None:
    """Verify valid credentials return access tokens and user profile."""
    email = f"login_{uuid4().hex[:8]}@enterprise.com"
    reg_payload = {
        "full_name": "Carol Login",
        "email": email,
        "password": "CorrectPassword123!",
        "organization_name": "Carol Industries",
    }
    await async_client.post("/api/v1/auth/register", json=reg_payload)

    login_res = await async_client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "CorrectPassword123!"},
    )
    assert login_res.status_code == 200
    data = login_res.json()
    assert "access_token" in data
    assert data["user"]["email"] == email
    assert data["organization"]["name"] == "Carol Industries"
    assert data["role"] == "OWNER"


@pytest.mark.asyncio
async def test_invalid_password_rejected(async_client: AsyncClient) -> None:
    """Verify incorrect password returns 401 Unauthorized with generic message."""
    email = f"badpass_{uuid4().hex[:8]}@enterprise.com"
    await async_client.post(
        "/api/v1/auth/register",
        json={
            "full_name": "Dave Badpass",
            "email": email,
            "password": "OriginalPassword123!",
            "organization_name": "Dave Co",
        },
    )

    bad_res = await async_client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "WrongPassword999!"},
    )
    assert bad_res.status_code == 401
    assert "Incorrect email or password" in bad_res.json()["detail"]


@pytest.mark.asyncio
async def test_nonexistent_email_login_rejected(async_client: AsyncClient) -> None:
    """Verify nonexistent email returns identical 401 without revealing account absence."""
    bad_res = await async_client.post(
        "/api/v1/auth/login",
        json={"email": "nonexistent@enterprise.com", "password": "AnyPassword123!"},
    )
    assert bad_res.status_code == 401
    assert "Incorrect email or password" in bad_res.json()["detail"]


@pytest.mark.asyncio
async def test_invalid_and_expired_access_token_rejected(async_client: AsyncClient) -> None:
    """Verify that malformed and expired JWT access tokens are rejected with 401."""
    # 1. Malformed token
    res_bad = await async_client.get(
        "/api/v1/auth/me",
        headers={"Authorization": "Bearer not-a-real-token"},
    )
    assert res_bad.status_code == 401

    # 2. Expired token
    expired_token = create_access_token(
        user_id=uuid4(),
        expires_delta=timedelta(seconds=-10),
    )
    res_expired = await async_client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {expired_token}"},
    )
    assert res_expired.status_code == 401


@pytest.mark.asyncio
async def test_refresh_token_rotation_and_revocation(async_client: AsyncClient) -> None:
    """Verify refresh token rotation and rejection of revoked refresh tokens."""
    email = f"rot_{uuid4().hex[:8]}@enterprise.com"
    reg_res = await async_client.post(
        "/api/v1/auth/register",
        json={
            "full_name": "Eve Rotation",
            "email": email,
            "password": "Password12345!",
            "organization_name": "Eve Labs",
        },
    )
    raw_refresh_1 = reg_res.cookies.get(settings.REFRESH_COOKIE_NAME)
    assert raw_refresh_1 is not None

    # First rotation
    ref_res_1 = await async_client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": raw_refresh_1},
    )
    assert ref_res_1.status_code == 200
    data_1 = ref_res_1.json()
    assert "access_token" in data_1
    raw_refresh_2 = ref_res_1.cookies.get(settings.REFRESH_COOKIE_NAME)
    assert raw_refresh_2 is not None
    assert raw_refresh_2 != raw_refresh_1

    # Replay attack: try to reuse revoked raw_refresh_1
    replay_res = await async_client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": raw_refresh_1},
    )
    assert replay_res.status_code == 401
    assert "Revoked refresh token presented" in replay_res.json()["detail"]


@pytest.mark.asyncio
async def test_logout_revokes_session(async_client: AsyncClient) -> None:
    """Verify logout revokes the refresh token and clears session cookies."""
    email = f"logout_{uuid4().hex[:8]}@enterprise.com"
    reg_res = await async_client.post(
        "/api/v1/auth/register",
        json={
            "full_name": "Frank Logout",
            "email": email,
            "password": "Password12345!",
            "organization_name": "Frank Corp",
        },
    )
    raw_refresh = reg_res.cookies.get(settings.REFRESH_COOKIE_NAME)

    logout_res = await async_client.post(
        "/api/v1/auth/logout",
        json={"refresh_token": raw_refresh},
    )
    assert logout_res.status_code == 200
    assert logout_res.json()["message"] == "Successfully logged out."

    # Attempting to refresh with the logged-out token must fail
    ref_res = await async_client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": raw_refresh},
    )
    assert ref_res.status_code == 401


@pytest.mark.asyncio
async def test_get_current_user_me(async_client: AsyncClient) -> None:
    """Verify /api/v1/auth/me returns user profile and list of organizations."""
    email = f"profile_{uuid4().hex[:8]}@enterprise.com"
    reg_res = await async_client.post(
        "/api/v1/auth/register",
        json={
            "full_name": "Grace Hopper",
            "email": email,
            "password": "Password12345!",
            "organization_name": "US Navy Computing",
        },
    )
    access_token = reg_res.json()["access_token"]

    me_res = await async_client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {access_token}"},
    )
    assert me_res.status_code == 200
    data = me_res.json()
    assert data["email"] == email
    assert data["full_name"] == "Grace Hopper"
    assert len(data["memberships"]) == 1
    assert data["memberships"][0]["tenant_name"] == "US Navy Computing"
    assert data["memberships"][0]["role"] == "OWNER"
