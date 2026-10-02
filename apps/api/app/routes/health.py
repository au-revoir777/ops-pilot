"""Health-check endpoints.

Provides liveness and readiness probes for Docker / ECS health checks.
"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter()


class HealthResponse(BaseModel):
    """Structured health-check response."""

    status: str
    service: str
    version: str
    timestamp: str
    checks: dict[str, str]


@router.get("/health", response_model=HealthResponse)
async def health_check() -> HealthResponse:
    """Liveness / readiness probe.

    Returns service status and basic dependency checks.
    In later phases, this will verify DB, MCP, and observability connectivity.
    """
    return HealthResponse(
        status="healthy",
        service="opspilot-api",
        version="0.1.0",
        timestamp=datetime.now(UTC).isoformat(),
        checks={
            "api": "healthy",
            "database": "not_configured",
            "mcp": "not_configured",
            "rag": "not_configured",
        },
    )


@router.get("/ready")
async def readiness() -> dict[str, str]:
    """Kubernetes/ECS readiness probe."""
    return {"status": "ready"}
