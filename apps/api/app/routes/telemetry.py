"""Chart data for the UI, read through the MCP tools (never raw PromQL from the browser).

GET /api/metrics?service=checkout&range=30m        p50/p95/p99, request rate, error rate
GET /api/services/{service}/deployments?hours=6    version history (deploy markers)

Only fixed, allow-listed queries over the Phase 3 recording rules are run.
"""

from __future__ import annotations

import asyncio
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Path, Query
from pydantic import BaseModel

from app.routes.system import McpConnectorDep

router = APIRouter()

SERVICE_PATTERN = r"^[a-z0-9][a-z0-9_-]{0,99}$"
RANGES = {"15m": 15, "30m": 30, "1h": 60, "6h": 360}
SERIES = {
    "request_rate": 'sum(service:http_requests:rate1m{{service="{s}"}})',
    "error_rate": 'max(service:http_errors:ratio_rate1m{{service="{s}"}})',
    "p50_latency_s": 'max(service:http_latency_seconds:p50_1m{{service="{s}"}})',
    "p95_latency_s": 'max(service:http_latency_seconds:p95_1m{{service="{s}"}})',
    "p99_latency_s": 'max(service:http_latency_seconds:p99_1m{{service="{s}"}})',
}


class Point(BaseModel):
    timestamp: str
    value: float | None


class MetricsResponse(BaseModel):
    service: str
    range: str
    status: Literal["ok", "partial", "unavailable"]
    errors: list[str]
    series: dict[str, list[Point]]


@router.get("/metrics", response_model=MetricsResponse)
async def service_metrics(
    connector: McpConnectorDep,
    service: Annotated[str, Query(pattern=SERVICE_PATTERN)],
    range: Annotated[Literal["15m", "30m", "1h", "6h"], Query()] = "30m",
) -> MetricsResponse:
    minutes = RANGES[range]
    async with connector() as tools:
        results = await asyncio.gather(
            *(
                tools.call("query_metrics", {"query": q.format(s=service),
                                             "start_time": f"now-{minutes}m"})
                for q in SERIES.values()
            )
        )  # fmt: skip
    series: dict[str, list[Point]] = {}
    errors: list[str] = []
    for name, result in zip(SERIES, results, strict=True):
        if result.get("status") in {"unavailable", "error"}:
            errors += [f"{name}: {e.get('error')}" for e in result.get("errors") or [{}]]
            continue
        rows = result.get("series") or []
        series[name] = [Point(**p) for p in rows[0]["points"]] if rows else []
    status: Literal["ok", "partial", "unavailable"] = (
        "ok" if not errors else ("partial" if series else "unavailable")
    )
    return MetricsResponse(
        service=service, range=range, status=status, errors=errors, series=series
    )


class DeploymentsResponse(BaseModel):
    service: str
    status: str
    errors: list[dict[str, Any]]
    deployments: list[dict[str, Any]]


@router.get("/services/{service}/deployments", response_model=DeploymentsResponse)
async def service_deployments(
    connector: McpConnectorDep,
    service: Annotated[str, Path(pattern=SERVICE_PATTERN)],
    hours: Annotated[int, Query(ge=1, le=72)] = 6,
) -> DeploymentsResponse:
    async with connector() as tools:
        result = await tools.call(
            "get_recent_deployments", {"service": service, "lookback_hours": hours}
        )
    return DeploymentsResponse(
        service=service,
        status=result.get("status", "ok"),
        errors=result.get("errors") or [],
        deployments=result.get("deployments") or [],
    )
