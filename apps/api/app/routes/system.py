"""System endpoints: monitored services and dependency health.

GET /api/services  services OpsPilot knows about: registered workloads (database)
                   merged with services currently exporting telemetry (via MCP)
GET /api/health    dependency status for the investigation path: database,
                   MCP server, knowledge base, LLM configuration
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from datetime import UTC, datetime
from typing import Annotated, Literal

import httpx
import structlog
from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel
from sqlalchemy import func, select, text

from app.agents.tools import ToolClient, connect_mcp
from app.config import get_settings
from app.db.models.knowledge import Document
from app.db.models.workload import Workload
from app.dependencies import SessionDep

logger = structlog.get_logger(__name__)
router = APIRouter()

McpConnector = Callable[[], AbstractAsyncContextManager[ToolClient]]


def get_mcp_connector() -> McpConnector:
    settings = get_settings()
    token = settings.mcp_auth_token.get_secret_value() if settings.mcp_auth_token else None

    @asynccontextmanager
    async def connect() -> AsyncIterator[ToolClient]:
        async with connect_mcp(settings.mcp_server_url, token, timeout=10) as client:
            yield client

    return connect


async def probe_mcp() -> bool:
    url = get_settings().mcp_server_url.rstrip("/")
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            return (await client.get(f"{url}/health")).status_code == 200
    except httpx.HTTPError:
        return False


def get_mcp_probe() -> Callable[[], Awaitable[bool]]:
    return probe_mcp


McpConnectorDep = Annotated[McpConnector, Depends(get_mcp_connector)]
McpProbeDep = Annotated[Callable[[], Awaitable[bool]], Depends(get_mcp_probe)]


class ServiceInfo(BaseModel):
    name: str
    project: str | None
    sources: list[Literal["registered", "telemetry"]]
    # Filled when ?health=true (via the MCP get_service_health tool).
    health: str | None = None
    p95_latency_ms: float | None = None
    error_rate: float | None = None
    request_rate: float | None = None
    version: str | None = None


class ServicesResponse(BaseModel):
    services: list[ServiceInfo]
    telemetry_status: Literal["ok", "unavailable"]


MAX_HEALTH_LOOKUPS = 25


@router.get("/services", response_model=ServicesResponse)
async def list_services(
    session: SessionDep, connector: McpConnectorDep, health: bool = False
) -> ServicesResponse:
    registered = (await session.execute(select(Workload.name))).scalars().all()
    found: dict[str, ServiceInfo] = {
        name: ServiceInfo(name=name, project=None, sources=["registered"]) for name in registered
    }
    telemetry_status: Literal["ok", "unavailable"] = "ok"
    async with connector() as tools:
        result = await tools.call(
            "query_metrics",
            {"query": "count by (service, project) (app_info)", "start_time": "now-15m"},
        )
        if result.get("status") in {"unavailable", "error"}:
            telemetry_status = "unavailable"
        for series in result.get("series") or []:
            labels = series.get("metric", {})
            name = labels.get("service")
            if not name:
                continue
            info = found.setdefault(name, ServiceInfo(name=name, project=None, sources=[]))
            info.project = info.project or labels.get("project")
            if "telemetry" not in info.sources:
                info.sources.append("telemetry")
        if health:
            targets = [s for s in found.values() if "telemetry" in s.sources][:MAX_HEALTH_LOOKUPS]
            results = await asyncio.gather(
                *(tools.call("get_service_health", {"service": s.name}) for s in targets)
            )
            for info, h in zip(targets, results, strict=True):
                if h.get("status") in {"unavailable", "error"}:
                    info.health = "unknown"
                    continue
                info.health = h.get("health")
                info.p95_latency_ms = h.get("p95_latency_ms")
                info.error_rate = h.get("error_rate")
                info.request_rate = h.get("request_rate")
                info.version = h.get("version")
    return ServicesResponse(
        services=sorted(found.values(), key=lambda s: s.name), telemetry_status=telemetry_status
    )


class DependencyHealth(BaseModel):
    status: Literal["ok", "degraded", "down"]
    timestamp: str
    checks: dict[str, str]


@router.get(
    "/health",
    response_model=DependencyHealth,
    responses={503: {"model": DependencyHealth, "description": "Database unavailable"}},
)
async def dependency_health(
    session: SessionDep, response: Response, mcp_probe: McpProbeDep
) -> DependencyHealth:
    """Investigations need the database; MCP and the knowledge base only degrade them."""
    settings = get_settings()
    checks: dict[str, str] = {}
    try:
        await asyncio.wait_for(session.execute(text("SELECT 1")), timeout=2)
        checks["database"] = "ok"
        documents = await session.scalar(select(func.count()).select_from(Document))
        checks["knowledge_base"] = "ok" if documents else "empty"
    except Exception as exc:
        logger.warning(
            "dependency_check_failed", dependency="database", error_type=type(exc).__name__
        )
        checks["database"] = "down"
        checks["knowledge_base"] = "unknown"
    checks["mcp"] = "ok" if await mcp_probe() else "down"
    checks["llm"] = "disabled" if settings.llm_provider == "none" else "configured"

    if checks["database"] == "down":
        status, response.status_code = "down", 503
    elif checks["mcp"] != "ok" or checks["knowledge_base"] != "ok":
        status = "degraded"
    else:
        status = "ok"
    return DependencyHealth(status=status, timestamp=datetime.now(UTC).isoformat(), checks=checks)


class PublicConfig(BaseModel):
    """Configuration that is safe to show in the UI. Never secrets or connection strings."""

    environment: str
    version: str
    read_only: bool
    llm_provider: str
    llm_model: str | None
    incident_lab_enabled: bool
    grafana_url: str | None


@router.get("/config", response_model=PublicConfig)
async def public_config() -> PublicConfig:
    from app.routes.health import VERSION

    settings = get_settings()
    return PublicConfig(
        environment=settings.app_env,
        version=VERSION,
        # The agent has no remediation endpoints at all (spec section 17).
        read_only=True,
        llm_provider=settings.llm_provider,
        llm_model=settings.llm_model if settings.llm_provider != "none" else None,
        incident_lab_enabled=settings.enable_incident_lab,
        grafana_url=settings.public_grafana_url,
    )
