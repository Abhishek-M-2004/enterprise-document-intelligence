"""Phase 9 Security Audit: Authentication & Authorization Security Tests.

Tests JWT expiration, signature forgery, tampering, refresh token rotation,
replay attack detection, and absence of sensitive information in error messages.
"""

from datetime import datetime, timedelta, timezone
import uuid
import jwt
import pytest
from httpx import AsyncClient

from app.core.config import settings
from app.core.security import create_access_token


@pytest.mark.asyncio
async def test_expired_access_token_rejected(async_client: AsyncClient):
    """Verify expired JWT access token is rejected with HTTP 401 Unauthorized."""
    user_id = uuid.uuid4()
    expired_payload = {
        "sub": str(user_id),
        "type": "access",
        "exp": datetime.now(timezone.utc) - timedelta(minutes=10),
        "iat": datetime.now(timezone.utc) - timedelta(minutes=30),
    }
    expired_token = jwt.encode(expired_payload, settings.SECRET_KEY, algorithm=settings.JWT_ALGORITHM)

    res = await async_client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {expired_token}"},
    )
    assert res.status_code == 401
    assert "detail" in res.json()


@pytest.mark.asyncio
async def test_forged_signature_token_rejected(async_client: AsyncClient):
    """Verify JWT signed with a bogus/forged secret key is rejected with HTTP 401."""
    user_id = uuid.uuid4()
    payload = {
        "sub": str(user_id),
        "type": "access",
        "exp": datetime.now(timezone.utc) + timedelta(minutes=15),
    }
    forged_token = jwt.encode(payload, "forged-attacker-secret-key-12345678", algorithm="HS256")

    res = await async_client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {forged_token}"},
    )
    assert res.status_code == 401


@pytest.mark.asyncio
async def test_tampered_payload_rejected(async_client: AsyncClient):
    """Verify tampering with an authentic token payload invalidates the signature."""
    suf = uuid.uuid4().hex[:8]
    reg = await async_client.post(
        "/api/v1/auth/register",
        json={"full_name": f"User {suf}", "email": f"user_{suf}@corp.com", "password": "Password123!", "organization_name": f"Org {suf}"},
    )
    valid_token = reg.json()["access_token"]
    parts = valid_token.split(".")
    # Tamper payload component (middle part)
    tampered_token = f"{parts[0]}.eyJzdWIiOiAiYWRtaW4ifQ.{parts[2]}"

    res = await async_client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {tampered_token}"},
    )
    assert res.status_code == 401


@pytest.mark.asyncio
async def test_refresh_token_rotation_and_revocation(async_client: AsyncClient):
    """Verify refresh token rotation and that revoked refresh tokens cannot be reused."""
    suf = uuid.uuid4().hex[:8]
    reg = await async_client.post(
        "/api/v1/auth/register",
        json={"full_name": f"Refresh User {suf}", "email": f"refresh_{suf}@corp.com", "password": "Password123!", "organization_name": f"Refresh Org {suf}"},
    )
    cookies = reg.cookies

    # First refresh succeeds and rotates the refresh cookie
    ref_1 = await async_client.post("/api/v1/auth/refresh", cookies=cookies)
    assert ref_1.status_code == 200
    assert "access_token" in ref_1.json()

    # User explicitly logs out
    logout_res = await async_client.post("/api/v1/auth/logout", cookies=cookies)
    assert logout_res.status_code == 200

    # Old refresh token is revoked; using it now must return 401
    ref_revoked = await async_client.post("/api/v1/auth/refresh", cookies=cookies)
    assert ref_revoked.status_code == 401


@pytest.mark.asyncio
async def test_error_responses_contain_no_stack_traces(async_client: AsyncClient):
    """Verify error responses do not leak tracebacks, internal paths, or secrets."""
    # Send malformed UUID path
    res = await async_client.get("/api/v1/documents/not-a-valid-uuid")
    assert res.status_code in [401, 404, 422]
    content = res.text
    assert "Traceback" not in content
    assert "sqlalchemy" not in content.lower()
    assert settings.SECRET_KEY not in content
