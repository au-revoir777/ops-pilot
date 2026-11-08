"""Liveness (/health) and readiness (/ready) probes.

/health never touches dependencies: it answers "is the process alive?" and is
safe for frequent container health checks. /ready runs one cheap ``SELECT 1``
with a timeout and returns 503 if the database is unreachable, so load
balancers stop routing traffic without the container being restarted.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import structlog
from fastapi import APIRouter, Response
from pydantic import BaseModel
from sqlalchemy import text

from app.config import get_settings
from app.dependencies import SessionDep

logger = structlog.get_logger(__name__)

router = APIRouter()

SERVICE_NAME = "opspilot-api"
VERSION = "0.1.0"


class HealthResponse(BaseModel):
    status: str
    service: str
    version: str
    timestamp: str
    checks: dict[str, str]


@router.get("/health", response_model=HealthResponse)
async def health_check() -> HealthResponse:
    return HealthResponse(
        status="healthy",
        service=SERVICE_NAME,
        version=VERSION,
        timestamp=datetime.now(UTC).isoformat(),
        checks={"api": "healthy"},
    )


@router.get(
    "/ready",
    response_model=HealthResponse,
    responses={503: {"model": HealthResponse, "description": "A dependency is unavailable"}},
)
async def readiness(session: SessionDep, response: Response) -> HealthResponse:
    timeout = get_settings().db_readiness_timeout_seconds
    database = "healthy"
    try:
        await asyncio.wait_for(session.execute(text("SELECT 1")), timeout=timeout)
    except Exception as exc:  # any failure means "not ready"; details stay in logs
        logger.warning("readiness_database_check_failed", error_type=type(exc).__name__)
        database = "unhealthy"
        response.status_code = 503

    return HealthResponse(
        status="ready" if database == "healthy" else "not_ready",
        service=SERVICE_NAME,
        version=VERSION,
        timestamp=datetime.now(UTC).isoformat(),
        checks={"database": database},
    )
