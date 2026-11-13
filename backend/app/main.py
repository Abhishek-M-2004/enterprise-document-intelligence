"""Main FastAPI Application Entrypoint."""

from contextlib import asynccontextmanager
from typing import Any, AsyncGenerator, Dict
from fastapi import FastAPI, Response
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.router import api_router
from app.core.config import settings
from app.core.logging import logger, setup_logging
from app.core.metrics import generate_metrics_output
from app.core.middleware import ObservabilityMiddleware
from app.db.session import engine


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan manager for graceful resource allocation and cleanup."""
    # Startup sequence
    setup_logging()
    logger.info("Initializing %s (v%s) in '%s' mode...", settings.PROJECT_NAME, settings.VERSION, settings.ENVIRONMENT)
    sanitized_config = settings.get_sanitized_dict()
    logger.info("Database host configured: %s", sanitized_config.get("DATABASE_HOST"))
    logger.info("Redis host configured: %s", sanitized_config.get("REDIS_HOST"))
    logger.info("Qdrant host configured: %s", sanitized_config.get("QDRANT_HOST"))
    logger.info("Allowed CORS origins: %s", settings.BACKEND_CORS_ORIGINS)

    yield

    # Shutdown sequence
    logger.info("Shutting down %s...", settings.PROJECT_NAME)
    await engine.dispose()
    logger.info("Database connection pools safely disposed.")


app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.VERSION,
    description=(
        "Production-grade foundation for a Multi-Tenant Enterprise Document Intelligence "
        "Platform supporting isolated tenant storage, hybrid search, and asynchronous RAG pipelines."
    ),
    openapi_url=f"{settings.API_V1_STR}/openapi.json",
    docs_url=f"{settings.API_V1_STR}/docs",
    redoc_url=f"{settings.API_V1_STR}/redoc",
    lifespan=lifespan,
)

# CORS Configuration
if settings.BACKEND_CORS_ORIGINS:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.BACKEND_CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

# Observability, Request Correlation, and Metrics Middleware
app.add_middleware(ObservabilityMiddleware)

# Register API v1 Router
app.include_router(api_router, prefix=settings.API_V1_STR)


@app.get(
    "/metrics",
    summary="Prometheus Root Metrics",
    description="Exposes platform metrics in Prometheus text format for system-level scrapers.",
    tags=["Observability"],
)
async def prometheus_metrics() -> Response:
    """Root Prometheus exposition endpoint."""
    return Response(
        content=generate_metrics_output(),
        media_type="text/plain; version=0.0.4; charset=utf-8",
    )



@app.get(
    "/",
    summary="Platform Root Endpoint",
    description="Returns platform metadata, operational status, and API documentation links.",
    tags=["Root"],
)
async def root() -> Dict[str, Any]:
    """Root endpoint exposing service metadata."""
    return {
        "service": settings.PROJECT_NAME,
        "version": settings.VERSION,
        "status": "operational",
        "environment": settings.ENVIRONMENT,
        "docs_url": f"{settings.API_V1_STR}/docs",
        "health_url": f"{settings.API_V1_STR}/health",
    }
