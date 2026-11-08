"""Scenario simulation: replay an incident's telemetry without a live stack.

A scenario describes what each MCP tool and the knowledge base *would* return
(see app/agents/scenarios/cases.json). ScenarioToolClient answers tool calls with
MCP-shaped results built from it, so the real agent graph runs unchanged. Used
for the evaluation suite, deterministic unit tests and incident replay.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from app.agents.tools import ALLOWED_TOOLS, ToolNotAllowed
from app.db.models.knowledge import DocumentType
from app.rag.retrieval import RetrievalUnavailable, RetrievedChunk
from app.rag.safety import detect_prompt_injection

NOW = datetime(2026, 11, 8, 12, 0, tzinfo=UTC)
CASES_FILE = Path(__file__).parent / "scenarios" / "cases.json"


def load_cases() -> dict[str, Any]:
    """The scenario catalogue (evaluation, replay and tests share one file)."""
    return json.loads(CASES_FILE.read_text(encoding="utf-8"))


STEP = timedelta(minutes=1)


def _unavailable(source: str) -> dict[str, Any]:
    return {
        "status": "unavailable",
        "errors": [
            {"source": source, "error": f"{source}_unavailable", "detail": "simulated outage"}
        ],
    }


def _history(spec: dict[str, Any] | str | None, window_minutes: int, now: datetime) -> list[dict]:
    """Build a 1-minute series: flat baseline, then a step `step_minutes_ago` minutes ago."""
    if spec is None:
        return []
    if spec == "flat":
        spec = {"baseline_s": 0.04, "current_s": 0.04, "step_minutes_ago": 0}
    earlier = spec.get("earlier")  # a recovered spike: {from_minutes_ago, to_minutes_ago, value_s}
    points = []
    for minute in range(window_minutes, -1, -1):
        stepped = spec.get("step_minutes_ago", 0) and minute <= spec["step_minutes_ago"]
        value = spec["current_s"] if stepped else spec["baseline_s"]
        if earlier and earlier["to_minutes_ago"] <= minute <= earlier["from_minutes_ago"]:
            value = earlier["value_s"]
        points.append({"timestamp": (now - minute * STEP).isoformat(), "value": value})
    return points


class ScenarioToolClient:
    def __init__(self, telemetry: dict[str, Any], now: datetime = NOW) -> None:
        self.t = telemetry
        self.now = now
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def _down(self, tool: str) -> bool:
        return tool in self.t.get("unavailable", []) or (
            "prometheus" in self.t.get("unavailable", []) and tool != "get_recent_logs"
        )

    async def call(self, tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if tool not in ALLOWED_TOOLS:
            raise ToolNotAllowed(tool)
        self.calls.append((tool, arguments))
        if self._down(tool):
            return _unavailable("loki" if tool == "get_recent_logs" else "prometheus")
        return getattr(self, tool)(**arguments)

    # --- tools ---------------------------------------------------------------

    def get_service_health(self, service: str) -> dict[str, Any]:
        target = self.t.get("service")
        if service != target:
            dep = self.t.get("dependency_health", {}).get(service, {"health": "healthy"})
            return {
                "status": "ok",
                "errors": [],
                "service": service,
                "health": dep["health"],
                "p95_latency_ms": dep.get("p95_ms", 60.0),
                "error_rate": dep.get("error_rate", 0.0),
                "request_rate": 3.0,
                "version": "1.0.0",
                "targets_up": 1,
                "reasons": [],
                "dependency_status": [],
            }
        health = self.t.get("health", {})
        deps = [
            {"service": name, "status": status, "error_rate": 0.0, "p95_latency_ms": 80.0}
            for name, status in health.get("deps", {}).items()
        ]
        return {
            "status": "ok",
            "errors": [],
            "service": service,
            "health": health.get("health", "healthy"),
            "p95_latency_ms": health.get("p95_ms"),
            "error_rate": health.get("error_rate"),
            "request_rate": 4.0,
            "version": health.get("version"),
            "targets_up": 1,
            "reasons": [],
            "dependency_status": deps,
        }

    def query_metrics(
        self, query: str, start_time: str, end_time: str = "now", **_: Any
    ) -> dict[str, Any]:
        window = (
            int(start_time.removeprefix("now-").removesuffix("m"))
            if start_time.endswith("m")
            else 60
        )
        if "count by (service) (app_info)" in query:
            series = [
                {"metric": {"service": s}, "points": []} for s in self.t.get("known_services", [])
            ]
            return {"status": "ok", "errors": [], "series": series}
        key = (
            "latency_history"
            if "http_latency" in query
            else "db_history"
            if "db_query" in query
            else "error_history"
            if "http_errors" in query
            else None
        )
        points = _history(self.t.get(key) if key else None, window, self.now)
        series = [{"metric": {}, "points": points}] if points else []
        return {"status": "ok", "errors": [], "series": series}

    def get_recent_logs(
        self, service: str, minutes: int = 30, severity: str | None = None, limit: int = 100
    ) -> dict[str, Any]:
        entries = []
        for event, spec in self.t.get("logs", {}).items():
            # spec: a count of recent lines, or {"count": n, "minutes_ago": m} for older ones
            count, age = (
                (spec, 0) if isinstance(spec, int) else (spec["count"], spec["minutes_ago"])
            )
            message, _, target = event.partition(":")
            level = "warning" if message in {"slow_query_detected", "request_slow"} else "error"
            if severity == "error" and level != "error":
                continue
            for i in range(count):
                metadata: dict[str, Any] = {"request_id": f"req-{message[:4]}-{i}"}
                if message == "slow_query_detected":
                    metadata |= {
                        "operation": ("select_cart_items", "insert_order")[i % 2],
                        "query_time_ms": 900,
                    }
                if target:
                    metadata["target"] = target
                entries.append(
                    {
                        "timestamp": (
                            self.now - timedelta(minutes=age, seconds=i * 10)
                        ).isoformat(),
                        "level": level,
                        "message": message,
                        "metadata": metadata,
                    }
                )
        return {"status": "ok", "errors": [], "service": service, "entries": entries[:limit]}

    def get_recent_deployments(
        self, service: str, lookback_hours: int | None = None
    ) -> dict[str, Any]:
        deployments = []
        for d in self.t.get("deployments", []):
            when = self.now - timedelta(minutes=d["minutes_ago"])
            if d.get("previous"):
                deployments.append(
                    {
                        "version": d["previous"],
                        "deployment_time": (
                            self.now - timedelta(hours=lookback_hours or 24)
                        ).isoformat(),
                        "last_seen": when.isoformat(),
                        "status": "superseded",
                        "deployed_before_window": True,
                    }
                )
            deployments.append(
                {
                    "version": d["version"],
                    "deployment_time": when.isoformat(),
                    "last_seen": self.now.isoformat(),
                    "status": "active",
                    "deployed_before_window": d.get("before_window", False),
                }
            )
        return {"status": "ok", "errors": [], "service": service, "deployments": deployments}

    def get_service_dependencies(self, service: str) -> dict[str, Any]:
        deps = [
            {"service": name, "direction": "downstream", "sources": ["catalog"]}
            for name in self.t.get("health", {}).get("deps", {})
        ]
        return {
            "status": "ok",
            "errors": [],
            "service": service,
            "known_service": True,
            "dependencies": deps,
        }

    def get_incident_events(self, service: str, minutes: int = 60) -> dict[str, Any]:
        events = [
            {
                "timestamp": (self.now - timedelta(minutes=5)).isoformat(),
                "kind": "alert",
                "summary": f"{name} (firing)",
                "details": {"state": "firing", "summary": f"{service} {name}"},
            }
            for name in self.t.get("alerts", [])
        ]
        return {"status": "ok", "errors": [], "service": service, "events": events}


class ScenarioRetriever:
    def __init__(self, knowledge: list[dict[str, Any]] | str | None) -> None:
        self.knowledge = knowledge

    async def retrieve(self, query: str, services: list[str] | None) -> list[RetrievedChunk]:
        if self.knowledge == "unavailable":
            raise RetrievalUnavailable("simulated knowledge base outage")
        chunks = []
        for i, item in enumerate(self.knowledge or []):
            chunks.append(
                RetrievedChunk(
                    document_id=uuid.uuid5(uuid.NAMESPACE_URL, item["source"]),
                    source=item["source"],
                    title=item.get("title", item["source"]),
                    doc_type=DocumentType(item.get("doc_type", "runbook")),
                    services=item.get("services", []),
                    section=item.get("section"),
                    chunk_index=i,
                    content=item["content"],
                    score=item.get("score", 0.75),
                    flags=detect_prompt_injection(item["content"]),
                )
            )
        return chunks
