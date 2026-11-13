"""Unit and integration tests for application health, root endpoints, and configuration safety."""

import pytest
from httpx import AsyncClient

from app.core.config import Settings, settings
from app.core.logging import SensitiveDataFilter
from app.core.qdrant_client import check_qdrant_connectivity
from app.core.redis_client import check_redis_connectivity
from app.db.session import check_db_connectivity
from app.workers.celery_app import celery_app, health_ping


@pytest.mark.asyncio
async def test_root_endpoint(async_client: AsyncClient) -> None:
    """Verify root endpoint returns valid metadata and 200 OK status."""
    response = await async_client.get("/")
    assert response.status_code == 200
    data = response.json()
    assert data["service"] == settings.PROJECT_NAME
    assert data["version"] == settings.VERSION
    assert data["status"] == "operational"
    assert "docs_url" in data
    assert "health_url" in data


@pytest.mark.asyncio
async def test_liveness_endpoint(async_client: AsyncClient) -> None:
    """Verify liveness probe returns 200 OK and alive status."""
    response = await async_client.get("/api/v1/health/live")
    assert response.status_code == 200
    assert response.json() == {"status": "alive"}


@pytest.mark.asyncio
async def test_readiness_endpoint(async_client: AsyncClient) -> None:
    """Verify readiness probe responds with appropriate status based on database state."""
    response = await async_client.get("/api/v1/health/ready")
    assert response.status_code in (200, 503)
    data = response.json()
    assert "status" in data
    assert data["status"] in ("ready", "not_ready")


@pytest.mark.asyncio
async def test_health_endpoint_structure(async_client: AsyncClient) -> None:
    """Verify /api/v1/health responds with the correct schema and diagnostic components."""
    response = await async_client.get("/api/v1/health")
    assert response.status_code in (200, 503)
    data = response.json()
    assert "status" in data
    assert data["status"] in ("healthy", "degraded", "unhealthy")
    assert "services" in data
    assert "database" in data["services"]
    assert "redis" in data["services"]
    assert "qdrant" in data["services"]
    assert "latency_ms" in data["services"]["database"]


@pytest.mark.asyncio
async def test_component_probes_do_not_crash() -> None:
    """Verify that individual health probes return structured diagnostics without unhandled exceptions."""
    db_ok, db_lat, _ = await check_db_connectivity(timeout_seconds=1.0)
    assert isinstance(db_ok, bool)
    assert isinstance(db_lat, float)

    redis_ok, redis_lat, _ = await check_redis_connectivity()
    assert isinstance(redis_ok, bool)
    assert isinstance(redis_lat, float)

    qdrant_ok, qdrant_lat, _ = await check_qdrant_connectivity()
    assert isinstance(qdrant_ok, bool)
    assert isinstance(qdrant_lat, float)


def test_settings_secrets_masking() -> None:
    """Ensure sensitive credentials are never revealed in sanitized settings."""
    sanitized = settings.get_sanitized_dict()
    assert sanitized["POSTGRES_PASSWORD"] == "********"
    assert sanitized["SECRET_KEY"] == "********"
    if settings.REDIS_PASSWORD:
        assert sanitized["REDIS_PASSWORD"] == "********"
    # Ensure raw password string does not appear anywhere in values
    for k, v in sanitized.items():
        if k not in ("DATABASE_HOST", "REDIS_HOST", "QDRANT_HOST"):
            assert settings.POSTGRES_PASSWORD not in str(v)


def test_production_constraints_enforced() -> None:
    """Ensure insecure settings or wildcard CORS are rejected in production."""
    with pytest.raises(ValueError, match="Wildcard"):
        Settings(
            ENVIRONMENT="production",
            SECRET_KEY="a-very-strong-32-character-secret-key-prod",
            BACKEND_CORS_ORIGINS=["*"],
        )

    with pytest.raises(ValueError, match="SECRET_KEY"):
        Settings(
            ENVIRONMENT="production",
            SECRET_KEY="dev-insecure-secret-key",
            BACKEND_CORS_ORIGINS=["https://app.company.com"],
        )


def test_logging_sensitive_data_filter() -> None:
    """Verify the logging filter scrubs passwords and bearer tokens."""
    scrubbed = SensitiveDataFilter._sanitize("Connecting with password=super_secret_123 and token=xyz987")
    assert "super_secret_123" not in scrubbed
    assert "xyz987" not in scrubbed
    assert "********" in scrubbed


def test_celery_task_registration() -> None:
    """Verify Celery app has configured tasks registered."""
    registered = celery_app.tasks
    assert "app.workers.celery_app.health_ping" in registered
    result = health_ping()
    assert result == "pong"
