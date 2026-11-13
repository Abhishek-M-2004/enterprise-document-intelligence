"""Observability, Request Correlation, and Structured Logging Middleware."""

from contextvars import ContextVar
import json
import logging
import time
from typing import Callable, Optional
import uuid
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.core.metrics import record_api_error, record_api_request

# Context variables for request correlation
request_id_ctx: ContextVar[Optional[str]] = ContextVar("request_id_ctx", default=None)
tenant_id_ctx: ContextVar[Optional[str]] = ContextVar("tenant_id_ctx", default=None)
user_id_ctx: ContextVar[Optional[str]] = ContextVar("user_id_ctx", default=None)

logger = logging.getLogger("app.access")


class ObservabilityMiddleware(BaseHTTPMiddleware):
    """FastAPI/Starlette middleware for distributed request tracing and structured logging."""

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        # 1. Resolve or generate Request ID
        request_id = request.headers.get("X-Request-ID")
        if not request_id:
            request_id = str(uuid.uuid4())
        token_rid = request_id_ctx.set(request_id)

        start_time = time.perf_counter()
        status_code = 500

        try:
            response = await call_next(request)
            status_code = response.status_code
        except Exception as exc:
            duration_s = time.perf_counter() - start_time
            duration_ms = round(duration_s * 1000, 2)
            record_api_request(endpoint=request.url.path, method=request.method, status_code=500, duration_s=duration_s)
            record_api_error(endpoint=request.url.path, error_type=exc.__class__.__name__)

            # Structured JSON log entry on unhandled failure
            log_payload = {
                "event": "http_request_failed",
                "request_id": request_id,
                "method": request.method,
                "path": request.url.path,
                "status_code": 500,
                "duration_ms": duration_ms,
                "error": str(exc),
                "error_type": exc.__class__.__name__,
            }
            logger.error(json.dumps(log_payload))
            request_id_ctx.reset(token_rid)
            raise exc

        duration_s = time.perf_counter() - start_time
        duration_ms = round(duration_s * 1000, 2)

        # 2. Inject telemetry headers
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Process-Time"] = f"{duration_ms}ms"

        # 3. Prometheus metrics recording
        record_api_request(endpoint=request.url.path, method=request.method, status_code=status_code, duration_s=duration_s)
        if status_code >= 500:
            record_api_error(endpoint=request.url.path, error_type=f"HTTP_{status_code}")

        # 4. Structured JSON access log
        # Exclude high-frequency health probes from verbose logging if desired
        if not request.url.path.endswith("/health/live") and not request.url.path.endswith("/metrics"):
            log_payload = {
                "event": "http_request",
                "request_id": request_id,
                "method": request.method,
                "path": request.url.path,
                "status_code": status_code,
                "duration_ms": duration_ms,
                "client_ip": request.client.host if request.client else "unknown",
            }
            logger.info(json.dumps(log_payload))

        request_id_ctx.reset(token_rid)
        return response
