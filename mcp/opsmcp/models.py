"""Typed tool outputs. These become the MCP tools' published output schemas.

Every result carries ``status``:
  ok           all sources answered
  partial      some sources failed; ``errors`` says which, the rest is real data
  unavailable  nothing could be retrieved; values are null, never guessed

A missing value is ``None``. Tools never substitute defaults for telemetry
they could not read (spec section 26).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

ResultStatus = Literal["ok", "partial", "unavailable"]
HealthStatus = Literal["healthy", "degraded", "down", "unknown"]
ErrorCode = Literal[
    "metrics_unavailable",
    "logs_unavailable",
    "incidents_unavailable",
    "invalid_query",
    "query_too_large",
    "catalog_unavailable",
]


class SourceError(BaseModel):
    source: Literal["prometheus", "loki", "opspilot-api", "catalog"]
    error: ErrorCode
    detail: str


class ToolResult(BaseModel):
    status: ResultStatus = "ok"
    errors: list[SourceError] = Field(default_factory=list)


# --- get_service_health ------------------------------------------------------


class DependencyHealth(BaseModel):
    service: str
    status: HealthStatus
    error_rate: float | None
    p95_latency_ms: float | None


class ServiceHealth(ToolResult):
    service: str
    health: HealthStatus
    error_rate: float | None = Field(description="5xx ratio over the last minute (0-1)")
    p95_latency_ms: float | None
    request_rate: float | None = Field(description="Requests per second over the last minute")
    version: str | None
    targets_up: int | None = Field(description="Scrape targets reporting this service")
    reasons: list[str] = Field(default_factory=list, description="Why health is not 'healthy'")
    dependency_status: list[DependencyHealth] = Field(default_factory=list)


# --- query_metrics -----------------------------------------------------------


class MetricPoint(BaseModel):
    timestamp: datetime
    value: float | None


class MetricSeries(BaseModel):
    metric: dict[str, str]
    points: list[MetricPoint]


class MetricsResult(ToolResult):
    query: str
    start_time: datetime
    end_time: datetime
    step_seconds: int
    series: list[MetricSeries] = Field(default_factory=list)
    truncated: bool = False


# --- get_recent_logs ---------------------------------------------------------


class LogEntry(BaseModel):
    timestamp: datetime
    level: str | None
    message: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class LogsResult(ToolResult):
    service: str
    minutes: int
    severity: str | None
    entries: list[LogEntry] = Field(default_factory=list)
    truncated: bool = False


# --- get_recent_deployments --------------------------------------------------


class Deployment(BaseModel):
    version: str
    deployment_time: datetime = Field(description="First time this version was observed")
    last_seen: datetime
    status: Literal["active", "superseded"]
    deployed_before_window: bool = Field(
        description="Already running when the lookback window started; true deploy time unknown"
    )


class DeploymentsResult(ToolResult):
    service: str
    lookback_hours: int
    source: str = Field(default="prometheus app_info version history")
    deployments: list[Deployment] = Field(default_factory=list)


# --- get_service_dependencies ------------------------------------------------


class Dependency(BaseModel):
    service: str
    direction: Literal["downstream", "upstream"]
    sources: list[Literal["catalog", "telemetry"]]


class DependenciesResult(ToolResult):
    service: str
    known_service: bool = Field(description="Whether the service is in the service catalog")
    dependencies: list[Dependency] = Field(default_factory=list)


# --- get_incident_events -----------------------------------------------------


class IncidentEvent(BaseModel):
    timestamp: datetime | None
    kind: Literal["alert", "incident", "deployment"]
    summary: str
    details: dict[str, Any] = Field(default_factory=dict)


class IncidentEventsResult(ToolResult):
    service: str
    minutes: int
    events: list[IncidentEvent] = Field(default_factory=list)
