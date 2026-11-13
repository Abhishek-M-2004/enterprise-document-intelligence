"""Pydantic schemas for application health and status monitoring."""

from datetime import datetime
from typing import Dict, Literal, Optional
from pydantic import BaseModel, Field

StatusType = Literal["healthy", "degraded", "unhealthy"]


class ComponentHealth(BaseModel):
    """Health status representation for a single infrastructure dependency."""

    status: Literal["healthy", "unhealthy"] = Field(
        ..., description="Operational status of the component"
    )
    latency_ms: Optional[float] = Field(
        None, description="Response time in milliseconds"
    )
    message: Optional[str] = Field(
        None, description="Optional diagnostic or error message"
    )


class HealthResponse(BaseModel):
    """Overall platform health response payload."""

    status: StatusType = Field(
        ..., description="Aggregated platform health status"
    )
    version: str = Field(..., description="Application semantic version")
    environment: str = Field(..., description="Running environment")
    timestamp: datetime = Field(
        default_factory=datetime.utcnow,
        description="UTC timestamp of the health verification",
    )
    services: Dict[str, ComponentHealth] = Field(
        default_factory=dict,
        description="Individual status of backing services (database, redis, qdrant)",
    )
