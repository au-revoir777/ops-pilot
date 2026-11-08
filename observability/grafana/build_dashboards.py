"""Generate the provisioned Grafana dashboard JSON (dashboards as code).

    python observability/grafana/build_dashboards.py

The JSON in ./dashboards is committed; a unit test fails if it drifts from
what this script produces. Edit the panels here, not in the Grafana UI.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

OUTPUT = Path(__file__).parent / "dashboards" / "opspilot-services.json"
PROM = {"type": "prometheus", "uid": "prometheus"}
LOKI = {"type": "loki", "uid": "loki"}
SERVICE = 'service=~"$service"'


def target(expr: str, legend: str, ref: str = "A", datasource: dict = PROM) -> dict[str, Any]:
    return {"datasource": datasource, "expr": expr, "legendFormat": legend, "refId": ref}


def timeseries(
    title: str, targets: list[dict], unit: str, grid: tuple[int, int, int, int], **extra: Any
) -> dict[str, Any]:
    x, y, w, h = grid
    return {
        "type": "timeseries",
        "title": title,
        "datasource": PROM,
        "gridPos": {"x": x, "y": y, "w": w, "h": h},
        "fieldConfig": {
            "defaults": {"unit": unit, "custom": {"lineWidth": 2, "fillOpacity": 8}},
            "overrides": [],
        },
        "options": {"legend": {"displayMode": "list", "placement": "bottom"}},
        "targets": targets,
        **extra,
    }


def row(title: str, y: int) -> dict[str, Any]:
    return {
        "type": "row",
        "title": title,
        "collapsed": False,
        "gridPos": {"x": 0, "y": y, "w": 24, "h": 1},
    }


def build() -> dict[str, Any]:
    panels: list[dict[str, Any]] = [
        row("Service health", 0),
        {
            "type": "stat",
            "title": "Scrape targets up",
            "description": "1 = Prometheus can scrape the target's /metrics.",
            "datasource": PROM,
            "gridPos": {"x": 0, "y": 1, "w": 14, "h": 4},
            "targets": [target('up{job=~"opspilot-api|services"}', "{{project}} {{instance}}")],
            "fieldConfig": {
                "defaults": {
                    "mappings": [
                        {"type": "value", "options": {"0": {"text": "DOWN", "color": "red"}}},
                        {"type": "value", "options": {"1": {"text": "UP", "color": "green"}}},
                    ],
                    "color": {"mode": "fixed", "fixedColor": "green"},
                },
                "overrides": [],
            },
            "options": {
                "colorMode": "background",
                "graphMode": "none",
                "textMode": "value_and_name",
            },
        },
        {
            "type": "table",
            "title": "Deployed versions",
            "description": "From app_info; correlate version changes with incidents.",
            "datasource": PROM,
            "gridPos": {"x": 14, "y": 1, "w": 10, "h": 4},
            "targets": [
                {**target(f"app_info{{{SERVICE}}}", "", "A"), "format": "table", "instant": True}
            ],
            "transformations": [
                {
                    "id": "organize",
                    "options": {
                        "excludeByName": {
                            "Time": True,
                            "Value": True,
                            "__name__": True,
                            "job": True,
                        },
                        "renameByName": {"instance": "target"},
                    },
                }
            ],
        },
        row("Traffic, errors, latency (RED)", 5),
        timeseries(
            "Request rate",
            [target(f"service:http_requests:rate1m{{{SERVICE}}}", "{{service}}")],
            "reqps",
            (0, 6, 8, 8),
        ),
        timeseries(
            "Error rate (5xx)",
            [target(f"service:http_errors:ratio_rate1m{{{SERVICE}}}", "{{service}}")],
            "percentunit",
            (8, 6, 8, 8),
        ),
        timeseries(
            "Requests in progress",
            [target(f"sum by (service) (http_requests_in_progress{{{SERVICE}}})", "{{service}}")],
            "short",
            (16, 6, 8, 8),
        ),
        timeseries(
            "Latency p50 / p95 / p99",
            [
                target(f"service:http_latency_seconds:p50_1m{{{SERVICE}}}", "p50 {{service}}", "A"),
                target(f"service:http_latency_seconds:p95_1m{{{SERVICE}}}", "p95 {{service}}", "B"),
                target(f"service:http_latency_seconds:p99_1m{{{SERVICE}}}", "p99 {{service}}", "C"),
            ],
            "s",
            (0, 14, 12, 9),
        ),
        timeseries(
            "Latency p95 by route",
            [
                target(
                    "histogram_quantile(0.95, sum by (service, route, le) "
                    f"(rate(http_request_duration_seconds_bucket{{{SERVICE}}}[1m])))",
                    "{{service}} {{route}}",
                )
            ],
            "s",
            (12, 14, 12, 9),
        ),
        row("Dependencies", 23),
        timeseries(
            "Database query p95",
            [
                target(
                    f"service_operation:db_query_seconds:p95_1m{{{SERVICE}}}",
                    "{{service}} {{operation}}",
                )
            ],
            "s",
            (0, 24, 12, 8),
        ),
        timeseries(
            "Downstream calls by outcome",
            [
                target(
                    "sum by (service, target, outcome) "
                    f"(rate(downstream_request_duration_seconds_count{{{SERVICE}}}[1m]))",
                    "{{service}} → {{target}} ({{outcome}})",
                )
            ],
            "reqps",
            (12, 24, 12, 8),
        ),
        row("Logs", 32),
        {
            "type": "logs",
            "title": "Logs (warnings and errors)",
            "datasource": LOKI,
            "gridPos": {"x": 0, "y": 33, "w": 24, "h": 10},
            "targets": [
                {"datasource": LOKI, "refId": "A", "expr": f'{{{SERVICE}, level=~"warning|error"}}'}
            ],
            "options": {"showTime": True, "wrapLogMessage": True, "sortOrder": "Descending"},
        },
        row("OpsPilot investigations and agent", 43),
        timeseries(
            "Investigations",
            [
                target("sum(rate(opspilot_investigations_created_total[5m]))", "opened", "A"),
                target(
                    "sum by (outcome) (rate(opspilot_investigations_finished_total[5m]))",
                    "{{outcome}}",
                    "B",
                ),
            ],
            "reqps",
            (0, 44, 8, 8),
        ),
        timeseries(
            "MCP tool calls (Phase 5+)",
            [
                target(
                    "sum by (tool, outcome) (rate(opspilot_tool_calls_total[5m]))",
                    "{{tool}} {{outcome}}",
                )
            ],
            "reqps",
            (8, 44, 8, 8),
        ),
        timeseries(
            "Agent / RAG latency p95 (Phase 4+)",
            [
                target(
                    "histogram_quantile(0.95, sum by (le) "
                    "(rate(opspilot_agent_execution_duration_seconds_bucket[5m])))",
                    "agent",
                    "A",
                ),
                target(
                    "histogram_quantile(0.95, sum by (le) "
                    "(rate(opspilot_rag_retrieval_duration_seconds_bucket[5m])))",
                    "rag",
                    "B",
                ),
            ],
            "s",
            (16, 44, 8, 8),
        ),
    ]
    for panel_id, panel in enumerate(panels, start=1):
        panel["id"] = panel_id

    return {
        "uid": "opspilot-services",
        "title": "OpsPilot — Services",
        "tags": ["opspilot"],
        "timezone": "browser",
        "schemaVersion": 39,
        "version": 1,
        "editable": False,
        "refresh": "10s",
        "time": {"from": "now-30m", "to": "now"},
        "templating": {
            "list": [
                {
                    "name": "service",
                    "label": "Service",
                    "type": "query",
                    "datasource": PROM,
                    "query": {
                        "query": "label_values(http_requests_total, service)",
                        "refId": "service",
                    },
                    "definition": "label_values(http_requests_total, service)",
                    "includeAll": True,
                    "multi": True,
                    "allValue": ".*",
                    "current": {"text": "All", "value": "$__all"},
                    "refresh": 2,
                }
            ]
        },
        "annotations": {"list": []},
        "panels": panels,
    }


def render() -> str:
    return json.dumps(build(), indent=2, ensure_ascii=False) + "\n"


if __name__ == "__main__":
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(render(), encoding="utf-8")
    print(f"wrote {OUTPUT}")  # noqa: T201
