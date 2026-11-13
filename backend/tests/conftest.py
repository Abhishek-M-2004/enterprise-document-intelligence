"""Pytest configuration and test fixtures."""

import os
import sys
from typing import AsyncGenerator
import uuid
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

# Ensure backend root is on sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.db.session import AsyncSessionLocal, engine
from app.main import app


@pytest_asyncio.fixture(scope="session")
async def async_client() -> AsyncGenerator[AsyncClient, None]:
    """Asynchronous HTTP test client for FastAPI application."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client
    await engine.dispose()


@pytest_asyncio.fixture
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    """Database session fixture for direct database tests."""
    async with AsyncSessionLocal() as session:
        yield session


@pytest_asyncio.fixture
async def auth_headers(async_client: AsyncClient) -> dict:
    """Fixture providing authenticated headers for an isolated test tenant."""
    suf = uuid.uuid4().hex[:8]
    reg = await async_client.post(
        "/api/v1/auth/register",
        json={
            "full_name": f"Test User {suf}",
            "email": f"test_user_{suf}@example.com",
            "password": "Password123!",
            "organization_name": f"Test Tenant {suf}",
        },
    )
    data = reg.json()
    token = data["access_token"]
    tenant_id = data["organization"]["id"]
    return {
        "Authorization": f"Bearer {token}",
        "X-Tenant-ID": tenant_id,
    }
