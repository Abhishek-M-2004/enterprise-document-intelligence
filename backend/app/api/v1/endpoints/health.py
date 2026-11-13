"""Health and readiness monitoring endpoints."""

import asyncio
from datetime import datetime
from fastapi import APIRouter, Response, status

from app.core.config import settings
from app.core.metrics import generate_metrics_output
from app.core.qdrant_client import check_qdrant_connectivity
from app.core.redis_client import check_redis_connectivity
from app.db.session import check_db_connectivity
from app.schemas.health import ComponentHealth, HealthResponse, StatusType

router = APIRouter()


@router.get(
    "/health",
    response_model=HealthResponse,
    summary="Comprehensive Platform Health Check",
    description="Inspects real-time connectivity to PostgreSQL, Redis, and Qdrant vector database.",
)
async def get_health(response: Response) -> HealthResponse:
    """Aggregate health status of all infrastructure backing services."""
    # Run infrastructure probes concurrently with graceful error containment
    db_res, redis_res, qdrant_res = await asyncio.gather(
        check_db_connectivity(),
        check_redis_connectivity(),
        check_qdrant_connectivity(),
        return_exceptions=True,
    )

    def parse_probe_result(res: object) -> ComponentHealth:
        if isinstance(res, Exception):
            return ComponentHealth(status="unhealthy", latency_ms=0.0, message=str(res))
        if isinstance(res, tuple) and len(res) == 3:
            is_healthy, latency, err = res
            return ComponentHealth(
                status="healthy" if is_healthy else "unhealthy",
                latency_ms=latency,
                message=err,
            )
        return ComponentHealth(status="unhealthy", latency_ms=0.0, message="Unknown probe failure")

    services = {
        "database": parse_probe_result(db_res),
        "redis": parse_probe_result(redis_res),
        "qdrant": parse_probe_result(qdrant_res),
    }

    healthy_count = sum(1 for svc in services.values() if svc.status == "healthy")
    total_count = len(services)

    if healthy_count == total_count:
        overall_status: StatusType = "healthy"
        response.status_code = status.HTTP_200_OK
    elif healthy_count > 0:
        overall_status = "degraded"
        # In degraded mode (e.g. redis or qdrant down), return 200 with diagnostics or 503 if database down
        if services["database"].status == "unhealthy":
            response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        else:
            response.status_code = status.HTTP_200_OK
    else:
        overall_status = "unhealthy"
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE

    return HealthResponse(
        status=overall_status,
        version=settings.VERSION,
        environment=settings.ENVIRONMENT,
        timestamp=datetime.utcnow(),
        services=services,
    )


@router.get(
    "/health/live",
    summary="Liveness Probe",
    description="Kubernetes/Docker liveness probe indicating process is responsive.",
)
async def get_liveness() -> dict[str, str]:
    """Basic liveness check."""
    return {"status": "alive"}


@router.get(
    "/health/ready",
    summary="Readiness Probe",
    description="Indicates whether the application is ready to accept incoming traffic.",
)
async def get_readiness(response: Response) -> dict[str, str]:
    """Readiness probe checking critical database dependency."""
    is_healthy, _, err = await check_db_connectivity(timeout_seconds=2.0)
    if not is_healthy:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return {"status": "not_ready", "reason": err or "Database connection failed"}
    return {"status": "ready"}


@router.get(
    "/metrics",
    summary="Prometheus Metrics Endpoint",
    description="Prometheus-compatible real-time exposition of platform and RAG operational telemetry.",
)
@router.get(
    "/health/metrics",
    summary="Health Component Prometheus Metrics Endpoint",
    description="Prometheus-compatible real-time exposition of platform and RAG operational telemetry.",
)
async def get_prometheus_metrics() -> Response:
    """Expose application metrics in Prometheus text format."""
    return Response(
        content=generate_metrics_output(),
        media_type="text/plain; version=0.0.4; charset=utf-8",
    )

