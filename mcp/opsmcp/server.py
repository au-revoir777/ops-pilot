"""OpsPilot MCP server (official MCP Python SDK, Streamable HTTP transport).

    uvicorn opsmcp.server:app --host 0.0.0.0 --port 8001

Endpoints:
  POST /mcp      MCP JSON-RPC (tools/list, tools/call ...), optional bearer auth
  GET  /health   liveness
  GET  /metrics  Prometheus metrics (tool calls, latency, backend latency)

Stateless HTTP mode with JSON responses: any replica can serve any request,
and there is no session state to lose on restart.
"""

from __future__ import annotations

import hmac
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated

import httpx
import structlog
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from pydantic import Field
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp, Receive, Scope, Send

from opsmcp import tools
from opsmcp.backends import LokiClient, OpsPilotApiClient, PrometheusClient
from opsmcp.catalog import CatalogError, ServiceCatalog
from opsmcp.config import McpSettings, get_settings
from opsmcp.instrumentation import configure_logging
from opsmcp.models import (
    DependenciesResult,
    DeploymentsResult,
    IncidentEventsResult,
    LogsResult,
    MetricsResult,
    ServiceHealth,
)

logger = structlog.get_logger(__name__)

INSTRUCTIONS = (
    "Read-only operational tools for SRE incident investigation: service health, "
    "PromQL metrics, logs, deployments (from version telemetry), dependencies and "
    "incident events. No tool executes commands or changes infrastructure. When a "
    "result has status 'partial' or 'unavailable', treat the missing data as unknown "
    "evidence, never as healthy."
)

ServiceName = Annotated[
    str,
    Field(
        description="Service name as used in metrics, e.g. 'checkout'",
        pattern=r"^[a-z0-9][a-z0-9_-]{0,99}$",
    ),
]


class CachedCatalog:
    """Re-reads the catalog file when it changes (no restart to onboard services)."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._mtime: float | None = None
        self._catalog: ServiceCatalog | None = None

    def __call__(self) -> ServiceCatalog:
        try:
            mtime = self.path.stat().st_mtime
        except OSError as exc:
            raise CatalogError(f"service catalog not found at {self.path}") from exc
        if self._catalog is None or mtime != self._mtime:
            self._catalog = ServiceCatalog.load(self.path)
            self._mtime = mtime
        return self._catalog


def build_deps(
    settings: McpSettings, transport: httpx.AsyncBaseTransport | None = None
) -> tools.ToolDeps:
    client = httpx.AsyncClient(timeout=settings.backend_timeout_seconds, transport=transport)
    return tools.ToolDeps(
        settings=settings,
        prometheus=PrometheusClient(client, settings.prometheus_url),
        loki=LokiClient(client, settings.loki_url),
        api=OpsPilotApiClient(
            client,
            settings.api_url,
            {"X-API-Key": settings.api_key.get_secret_value()} if settings.api_key else None,
        ),
        catalog=CachedCatalog(Path(settings.catalog_path)),
    )


def build_server(deps: tools.ToolDeps) -> FastMCP:
    mcp = FastMCP(
        "OpsPilot MCP",
        instructions=INSTRUCTIONS,
        stateless_http=True,
        json_response=True,
        # Reached by service name inside the Compose/VPC network, not via localhost.
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
    )

    @mcp.tool(annotations={"readOnlyHint": True, "openWorldHint": False})
    async def get_service_health(service: ServiceName) -> ServiceHealth:
        """Current health of a service: up targets, 5xx ratio, p95 latency, request rate,
        deployed version, reasons it is not healthy, and the health of its dependencies."""
        return await tools.get_service_health(deps, service=service)

    @mcp.tool(annotations={"readOnlyHint": True, "openWorldHint": False})
    async def query_metrics(
        query: Annotated[
            str, Field(description="PromQL expression", max_length=tools.MAX_PROMQL_CHARS)
        ],
        start_time: Annotated[str, Field(description="ISO 8601 or relative, e.g. 'now-30m'")],
        end_time: Annotated[str, Field(description="ISO 8601 or 'now'")] = "now",
        step_seconds: Annotated[int | None, Field(ge=15, le=3600)] = None,
    ) -> MetricsResult:
        """Run a read-only PromQL range query. Range, resolution and series count are capped.
        Useful recording rules: service:http_latency_seconds:p95_1m,
        service:http_errors:ratio_rate1m, service:http_requests:rate1m,
        service_operation:db_query_seconds:p95_1m."""
        return await tools.query_metrics(
            deps, query=query, start_time=start_time, end_time=end_time, step_seconds=step_seconds
        )

    @mcp.tool(annotations={"readOnlyHint": True, "openWorldHint": False})
    async def get_recent_logs(
        service: ServiceName,
        minutes: Annotated[int, Field(ge=1, le=10080)] = 30,
        severity: Annotated[
            str | None, Field(description="Minimum level: debug, info, warning or error")
        ] = None,
        limit: Annotated[int, Field(ge=1, le=1000)] = 100,
    ) -> LogsResult:
        """Recent structured log entries for a service (newest first), optionally only at or
        above a severity. Each entry has timestamp, level, message and metadata such as
        request_id, route, latency_ms or query_time_ms."""
        return await tools.get_recent_logs(
            deps, service=service, minutes=minutes, severity=severity, limit=limit
        )

    @mcp.tool(annotations={"readOnlyHint": True, "openWorldHint": False})
    async def get_recent_deployments(
        service: ServiceName,
        lookback_hours: Annotated[int | None, Field(ge=1, le=72)] = None,
    ) -> DeploymentsResult:
        """Versions of a service seen in the lookback window, derived from the app_info
        version label: when each version first appeared and whether it is still active."""
        return await tools.get_recent_deployments(
            deps, service=service, lookback_hours=lookback_hours
        )

    @mcp.tool(annotations={"readOnlyHint": True, "openWorldHint": False})
    async def get_service_dependencies(service: ServiceName) -> DependenciesResult:
        """Upstream and downstream dependencies of a service, from the service catalog and
        from observed service-to-service traffic, with the source of each."""
        return await tools.get_service_dependencies(deps, service=service)

    @mcp.tool(annotations={"readOnlyHint": True, "openWorldHint": False})
    async def get_incident_events(
        service: ServiceName,
        minutes: Annotated[int, Field(ge=1, le=10080)] = 60,
    ) -> IncidentEventsResult:
        """Timeline of alerts, OpsPilot incidents and deployments for a service in the
        last N minutes, newest first."""
        return await tools.get_incident_events(deps, service=service, minutes=minutes)

    @mcp.custom_route("/health", methods=["GET"])
    async def health(_request: Request) -> Response:
        return JSONResponse({"status": "healthy", "service": deps.settings.service_name})

    @mcp.custom_route("/metrics", methods=["GET"])
    async def metrics(_request: Request) -> Response:
        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

    return mcp


class BearerAuthMiddleware:
    """Require ``Authorization: Bearer <token>`` on the MCP endpoint when configured.

    /health and /metrics stay open for probes and Prometheus (internal network).
    """

    OPEN_PATHS = frozenset({"/health", "/metrics"})

    def __init__(self, app: ASGIApp, token: str | None) -> None:
        self.app = app
        self.expected = f"Bearer {token}".encode() if token else None

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if self.expected and scope["type"] == "http" and scope["path"] not in self.OPEN_PATHS:
            provided = dict(scope["headers"]).get(b"authorization", b"")
            if not hmac.compare_digest(provided, self.expected):
                response = JSONResponse({"error": "unauthorized"}, status_code=401)
                await response(scope, receive, send)
                return
        await self.app(scope, receive, send)


def create_app(
    settings: McpSettings | None = None, transport: httpx.AsyncBaseTransport | None = None
) -> ASGIApp:
    settings = settings or get_settings()
    configure_logging(settings.service_name, settings.log_level)
    deps = build_deps(settings, transport)
    mcp = build_server(deps)
    starlette_app = mcp.streamable_http_app()
    inner_lifespan = starlette_app.router.lifespan_context

    @asynccontextmanager
    async def lifespan(app) -> AsyncIterator[None]:
        logger.info("mcp_server_starting", tools=len(await mcp.list_tools()))
        async with inner_lifespan(app):
            yield
        await deps.prometheus.client.aclose()

    starlette_app.router.lifespan_context = lifespan
    token = settings.mcp_auth_token.get_secret_value() if settings.mcp_auth_token else None
    starlette_app.state.mcp = mcp
    return BearerAuthMiddleware(starlette_app, token)


app = create_app()
