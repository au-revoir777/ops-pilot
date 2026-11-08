"""Turn MCP tool results into observations (facts with sources and signal tags).

Pure functions. A tool result that is ``unavailable`` produces no facts, only a
missing-evidence note: nothing is inferred from absent data.

Signal tags used by the reasoning rules:
  symptom_latency, symptom_errors      the reported problem is confirmed
  latency_step                         p95 history shows a step change (with start time)
  db_latency_rise                      DB query p95 rose during the window
  db_slow_logs                         slow_query_detected warnings present
  deploy_recent                        a version first appeared in the window
  dependency_degraded                  a dependency's health is degraded/down
  dependency_errors                    dependency_error / timeout / unreachable logs
  internal_errors                      request_processing_failed logs (no dependency cause)
  alert_firing                         an alert is firing or pending for the service
  dependencies_healthy                 every dependency with data is healthy
  db_latency_flat                      DB query p95 data exists and did not rise
"""

from __future__ import annotations

import statistics
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from app.agents.models import Observation

LATENCY_STEP_FACTOR = 2.0
LATENCY_STEP_MIN_S = 0.5
DB_RISE_FACTOR = 3.0
DB_RISE_MIN_S = 0.3
LOG_EVENT_MIN = 3
# Evidence is counted from this long before the symptom onset (1-minute telemetry resolution).
SYMPTOM_LOOKBACK = timedelta(minutes=3)


def parse_ts(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


@dataclass
class Facts:
    """Accumulates observations with sequential ids (F1, F2, ...)."""

    observations: list[Observation] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)

    def add(
        self,
        kind: str,
        statement: str,
        source: str,
        *,
        signals: list[str] | None = None,
        at: datetime | None = None,
        **data: Any,
    ) -> Observation:
        obs = Observation(
            id=f"F{len(self.observations) + 1}",
            kind=kind,
            statement=statement,
            source=source,
            at=at,
            signals=signals or [],
            data=data,
        )
        # The same fact can arrive twice (e.g. a wider follow-up query); keep one.
        for existing in self.observations:
            if (
                existing.kind == obs.kind
                and existing.statement.split(" at ")[0] == obs.statement.split(" at ")[0]
            ):
                return existing
        self.observations.append(obs)
        return obs

    def note_missing(self, tool: str, result: dict[str, Any]) -> bool:
        """Record unavailable sources. Returns True when the result has no usable data."""
        for error in result.get("errors", []):
            self.missing.append(f"{tool}: {error.get('error')} ({error.get('detail', '')})".strip())
        return result.get("status") in {"unavailable", "error"}


def step_change(points: list[dict[str, Any]], factor: float, floor: float) -> dict[str, Any] | None:
    """Detect a sustained step at the end of a series.

    The step is the final run of points at or above ``max(factor * baseline, floor)``,
    where baseline is the median of the points just before that run. Looking at the
    *last* run means an earlier, already-recovered incident in the same window
    neither hides the current one nor shifts its start time.
    """
    values = [(parse_ts(p["timestamp"]), p["value"]) for p in points if p.get("value") is not None]
    if len(values) < 4:
        return None
    # Walk back from the end while values stay elevated relative to the floor.
    end = len(values) - 1
    if values[end][1] < floor:
        return None
    start = end
    while start > 0 and values[start - 1][1] >= floor:
        start -= 1
    before = [v for _, v in values[max(0, start - 6) : start]]
    if not before:
        return None  # elevated for the whole window: no baseline to compare against
    baseline = statistics.median(before)
    threshold = max(baseline * factor, floor)
    run = values[start:]
    if run[-1][1] < threshold:
        return None
    first = next(i for i, (_, v) in enumerate(run) if v >= threshold)
    return {"baseline": baseline, "current": run[-1][1], "start": run[first][0]}


def _series(result: dict[str, Any]) -> list[dict[str, Any]]:
    series = result.get("series") or []
    return series[0]["points"] if series else []


def extract_health(
    facts: Facts, service: str, result: dict[str, Any], thresholds: dict[str, float]
) -> None:
    if facts.note_missing("get_service_health", result):
        return
    p95, err = result.get("p95_latency_ms"), result.get("error_rate")
    signals = []
    if p95 is not None and p95 > thresholds["p95_ms"]:
        signals.append("symptom_latency")
    if err is not None and err > thresholds["error_ratio"]:
        signals.append("symptom_errors")
    facts.add(
        "health",
        f"{service} health is {result.get('health')}: p95 "
        f"{_fmt_ms(p95)}, 5xx ratio {_fmt_pct(err)}, version {result.get('version') or 'unknown'}",
        "get_service_health",
        signals=signals,
        health=result.get("health"),
        p95_latency_ms=p95,
        error_rate=err,
        version=result.get("version"),
        reasons=result.get("reasons", []),
    )
    deps = result.get("dependency_status") or []
    with_data = [d for d in deps if d.get("status") != "unknown"]
    for dep in deps:
        if dep.get("status") in {"degraded", "down"}:
            facts.add(
                "dependency",
                f"dependency {dep['service']} is {dep['status']} "
                f"(p95 {_fmt_ms(dep.get('p95_latency_ms'))}, "
                f"5xx {_fmt_pct(dep.get('error_rate'))})",
                "get_service_health",
                signals=["dependency_degraded"],
                dependency=dep["service"],
            )
    if with_data and all(d.get("status") == "healthy" for d in with_data):
        names = ", ".join(sorted(d["service"] for d in with_data))
        facts.add(
            "dependency",
            f"all dependencies with data are healthy ({names})",
            "get_service_health",
            signals=["dependencies_healthy"],
            dependencies=[d["service"] for d in with_data],
        )


def extract_dependency_health(facts: Facts, dependency: str, result: dict[str, Any]) -> None:
    """Follow-up health check of a dependency: evidence about the dependency only."""
    if facts.note_missing("get_service_health", result):
        return
    health = result.get("health")
    facts.add(
        "dependency",
        f"dependency {dependency} health is {health}: p95 {_fmt_ms(result.get('p95_latency_ms'))}, "
        f"5xx ratio {_fmt_pct(result.get('error_rate'))}",
        "get_service_health",
        signals=["dependency_degraded"] if health in {"degraded", "down"} else [],
        dependency=dependency,
        health=health,
    )


def extract_latency_history(facts: Facts, service: str, result: dict[str, Any]) -> None:
    if facts.note_missing("query_metrics", result):
        return
    step = step_change(_series(result), LATENCY_STEP_FACTOR, LATENCY_STEP_MIN_S)
    if step:
        facts.add(
            "metric",
            f"{service} p95 latency rose from {_fmt_ms(step['baseline'] * 1000)} to "
            f"{_fmt_ms(step['current'] * 1000)}, starting at {_fmt_time(step['start'])}",
            "query_metrics",
            signals=["latency_step", "symptom_latency"],
            at=step["start"],
            baseline_s=step["baseline"],
            current_s=step["current"],
        )


def extract_db_history(
    facts: Facts, service: str, result: dict[str, Any], since: datetime | None = None
) -> None:
    """``since`` = shortly before the symptom onset, when known.

    An earlier, recovered database incident in the same window must not decide
    the current one: when the database has been fast since the symptom began,
    that is reported as flat even if it was slow an hour ago.
    """
    if facts.note_missing("query_metrics", result):
        return
    points = _series(result)
    if not points:
        return
    step = step_change(points, DB_RISE_FACTOR, DB_RISE_MIN_S)
    if step:
        facts.add(
            "metric",
            f"{service} database query p95 rose from {_fmt_ms(step['baseline'] * 1000)} to "
            f"{_fmt_ms(step['current'] * 1000)}, starting at {_fmt_time(step['start'])}",
            "query_metrics",
            signals=["db_latency_rise"],
            at=step["start"],
            baseline_s=step["baseline"],
            current_s=step["current"],
        )
        return
    values = [p["value"] for p in points if p.get("value") is not None]
    if not values:
        return
    if since is not None:
        recent = [
            p["value"]
            for p in points
            if p.get("value") is not None and (ts := parse_ts(p["timestamp"])) and ts >= since
        ]
        if recent and max(recent) < DB_RISE_MIN_S:
            facts.add(
                "metric",
                f"{service} database query p95 stayed below {_fmt_ms(DB_RISE_MIN_S * 1000)} "
                f"since the symptom began ({_fmt_time(since)}), now {_fmt_ms(recent[-1] * 1000)}",
                "query_metrics",
                signals=["db_latency_flat"],
                current_s=recent[-1],
            )
            return
    if min(values) >= DB_RISE_MIN_S:
        # High for the whole window: no baseline to compare, but clearly slow.
        facts.add(
            "metric",
            f"{service} database query p95 was elevated for the whole window "
            f"(at least {_fmt_ms(min(values) * 1000)}, now {_fmt_ms(values[-1] * 1000)})",
            "query_metrics",
            signals=["db_latency_rise"],
            current_s=values[-1],
        )
    elif max(values) < DB_RISE_MIN_S:
        # Only "flat" when it never got slow; a recovered spike is neither.
        facts.add(
            "metric",
            f"{service} database query p95 stayed below {_fmt_ms(DB_RISE_MIN_S * 1000)} "
            "during the window",
            "query_metrics",
            signals=["db_latency_flat"],
        )


def extract_error_history(facts: Facts, service: str, result: dict[str, Any]) -> None:
    if facts.note_missing("query_metrics", result):
        return
    step = step_change(_series(result), 3.0, 0.02)
    if step:
        facts.add(
            "metric",
            f"{service} 5xx ratio rose from {_fmt_pct(step['baseline'])} to "
            f"{_fmt_pct(step['current'])}, starting at {_fmt_time(step['start'])}",
            "query_metrics",
            signals=["symptom_errors", "error_step"],
            at=step["start"],
        )


def extract_logs(
    facts: Facts, service: str, result: dict[str, Any], since: datetime | None = None
) -> None:
    """``since`` = shortly before the symptom onset, when known.

    Log lines from an earlier incident in the lookback window describe that
    incident, not this one, so they are left out of the counts.
    """
    if facts.note_missing("get_recent_logs", result):
        return
    entries = result.get("entries") or []
    if since is not None:
        entries = [
            e for e in entries if (ts := parse_ts(e.get("timestamp"))) is None or ts >= since
        ]
    counts = Counter(e.get("message") for e in entries)
    slow_ops = Counter(
        e.get("metadata", {}).get("operation")
        for e in entries
        if e.get("message") == "slow_query_detected"
    )
    if counts["slow_query_detected"] >= LOG_EVENT_MIN:
        times = [
            e.get("metadata", {}).get("query_time_ms")
            for e in entries
            if e.get("message") == "slow_query_detected"
        ]
        times = [t for t in times if isinstance(t, (int, float))]
        ops = ", ".join(f"{op} ({n})" for op, n in slow_ops.most_common() if op)
        typical = f", typical {statistics.median(times):.0f} ms" if times else ""
        facts.add(
            "log",
            f"{counts['slow_query_detected']} slow_query_detected warnings in {service} logs "
            f"({ops}{typical})",
            "get_recent_logs",
            signals=["db_slow_logs"],
            count=counts["slow_query_detected"],
            operations=dict(slow_ops),
            sample_request_ids=_sample_ids(entries, "slow_query_detected"),
        )
    if counts["request_slow"] >= LOG_EVENT_MIN:
        facts.add(
            "log",
            f"{counts['request_slow']} request_slow warnings (requests over 1 s) in {service} logs"
            + ("" if counts["slow_query_detected"] >= LOG_EVENT_MIN else ", with no slow queries"),
            "get_recent_logs",
            # Slow requests without slow queries point at the service's own code path.
            signals=["symptom_latency"]
            + ([] if counts["slow_query_detected"] >= LOG_EVENT_MIN else ["app_slow_logs"]),
            count=counts["request_slow"],
        )
    dep_events = (
        counts["dependency_error"] + counts["dependency_timeout"] + counts["dependency_unreachable"]
    )
    if dep_events >= LOG_EVENT_MIN:
        targets = Counter(
            e.get("metadata", {}).get("target")
            for e in entries
            if e.get("message")
            in {"dependency_error", "dependency_timeout", "dependency_unreachable"}
        )
        names = ", ".join(f"{t} ({n})" for t, n in targets.most_common() if t)
        facts.add(
            "log",
            f"{dep_events} dependency failure logs in {service} ({names})",
            "get_recent_logs",
            signals=["dependency_errors"],
            targets=dict(targets),
        )
    if counts["request_processing_failed"] >= LOG_EVENT_MIN:
        facts.add(
            "log",
            f"{counts['request_processing_failed']} request_processing_failed errors "
            f"in {service} logs",
            "get_recent_logs",
            signals=["internal_errors", "symptom_errors"],
            count=counts["request_processing_failed"],
        )


def extract_deployments(
    facts: Facts, service: str, result: dict[str, Any], window_start: datetime
) -> None:
    if facts.note_missing("get_recent_deployments", result):
        return
    deployments = sorted(
        (d for d in result.get("deployments") or [] if parse_ts(d.get("deployment_time"))),
        key=lambda d: parse_ts(d["deployment_time"]),
    )
    for index, d in enumerate(deployments):
        when = parse_ts(d["deployment_time"])
        if d.get("deployed_before_window") or when < window_start:
            continue
        previous = deployments[index - 1]["version"] if index > 0 else None
        facts.add(
            "deployment",
            f"{service} version {d['version']} was first observed at {_fmt_time(when)}"
            + (f" (replacing {previous})" if previous else ""),
            "get_recent_deployments",
            signals=["deploy_recent"],
            at=when,
            version=d["version"],
            previous_version=previous,
            status=d.get("status"),
        )


def extract_events(facts: Facts, service: str, result: dict[str, Any]) -> None:
    if facts.note_missing("get_incident_events", result):
        return
    for event in result.get("events") or []:
        if event.get("kind") == "alert" and event.get("details", {}).get("state") in {
            "firing",
            "pending",
        }:
            facts.add(
                "alert",
                f"alert {event.get('summary')} for {service}: "
                f"{event.get('details', {}).get('summary') or 'no summary'}",
                "get_incident_events",
                signals=["alert_firing"],
                at=parse_ts(event.get("timestamp")),
            )


def extract_dependencies(facts: Facts, service: str, result: dict[str, Any]) -> list[str]:
    """Returns downstream dependency names (used to plan follow-up checks)."""
    if facts.note_missing("get_service_dependencies", result):
        return []
    return sorted(
        d["service"] for d in result.get("dependencies") or [] if d.get("direction") == "downstream"
    )


def _sample_ids(entries: list[dict[str, Any]], message: str, n: int = 3) -> list[str]:
    ids = [e.get("metadata", {}).get("request_id") for e in entries if e.get("message") == message]
    return [i for i in ids if i][:n]


def _fmt_ms(value: float | None) -> str:
    return "unknown" if value is None else f"{value:.0f} ms"


def _fmt_pct(value: float | None) -> str:
    return "unknown" if value is None else f"{value:.1%}"


def _fmt_time(value: datetime | None) -> str:
    return "unknown time" if value is None else value.strftime("%H:%M:%S UTC")
