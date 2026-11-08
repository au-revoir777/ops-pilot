"""Unit tests for every MCP tool (fake backends, no containers)."""

from __future__ import annotations

import json
from datetime import timedelta

import pytest
from prometheus_client import REGISTRY

from mcp_fakes import NOW, FakeBackends, make_deps, vector
from opsmcp import tools
from opsmcp.catalog import CatalogError, ServiceCatalog

pytestmark = pytest.mark.unit

CHECKOUT = '{service="checkout"}'


def healthy_checkout(fake: FakeBackends, *, p95: float = 0.18, errors: float = 0.0) -> None:
    fake.instant = {
        "max by (instance) (up)": vector(({"instance": "checkout:8080"}, 1)),
        f"service:http_requests:rate1m{CHECKOUT}": vector(({}, 4.2)),
        f"app_info{CHECKOUT}": vector(({"service": "checkout", "version": "1.8.2"}, 1)),
        f"service:http_errors:ratio_rate1m{CHECKOUT}": vector(({}, errors)),
        f"service:http_latency_seconds:p95_1m{CHECKOUT}": vector(({}, p95)),
        "downstream_request_duration_seconds_count": vector(({"target": "payments"}, 120)),
        'ratio_rate1m{service="payments"}': vector(({}, 0.0)),
        'p95_1m{service="payments"}': vector(({}, 0.09)),
        'ratio_rate1m{service="users"}': vector(({}, 0.0)),
        'p95_1m{service="users"}': vector(({}, 0.05)),
    }


# ---------------------------------------------------------------------------
# Validation shared by all tools
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "service", ["Checkout", "", 'checkout"} or vector(1)', "a b", "../etc", "x" * 101]
)
async def test_invalid_service_names_rejected_before_any_query(service):
    fake = FakeBackends()
    deps = make_deps(fake)
    for tool in (
        tools.get_service_health,
        tools.get_recent_logs,
        tools.get_recent_deployments,
        tools.get_service_dependencies,
        tools.get_incident_events,
    ):
        with pytest.raises(ValueError, match="service must be"):
            await tool(deps, service=service)
    assert fake.requests == []


def test_parse_time():
    assert tools.parse_time("now", NOW) == NOW
    assert tools.parse_time("now-15m", NOW) == NOW - timedelta(minutes=15)
    assert tools.parse_time("now-2h", NOW) == NOW - timedelta(hours=2)
    assert tools.parse_time("2026-11-08T11:00:00Z", NOW) == NOW - timedelta(hours=1)
    with pytest.raises(ValueError):
        tools.parse_time("yesterday", NOW)


# ---------------------------------------------------------------------------
# get_service_health
# ---------------------------------------------------------------------------


async def test_health_healthy_service_with_dependencies():
    fake = FakeBackends()
    healthy_checkout(fake)
    result = await tools.get_service_health(make_deps(fake), service="checkout")

    assert result.status == "ok"
    assert result.health == "healthy"
    assert result.p95_latency_ms == 180.0
    assert result.error_rate == 0.0
    assert result.request_rate == 4.2
    assert result.version == "1.8.2"
    assert result.targets_up == 1
    # Catalog (users, payments) merged with telemetry (payments).
    assert {d.service: d.status for d in result.dependency_status} == {
        "payments": "healthy",
        "users": "healthy",
    }


async def test_health_degraded_on_latency_and_errors():
    fake = FakeBackends()
    healthy_checkout(fake, p95=2.1, errors=0.12)
    result = await tools.get_service_health(make_deps(fake), service="checkout")
    assert result.health == "degraded"
    assert any("p95 latency 2100 ms" in r for r in result.reasons)
    assert any("5xx ratio 12.0%" in r for r in result.reasons)


async def test_health_down_when_targets_not_up():
    fake = FakeBackends()
    healthy_checkout(fake)
    fake.instant["max by (instance) (up)"] = vector(({"instance": "checkout:8080"}, 0))
    result = await tools.get_service_health(make_deps(fake), service="checkout")
    assert result.health == "down"


async def test_health_unknown_service_returns_nulls_not_guesses():
    fake = FakeBackends()
    result = await tools.get_service_health(make_deps(fake), service="ghost")
    assert result.health == "unknown"
    assert result.error_rate is None and result.p95_latency_ms is None
    assert result.version is None
    assert result.status == "ok"  # backends answered; there was simply no data


async def test_health_prometheus_unavailable():
    fake = FakeBackends()
    fake.down.add("prometheus.test")
    result = await tools.get_service_health(make_deps(fake), service="checkout")
    assert result.status == "unavailable"
    assert result.health == "unknown"
    assert result.errors[0].error == "metrics_unavailable"
    assert result.p95_latency_ms is None


async def test_health_survives_missing_catalog():
    fake = FakeBackends()
    healthy_checkout(fake)
    result = await tools.get_service_health(make_deps(fake, catalog=None), service="checkout")
    assert result.status == "partial"
    assert result.errors[0].error == "catalog_unavailable"
    assert [d.service for d in result.dependency_status] == ["payments"]  # telemetry only


# ---------------------------------------------------------------------------
# query_metrics
# ---------------------------------------------------------------------------


async def test_query_metrics_returns_series():
    fake = FakeBackends()
    t = NOW.timestamp()
    fake.range_result = [
        {"metric": {"service": "checkout"}, "values": [[t - 60, "0.2"], [t, "NaN"]]}
    ]
    result = await tools.query_metrics(
        make_deps(fake), query="service:http_latency_seconds:p95_1m", start_time="now-30m"
    )
    assert result.status == "ok"
    assert result.series[0].metric == {"service": "checkout"}
    assert [p.value for p in result.series[0].points] == [0.2, None]
    assert result.step_seconds == 15


async def test_query_metrics_caps_resolution_and_series():
    fake = FakeBackends()
    fake.range_result = [{"metric": {"i": str(i)}, "values": []} for i in range(60)]
    deps = make_deps(fake, max_series=50, max_points_per_series=100)
    result = await tools.query_metrics(deps, query="up", start_time="now-24h", step_seconds=15)
    assert result.step_seconds == 864  # 24h / 100 points
    assert len(result.series) == 50 and result.truncated


@pytest.mark.parametrize(
    ("query", "start", "end", "match"),
    [
        ("", "now-1h", "now", "query must be"),
        ("x" * 2001, "now-1h", "now", "query must be"),
        ("up", "now", "now-1h", "after start_time"),
        ("up", "now-25h", "now", "limited to 24 hours"),
        ("up", "last tuesday", "now", "ISO 8601"),
    ],
)
async def test_query_metrics_validation(query, start, end, match):
    with pytest.raises(ValueError, match=match):
        await tools.query_metrics(
            make_deps(FakeBackends()), query=query, start_time=start, end_time=end
        )


async def test_query_metrics_invalid_promql_is_reported():
    fake = FakeBackends()
    fake.status_code["prometheus.test"] = 400
    result = await tools.query_metrics(make_deps(fake), query="sum(", start_time="now-5m")
    assert result.status == "unavailable"
    assert result.errors[0].error == "invalid_query"
    assert "parse error" in result.errors[0].detail


async def test_query_metrics_prometheus_down():
    fake = FakeBackends()
    fake.status_code["prometheus.test"] = 503
    result = await tools.query_metrics(make_deps(fake), query="up", start_time="now-5m")
    assert result.errors[0].error == "metrics_unavailable"


# ---------------------------------------------------------------------------
# get_recent_logs
# ---------------------------------------------------------------------------


def loki_line(ts_offset_s: int, **fields) -> list[str]:
    ns = int((NOW.timestamp() - ts_offset_s) * 1e9)
    return [str(ns), json.dumps(fields)]


async def test_logs_parsed_newest_first_with_metadata():
    fake = FakeBackends()
    slow_query = loki_line(
        5,
        event="slow_query_detected",
        level="warning",
        operation="select_cart_items",
        query_time_ms=1900,
        request_id="r1",
        service="checkout",
    )
    plain = [str(int(NOW.timestamp() * 1e9)), "plain text line"]
    fake.loki_streams = [
        {
            "stream": {"service": "checkout", "level": "warning"},
            "values": [slow_query, loki_line(60, event="request_slow", level="warning")],
        },
        {"stream": {"service": "checkout", "level": "info"}, "values": [plain]},
    ]
    result = await tools.get_recent_logs(make_deps(fake), service="checkout", minutes=15)

    assert [e.message for e in result.entries] == [
        "plain text line",
        "slow_query_detected",
        "request_slow",
    ]
    slow = result.entries[1]
    assert slow.level == "warning"
    assert slow.metadata == {
        "operation": "select_cart_items",
        "query_time_ms": 1900,
        "request_id": "r1",
    }
    assert result.entries[0].level == "info"  # from the stream label


async def test_logs_severity_builds_server_side_filter():
    fake = FakeBackends()
    await tools.get_recent_logs(make_deps(fake), service="checkout", severity="WARN")
    logql = fake.queries()[0]
    assert logql == '{service="checkout"} | level=~"warning|error|critical"'


@pytest.mark.parametrize(
    ("kwargs", "match"),
    [
        ({"minutes": 0}, "minutes"),
        ({"minutes": 100_000}, "minutes"),
        ({"severity": "fatal"}, "severity"),
        ({"limit": 5000}, "limit"),
    ],
)
async def test_logs_validation(kwargs, match):
    with pytest.raises(ValueError, match=match):
        await tools.get_recent_logs(make_deps(FakeBackends()), service="checkout", **kwargs)


async def test_logs_loki_unavailable():
    fake = FakeBackends()
    fake.down.add("loki.test")
    result = await tools.get_recent_logs(make_deps(fake), service="checkout")
    assert result.status == "unavailable"
    assert result.errors[0].error == "logs_unavailable"
    assert result.entries == []


# ---------------------------------------------------------------------------
# get_recent_deployments
# ---------------------------------------------------------------------------


def version_series(version: str, start_offset_s: int, end_offset_s: int, step: int = 300):
    t = NOW.timestamp()
    return {
        "metric": {"version": version},
        "values": [[t - o, "1"] for o in range(start_offset_s, end_offset_s - 1, -step)],
    }


async def test_deployments_from_version_history():
    fake = FakeBackends()
    # 1.8.1 ran from the start of the window until 1 h ago; 1.8.2 since then.
    fake.range_result = [
        version_series("1.8.1", 24 * 3600, 3600),
        version_series("1.8.2", 3300, 0),
    ]
    result = await tools.get_recent_deployments(make_deps(fake), service="checkout")
    assert [(d.version, d.status) for d in result.deployments] == [
        ("1.8.2", "active"),
        ("1.8.1", "superseded"),
    ]
    assert result.deployments[0].deployment_time == NOW - timedelta(seconds=3300)
    assert result.deployments[0].deployed_before_window is False
    assert result.deployments[1].deployed_before_window is True


async def test_deployments_validation_and_outage():
    with pytest.raises(ValueError, match="lookback_hours"):
        await tools.get_recent_deployments(
            make_deps(FakeBackends()), service="checkout", lookback_hours=500
        )
    fake = FakeBackends()
    fake.down.add("prometheus.test")
    result = await tools.get_recent_deployments(make_deps(fake), service="checkout")
    assert result.status == "unavailable" and result.deployments == []


# ---------------------------------------------------------------------------
# get_service_dependencies
# ---------------------------------------------------------------------------


async def test_dependencies_merge_catalog_and_telemetry():
    fake = FakeBackends()
    fake.instant = {
        'downstream_request_duration_seconds_count{service="checkout"}': vector(
            ({"target": "payments"}, 10), ({"target": "inventory"}, 3)
        ),
    }
    result = await tools.get_service_dependencies(make_deps(fake), service="checkout")
    deps = {(d.service, d.direction): d.sources for d in result.dependencies}
    assert deps == {
        ("payments", "downstream"): ["catalog", "telemetry"],
        ("users", "downstream"): ["catalog"],
        ("inventory", "downstream"): ["telemetry"],
    }
    assert result.known_service is True


async def test_upstream_dependents():
    fake = FakeBackends()
    fake.instant = {'{target="payments"}': vector(({"service": "checkout"}, 7))}
    result = await tools.get_service_dependencies(make_deps(fake), service="payments")
    assert [(d.service, d.direction, d.sources) for d in result.dependencies] == [
        ("checkout", "upstream", ["catalog", "telemetry"])
    ]


async def test_dependencies_partial_when_one_source_fails():
    fake = FakeBackends()
    fake.down.add("prometheus.test")
    result = await tools.get_service_dependencies(make_deps(fake), service="checkout")
    assert result.status == "partial"
    assert {d.service for d in result.dependencies} == {"users", "payments"}

    both = await tools.get_service_dependencies(make_deps(fake, catalog=None), service="checkout")
    assert both.status == "unavailable"


# ---------------------------------------------------------------------------
# get_incident_events
# ---------------------------------------------------------------------------


async def test_incident_events_timeline():
    fake = FakeBackends()
    fake.alerts = [
        {"labels": {"alertname": "HighLatencyP95", "service": "checkout", "severity": "warning"},
         "state": "firing", "activeAt": "2026-11-08T11:50:00Z", "value": "2.1",
         "annotations": {"summary": "checkout p95 latency is 2.1s"}},
        {"labels": {"alertname": "HighLatencyP95", "service": "users"}, "state": "firing",
         "activeAt": "2026-11-08T11:55:00Z"},
    ]  # fmt: skip
    fake.incidents = [
        {"id": "i1", "title": "Checkout slow", "severity": "SEV2", "status": "open",
         "service_name": "checkout", "created_at": "2026-11-08T11:52:00Z"},
        {"id": "i0", "title": "Old", "severity": "SEV3", "status": "closed",
         "service_name": "checkout", "created_at": "2026-11-01T00:00:00Z"},
        {"id": "i2", "title": "Other", "severity": "SEV3", "status": "open",
         "service_name": "payments", "created_at": "2026-11-08T11:59:00Z"},
    ]  # fmt: skip
    fake.range_result = [
        version_series("1.8.2", 840, 0, step=60),
        version_series("1.8.1", 3600, 900, step=60),
    ]

    result = await tools.get_incident_events(make_deps(fake), service="checkout", minutes=30)

    assert result.status == "ok"
    assert [(e.kind, e.summary) for e in result.events] == [
        ("incident", "SEV2 Checkout slow"),
        ("alert", "HighLatencyP95 (firing)"),
        ("deployment", "version 1.8.2 first observed"),
    ]


async def test_incident_events_report_failed_sources():
    fake = FakeBackends()
    fake.down.add("api.test")
    result = await tools.get_incident_events(make_deps(fake), service="checkout")
    assert result.status == "partial"
    assert [e.error for e in result.errors] == ["incidents_unavailable"]


# ---------------------------------------------------------------------------
# Instrumentation, catalog, security
# ---------------------------------------------------------------------------


async def test_tool_calls_are_counted_and_timed():
    def calls(outcome: str) -> float:
        labels = {"tool": "get_recent_logs", "outcome": outcome}
        return REGISTRY.get_sample_value("opspilot_mcp_tool_calls_total", labels) or 0.0

    ok_before, invalid_before = calls("ok"), calls("invalid")
    await tools.get_recent_logs(make_deps(FakeBackends()), service="checkout")
    with pytest.raises(ValueError):
        await tools.get_recent_logs(make_deps(FakeBackends()), service="BAD")
    assert calls("ok") == ok_before + 1
    assert calls("invalid") == invalid_before + 1
    count = REGISTRY.get_sample_value(
        "opspilot_mcp_tool_duration_seconds_count", {"tool": "get_recent_logs"}
    )
    assert count and count >= 2


async def test_tools_only_issue_get_requests_to_configured_hosts():
    fake = FakeBackends()
    healthy_checkout(fake)
    deps = make_deps(fake)
    await tools.get_service_health(deps, service="checkout")
    await tools.get_recent_logs(deps, service="checkout")
    await tools.get_incident_events(deps, service="checkout")
    assert {r.method for r in fake.requests} == {"GET"}
    assert {r.url.host for r in fake.requests} <= {"prometheus.test", "loki.test", "api.test"}


@pytest.mark.parametrize(
    ("text", "match"),
    [
        ("services: [a, b]", "mapping"),
        ("services:\n  Bad Name: {}", "invalid service name"),
        ("services:\n  a: {depends_on: ['x; rm']}", "invalid service name"),
        ("services: [unclosed", "not valid YAML"),
    ],
)
def test_catalog_validation(text, match):
    with pytest.raises(CatalogError, match=match):
        ServiceCatalog.from_yaml(text)


def test_shipped_catalog_is_valid():
    from pathlib import Path

    path = Path(__file__).resolve().parents[2] / "observability/catalog/services.yml"
    catalog = ServiceCatalog.load(path)
    assert catalog.get("checkout").depends_on == ("users", "payments")
    assert catalog.dependents_of("payments") == ["checkout"]
