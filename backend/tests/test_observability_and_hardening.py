"""Phase 7 automated tests for Observability, Structured Logging, Prometheus Metrics, and Rate Limiting."""

import logging
import pytest
from httpx import AsyncClient
import uuid

from app.core.logging import SensitiveDataFilter
from app.core.metrics import generate_metrics_output, record_api_request
from app.core.rate_limiter import RateLimiter
from app.core.tracing import trace_span


@pytest.mark.asyncio
async def test_sensitive_data_filter_masks_credentials():
    """Verify that sensitive patterns (passwords, tokens, api keys) are masked from log output."""
    filter_instance = SensitiveDataFilter()
    record = logging.LogRecord(
        name="test",
        level=logging.INFO,
        pathname="",
        lineno=0,
        msg="User authenticated password='SuperSecretPassword123' token='eyJhbGciOiJIUzI1NiJ9' secret=my_db_secret",
        args=(),
        exc_info=None,
    )
    filter_instance.filter(record)

    assert "SuperSecretPassword123" not in record.msg
    assert "eyJhbGciOiJIUzI1NiJ9" not in record.msg
    assert "********" in record.msg


@pytest.mark.asyncio
async def test_request_id_and_process_time_headers(async_client: AsyncClient):
    """Verify ObservabilityMiddleware generates/propagates X-Request-ID and X-Process-Time headers."""
    # 1. System generates a fresh Request-ID when none provided
    res1 = await async_client.get("/api/v1/health/live")
    assert res1.status_code == 200
    assert "x-request-id" in res1.headers
    assert "x-process-time" in res1.headers
    assert uuid.UUID(res1.headers["x-request-id"])

    # 2. System preserves and echoes back client-provided X-Request-ID
    custom_rid = str(uuid.uuid4())
    res2 = await async_client.get(
        "/api/v1/health/live",
        headers={"X-Request-ID": custom_rid},
    )
    assert res2.status_code == 200
    assert res2.headers["x-request-id"] == custom_rid


@pytest.mark.asyncio
async def test_prometheus_metrics_endpoint(async_client: AsyncClient):
    """Verify Prometheus metrics exposition endpoint returns expected Prometheus metric formats."""
    # Root metrics endpoint
    res = await async_client.get("/metrics")
    assert res.status_code == 200
    assert "text/plain" in res.headers["content-type"]
    content = res.text

    assert "rag_api_requests_total" in content
    assert "rag_api_request_duration_seconds" in content
    assert "rag_vector_search_latency_seconds" in content
    assert "rag_bm25_search_latency_seconds" in content
    assert "rag_reranker_latency_seconds" in content
    assert "rag_llm_requests_total" in content

    # Component health metrics endpoint
    res_health_metrics = await async_client.get("/api/v1/health/metrics")
    assert res_health_metrics.status_code == 200
    assert "rag_api_requests_total" in res_health_metrics.text


@pytest.mark.asyncio
async def test_opentelemetry_tracing_span():
    """Verify OpenTelemetry tracer creates spans and records timing attributes without exception."""
    with trace_span("TestStageSpan", attributes={"tenant_id": "test-tenant-123", "candidate_count": 10}) as span:
        assert span is not None


@pytest.mark.asyncio
async def test_rate_limiter_enforcement(async_client: AsyncClient):
    """Verify that requests exceeding configured rate limits return HTTP 429 Too Many Requests."""
    # Create a strict rate limiter allowing only 2 requests per window for this test
    strict_limiter = RateLimiter(requests_limit=2, window_seconds=10, tag=f"test_{uuid.uuid4().hex[:6]}")

    class MockRequest:
        def __init__(self, ip: str):
            self.client = type("Client", (), {"host": ip})
            self.state = type("State", (), {"tenant_id": None, "user_id": None})

    req = MockRequest("192.168.1.100")

    # Request 1: allowed
    await strict_limiter(req)
    # Request 2: allowed
    await strict_limiter(req)

    # Request 3: must trigger HTTP 429
    with pytest.raises(Exception) as excinfo:
        await strict_limiter(req)
    assert excinfo.value.status_code == 429
    assert "Rate limit exceeded" in str(excinfo.value.detail)
    assert "Retry-After" in excinfo.value.headers


@pytest.mark.asyncio
async def test_health_probes_liveness_vs_readiness(async_client: AsyncClient):
    """Verify difference between liveness probe (process responsiveness) and readiness probe (DB connectivity)."""
    # Liveness probe
    live_res = await async_client.get("/api/v1/health/live")
    assert live_res.status_code == 200
    assert live_res.json()["status"] == "alive"

    # Readiness probe
    ready_res = await async_client.get("/api/v1/health/ready")
    assert ready_res.status_code in [200, 503]
    if ready_res.status_code == 200:
        assert ready_res.json()["status"] == "ready"
