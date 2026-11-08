"""Tool implementations. Pure async functions over injected backends.

Each tool validates its input (raising ValueError, which MCP reports as a tool
error), queries only fixed read-only endpoints, and returns a typed result in
which unavailable data is reported, never invented.

Queries are built server-side from validated parameters; the only caller-
supplied query language is PromQL in ``query_metrics``, which is read-only by
design and bounded in time range, resolution and series count.
"""

from __future__ import annotations

import asyncio
import json
import math
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from opsmcp.backends import (
    BackendQueryError,
    BackendUnavailable,
    LokiClient,
    OpsPilotApiClient,
    PrometheusClient,
)
from opsmcp.catalog import SERVICE_NAME, CatalogError, ServiceCatalog
from opsmcp.config import McpSettings
from opsmcp.instrumentation import instrumented
from opsmcp.models import (
    DependenciesResult,
    Dependency,
    DependencyHealth,
    Deployment,
    DeploymentsResult,
    HealthStatus,
    IncidentEvent,
    IncidentEventsResult,
    LogEntry,
    LogsResult,
    MetricPoint,
    MetricSeries,
    MetricsResult,
    ServiceHealth,
    SourceError,
)

SEVERITIES = ("debug", "info", "warning", "error")
_LEVELS_AT_OR_ABOVE = {
    "debug": "debug|info|warning|error|critical",
    "info": "info|warning|error|critical",
    "warning": "warning|error|critical",
    "error": "error|critical",
}
_RELATIVE = re.compile(r"^now(?:-(\d+)([smhd]))?$")
_UNIT_SECONDS = {"s": 1, "m": 60, "h": 3600, "d": 86400}
_LOG_RESERVED = {"timestamp", "level", "event", "service", "msg", "message"}
MAX_PROMQL_CHARS = 2000


@dataclass
class ToolDeps:
    settings: McpSettings
    prometheus: PrometheusClient
    loki: LokiClient
    api: OpsPilotApiClient
    catalog: Callable[[], ServiceCatalog]  # raises CatalogError
    now: Callable[[], datetime] = lambda: datetime.now(UTC)


# ---------------------------------------------------------------------------
# Validation and parsing helpers
# ---------------------------------------------------------------------------


def validate_service(service: str) -> str:
    if not isinstance(service, str) or not SERVICE_NAME.match(service):
        raise ValueError(
            f"service must be a lowercase service name (letters, digits, '-', '_'), got {service!r}"
        )
    return service


def validate_minutes(minutes: int, settings: McpSettings) -> int:
    if not 1 <= minutes <= settings.max_lookback_minutes:
        raise ValueError(f"minutes must be between 1 and {settings.max_lookback_minutes}")
    return minutes


def parse_time(value: str, now: datetime) -> datetime:
    """ISO 8601 (``2026-11-08T07:00:00Z``) or relative (``now``, ``now-15m``)."""
    value = value.strip()
    match = _RELATIVE.match(value)
    if match:
        amount, unit = match.groups()
        return now - timedelta(seconds=int(amount) * _UNIT_SECONDS[unit]) if amount else now
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"time must be ISO 8601 or 'now-<n><s|m|h|d>', got {value!r}") from exc
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _value(sample: dict[str, Any]) -> float | None:
    raw = float(sample["value"][1])
    return None if math.isnan(raw) or math.isinf(raw) else raw


def _first(results: list[dict[str, Any]]) -> float | None:
    return _value(results[0]) if results else None


def _sel(service: str) -> str:
    # Safe: service already matched ^[a-z0-9][a-z0-9_-]*$ (no quotes or braces).
    return f'service="{service}"'


def _prom_error(exc: BackendUnavailable | BackendQueryError) -> SourceError:
    if isinstance(exc, BackendQueryError):
        return SourceError(source="prometheus", error="invalid_query", detail=exc.reason)
    return SourceError(source="prometheus", error="metrics_unavailable", detail=exc.reason)


def _status(errors: list[SourceError], have_data: bool) -> str:
    if not errors:
        return "ok"
    return "partial" if have_data else "unavailable"


def _ts(seconds: float) -> datetime:
    return datetime.fromtimestamp(float(seconds), tz=UTC)


# ---------------------------------------------------------------------------
# get_service_health
# ---------------------------------------------------------------------------


async def _red(prom: PrometheusClient, service: str) -> tuple[float | None, float | None]:
    err, p95 = await asyncio.gather(
        prom.instant(f"max(service:http_errors:ratio_rate1m{{{_sel(service)}}})"),
        prom.instant(f"max(service:http_latency_seconds:p95_1m{{{_sel(service)}}})"),
    )
    p95_s = _first(p95)
    return _first(err), (round(p95_s * 1000, 1) if p95_s is not None else None)


def classify(
    *,
    targets_total: int,
    targets_up: int,
    error_rate: float | None,
    p95_ms: float | None,
    settings: McpSettings,
) -> tuple[HealthStatus, list[str]]:
    if targets_total == 0:
        return "unknown", ["no scrape target has reported this service in the last hour"]
    if targets_up == 0:
        return "down", [f"0 of {targets_total} scrape targets are up"]
    reasons = []
    if targets_up < targets_total:
        reasons.append(f"{targets_total - targets_up} of {targets_total} scrape targets are down")
    if error_rate is not None and error_rate > settings.degraded_error_ratio:
        reasons.append(f"5xx ratio {error_rate:.1%} above {settings.degraded_error_ratio:.0%}")
    if p95_ms is not None and p95_ms > settings.degraded_p95_ms:
        reasons.append(f"p95 latency {p95_ms:.0f} ms above {settings.degraded_p95_ms:.0f} ms")
    return ("degraded" if reasons else "healthy"), reasons


@instrumented("get_service_health")
async def get_service_health(deps: ToolDeps, *, service: str) -> ServiceHealth:
    service = validate_service(service)
    prom, settings = deps.prometheus, deps.settings
    try:
        targets, rate, version_rows, (error_rate, p95_ms) = await asyncio.gather(
            prom.instant(
                "max by (instance) (up) * on (instance) group_left () "
                f"max by (instance) (last_over_time(app_info{{{_sel(service)}}}[1h]))"
            ),
            prom.instant(f"sum(service:http_requests:rate1m{{{_sel(service)}}})"),
            prom.instant(f"app_info{{{_sel(service)}}}"),
            _red(prom, service),
        )
    except (BackendUnavailable, BackendQueryError) as exc:
        return ServiceHealth(
            service=service, health="unknown", error_rate=None, p95_latency_ms=None,
            request_rate=None, version=None, targets_up=None,
            status="unavailable", errors=[_prom_error(exc)],
        )  # fmt: skip

    targets_total = len(targets)
    targets_up = sum(1 for t in targets if _value(t) == 1.0)
    versions = sorted({row["metric"].get("version", "") for row in version_rows} - {""})
    health, reasons = classify(
        targets_total=targets_total,
        targets_up=targets_up,
        error_rate=error_rate,
        p95_ms=p95_ms,
        settings=settings,
    )
    request_rate = _first(rate)
    if health in {"healthy", "degraded"} and not request_rate:
        reasons.append("no traffic in the last minute; error rate and latency may be empty")

    errors: list[SourceError] = []
    dependencies: list[DependencyHealth] = []
    try:
        names = await _downstream_names(deps, service, errors)
        for name in names:
            dep_err, dep_p95 = await _red(prom, name)
            dep_health, _ = classify(
                targets_total=1, targets_up=1, error_rate=dep_err, p95_ms=dep_p95,
                settings=settings,
            )  # fmt: skip
            if dep_err is None and dep_p95 is None:
                dep_health = "unknown"
            dependencies.append(
                DependencyHealth(service=name, status=dep_health, error_rate=dep_err,
                                 p95_latency_ms=dep_p95)
            )  # fmt: skip
    except (BackendUnavailable, BackendQueryError) as exc:
        errors.append(_prom_error(exc))

    return ServiceHealth(
        service=service,
        health=health,
        error_rate=round(error_rate, 4) if error_rate is not None else None,
        p95_latency_ms=p95_ms,
        request_rate=round(request_rate, 3) if request_rate is not None else None,
        version=", ".join(versions) or None,
        targets_up=targets_up,
        reasons=reasons,
        dependency_status=dependencies,
        status=_status(errors, have_data=True),
        errors=errors,
    )


async def _downstream_names(deps: ToolDeps, service: str, errors: list[SourceError]) -> list[str]:
    names: set[str] = set()
    try:
        entry = deps.catalog().get(service)
        if entry:
            names.update(entry.depends_on)
    except CatalogError as exc:
        errors.append(SourceError(source="catalog", error="catalog_unavailable", detail=str(exc)))
    observed = await deps.prometheus.instant(
        "sum by (target) (increase(downstream_request_duration_seconds_count"
        f"{{{_sel(service)}}}[1h])) > 0"
    )
    names.update(r["metric"]["target"] for r in observed if "target" in r["metric"])
    return sorted(n for n in names if SERVICE_NAME.match(n))


# ---------------------------------------------------------------------------
# query_metrics
# ---------------------------------------------------------------------------


@instrumented("query_metrics")
async def query_metrics(
    deps: ToolDeps,
    *,
    query: str,
    start_time: str,
    end_time: str = "now",
    step_seconds: int | None = None,
) -> MetricsResult:
    settings = deps.settings
    query = query.strip()
    if not query or len(query) > MAX_PROMQL_CHARS:
        raise ValueError(f"query must be 1-{MAX_PROMQL_CHARS} characters of PromQL")
    now = deps.now()
    start, end = parse_time(start_time, now), parse_time(end_time, now)
    if end <= start:
        raise ValueError("end_time must be after start_time")
    span = (end - start).total_seconds()
    if span > settings.max_query_range_hours * 3600:
        raise ValueError(f"time range is limited to {settings.max_query_range_hours} hours")
    # Coarsest of: requested step, enough to stay under the point budget, 15 s floor.
    min_step = max(15, math.ceil(span / settings.max_points_per_series))
    step = max(step_seconds or 0, min_step)

    result = MetricsResult(query=query, start_time=start, end_time=end, step_seconds=step)
    try:
        rows = await deps.prometheus.range(query, start, end, step)
    except (BackendUnavailable, BackendQueryError) as exc:
        result.status, result.errors = "unavailable", [_prom_error(exc)]
        return result

    result.truncated = len(rows) > settings.max_series
    result.series = [
        MetricSeries(
            metric=row.get("metric", {}),
            points=[
                MetricPoint(
                    timestamp=_ts(ts),
                    value=None if math.isnan(float(v)) or math.isinf(float(v)) else float(v),
                )
                for ts, v in row.get("values", [])
            ],
        )
        for row in rows[: settings.max_series]
    ]
    return result


# ---------------------------------------------------------------------------
# get_recent_logs
# ---------------------------------------------------------------------------


def parse_log_line(line: str, labels: dict[str, str], ts_ns: str) -> LogEntry:
    timestamp = datetime.fromtimestamp(int(ts_ns) / 1e9, tz=UTC)
    try:
        payload = json.loads(line)
    except ValueError:
        payload = None
    if not isinstance(payload, dict):
        return LogEntry(timestamp=timestamp, level=labels.get("level"), message=line[:2000])
    message = payload.get("event") or payload.get("message") or payload.get("msg") or line
    metadata = {
        k: (v[:500] if isinstance(v, str) else v)
        for k, v in payload.items()
        if k not in _LOG_RESERVED
    }
    return LogEntry(
        timestamp=timestamp,
        level=payload.get("level") or labels.get("level"),
        message=str(message)[:2000],
        metadata=metadata,
    )


@instrumented("get_recent_logs")
async def get_recent_logs(
    deps: ToolDeps,
    *,
    service: str,
    minutes: int = 30,
    severity: str | None = None,
    limit: int = 100,
) -> LogsResult:
    service = validate_service(service)
    minutes = validate_minutes(minutes, deps.settings)
    if severity is not None:
        severity = severity.lower()
        if severity == "warn":
            severity = "warning"
        if severity not in SEVERITIES:
            raise ValueError(f"severity must be one of {', '.join(SEVERITIES)}")
    if not 1 <= limit <= deps.settings.max_log_lines:
        raise ValueError(f"limit must be between 1 and {deps.settings.max_log_lines}")

    logql = f"{{{_sel(service)}}}"
    if severity:
        logql += f' | level=~"{_LEVELS_AT_OR_ABOVE[severity]}"'
    end = deps.now()
    result = LogsResult(service=service, minutes=minutes, severity=severity)
    try:
        streams = await deps.loki.query_range(logql, end - timedelta(minutes=minutes), end, limit)
    except (BackendUnavailable, BackendQueryError) as exc:
        result.status = "unavailable"
        result.errors = [SourceError(source="loki", error="logs_unavailable", detail=exc.reason)]
        return result

    entries = [
        parse_log_line(line, stream.get("stream", {}), ts)
        for stream in streams
        for ts, line in stream.get("values", [])
    ]
    entries.sort(key=lambda e: e.timestamp, reverse=True)
    result.truncated = len(entries) >= limit
    result.entries = entries[:limit]
    return result


# ---------------------------------------------------------------------------
# get_recent_deployments
# ---------------------------------------------------------------------------


async def _deployments(
    deps: ToolDeps, service: str, lookback: timedelta
) -> tuple[list[Deployment], list[SourceError]]:
    end = deps.now()
    start = end - lookback
    step = max(60, math.ceil(lookback.total_seconds() / 300))
    try:
        rows = await deps.prometheus.range(
            f"max by (version) (app_info{{{_sel(service)}}})", start, end, step
        )
    except (BackendUnavailable, BackendQueryError) as exc:
        return [], [_prom_error(exc)]

    latest = max((float(v[-1][0]) for r in rows if (v := r.get("values"))), default=None)
    deployments = []
    for row in rows:
        values = row.get("values") or []
        version = row.get("metric", {}).get("version")
        if not values or not version:
            continue
        first, last = float(values[0][0]), float(values[-1][0])
        deployments.append(
            Deployment(
                version=version,
                deployment_time=_ts(first),
                last_seen=_ts(last),
                status="active"
                if latest is not None and latest - last <= 2 * step
                else "superseded",
                deployed_before_window=first - start.timestamp() <= step,
            )
        )
    deployments.sort(key=lambda d: d.deployment_time, reverse=True)
    return deployments, []


@instrumented("get_recent_deployments")
async def get_recent_deployments(
    deps: ToolDeps, *, service: str, lookback_hours: int | None = None
) -> DeploymentsResult:
    service = validate_service(service)
    hours = lookback_hours or deps.settings.deployment_lookback_hours
    if not 1 <= hours <= 72:
        raise ValueError("lookback_hours must be between 1 and 72")
    deployments, errors = await _deployments(deps, service, timedelta(hours=hours))
    return DeploymentsResult(
        service=service,
        lookback_hours=hours,
        deployments=deployments,
        status=_status(errors, have_data=False),
        errors=errors,
    )


# ---------------------------------------------------------------------------
# get_service_dependencies
# ---------------------------------------------------------------------------


@instrumented("get_service_dependencies")
async def get_service_dependencies(deps: ToolDeps, *, service: str) -> DependenciesResult:
    service = validate_service(service)
    errors: list[SourceError] = []
    found: dict[tuple[str, str], set[str]] = {}

    def add(name: str, direction: str, source: str) -> None:
        if SERVICE_NAME.match(name) and name != service:
            found.setdefault((name, direction), set()).add(source)

    known = False
    try:
        catalog = deps.catalog()
        entry = catalog.get(service)
        known = entry is not None
        for name in entry.depends_on if entry else ():
            add(name, "downstream", "catalog")
        for name in catalog.dependents_of(service):
            add(name, "upstream", "catalog")
    except CatalogError as exc:
        errors.append(SourceError(source="catalog", error="catalog_unavailable", detail=str(exc)))

    try:
        downstream, upstream = await asyncio.gather(
            deps.prometheus.instant(
                "sum by (target) (increase(downstream_request_duration_seconds_count"
                f"{{{_sel(service)}}}[1h])) > 0"
            ),
            deps.prometheus.instant(
                "sum by (service) (increase(downstream_request_duration_seconds_count"
                f'{{target="{service}"}}[1h])) > 0'
            ),
        )
        for row in downstream:
            add(row["metric"].get("target", ""), "downstream", "telemetry")
        for row in upstream:
            add(row["metric"].get("service", ""), "upstream", "telemetry")
    except (BackendUnavailable, BackendQueryError) as exc:
        errors.append(_prom_error(exc))

    dependencies = [
        Dependency(service=name, direction=direction, sources=sorted(sources))
        for (name, direction), sources in sorted(found.items())
    ]
    have_data = len(errors) < 2
    return DependenciesResult(
        service=service,
        known_service=known,
        dependencies=dependencies,
        status=_status(errors, have_data),
        errors=errors,
    )


# ---------------------------------------------------------------------------
# get_incident_events
# ---------------------------------------------------------------------------


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


@instrumented("get_incident_events")
async def get_incident_events(
    deps: ToolDeps, *, service: str, minutes: int = 60
) -> IncidentEventsResult:
    """Alerts, OpsPilot incidents and deployments for a service, newest first."""
    service = validate_service(service)
    minutes = validate_minutes(minutes, deps.settings)
    window_start = deps.now() - timedelta(minutes=minutes)
    events: list[IncidentEvent] = []
    errors: list[SourceError] = []

    async def alerts() -> None:
        try:
            for alert in await deps.prometheus.alerts():
                labels = alert.get("labels", {})
                if labels.get("service") != service:
                    continue
                events.append(
                    IncidentEvent(
                        timestamp=_parse_iso(alert.get("activeAt")),
                        kind="alert",
                        summary=f"{labels.get('alertname', 'alert')} ({alert.get('state')})",
                        details={
                            "severity": labels.get("severity"),
                            "state": alert.get("state"),
                            "summary": alert.get("annotations", {}).get("summary"),
                            "value": alert.get("value"),
                        },
                    )
                )
        except (BackendUnavailable, BackendQueryError) as exc:
            errors.append(_prom_error(exc))

    async def incidents() -> None:
        try:
            for incident in await deps.api.list_incidents(limit=100):
                created = _parse_iso(incident.get("created_at"))
                if incident.get("service_name") != service or (created and created < window_start):
                    continue
                events.append(
                    IncidentEvent(
                        timestamp=created,
                        kind="incident",
                        summary=f"{incident.get('severity')} {incident.get('title')}",
                        details={
                            "incident_id": incident.get("id"),
                            "status": incident.get("status"),
                        },
                    )
                )
        except (BackendUnavailable, BackendQueryError) as exc:
            errors.append(
                SourceError(source="opspilot-api", error="incidents_unavailable", detail=exc.reason)
            )

    async def deployments() -> None:
        lookback = timedelta(minutes=max(minutes, 60))
        found, deploy_errors = await _deployments(deps, service, lookback)
        errors.extend(e for e in deploy_errors if e not in errors)
        for d in found:
            if not d.deployed_before_window and d.deployment_time >= window_start:
                events.append(
                    IncidentEvent(
                        timestamp=d.deployment_time,
                        kind="deployment",
                        summary=f"version {d.version} first observed",
                        details={"version": d.version, "status": d.status},
                    )
                )

    await asyncio.gather(alerts(), incidents(), deployments())
    epoch = datetime.min.replace(tzinfo=UTC)
    events.sort(key=lambda e: e.timestamp or epoch, reverse=True)
    sources_failed = {e.source for e in errors}
    return IncidentEventsResult(
        service=service,
        minutes=minutes,
        events=events,
        status=_status(errors, have_data=len(sources_failed) < 2),
        errors=errors,
    )
