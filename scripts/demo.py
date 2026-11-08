"""Repeatable flagship demo: inject -> traffic -> telemetry -> investigate -> diagnosis.

Drives the same public API the web UI uses, so a passing run means the UI demo
path works too. Three steps:

    python scripts/demo.py prepare   # healthy + baseline traffic (~2-3 min, do it beforehand)
    python scripts/demo.py run       # the 30-60 s path: inject, traffic, ask, diagnose
    python scripts/demo.py reset     # back to healthy

`run` exits non-zero when any stage fails or the diagnosis is not the expected
one, and prints how long each stage took. Needs ENABLE_INCIDENT_LAB=true on the
API and ENABLE_FAILURE_INJECTION=true on the demo workloads.
"""

from __future__ import annotations

import argparse
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx

SERVICE = "checkout"
# What each injected failure should be diagnosed as, and the question to ask.
SCENARIOS: dict[str, dict[str, Any]] = {
    "latency": {
        "question": "Why is checkout latency high?",
        "expected": "application_latency",
        "series": "p95_latency_s",
        "threshold": 1.0,  # seconds; injected delay is 2 s
    },
    "db": {
        "question": "Checkout is slow, why?",
        "expected": "database_degradation",
        "series": "p95_latency_s",
        "threshold": 0.8,
    },
    "errors": {
        "question": "Why is checkout returning errors?",
        "expected": "application_errors",
        "series": "error_rate",
        "threshold": 0.1,  # 5xx ratio; injected rate is 50 %
    },
}
HEALTHY_P95_S = 0.5
HEALTHY_ERROR_RATIO = 0.02
FRESH_SECONDS = 90  # how recent a metric point must be to describe "now"
GET_RETRIES = 3


def _parse_ts(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


class DemoError(RuntimeError):
    pass


@dataclass
class Stage:
    name: str
    seconds: float
    detail: str


@dataclass
class DemoResult:
    ok: bool
    stages: list[Stage] = field(default_factory=list)
    investigation: dict[str, Any] | None = None

    @property
    def presented_seconds(self) -> float:
        """The part an audience watches: from injection to diagnosis."""
        setup = {"preflight", "reset", "baseline"}
        return sum(s.seconds for s in self.stages if s.name not in setup)


class Demo:
    def __init__(self, api_url: str, ui_url: str, out: Callable[[str], None] = print) -> None:
        self.http = httpx.Client(base_url=api_url.rstrip("/"), timeout=60.0)
        self.ui_url = ui_url.rstrip("/")
        self.out = out
        self.injected_at = datetime.now(UTC)

    # -- API helpers ---------------------------------------------------------

    def _get(self, path: str, **params: Any) -> dict[str, Any]:
        # Reads are idempotent: retry transient transport errors (a busy laptop
        # occasionally drops a connection) instead of failing the whole demo.
        for attempt in range(GET_RETRIES):
            try:
                response = self.http.get(path, params=params)
                response.raise_for_status()
                return response.json()
            except httpx.TransportError:
                if attempt == GET_RETRIES - 1:
                    raise
                time.sleep(2**attempt)
        raise AssertionError("unreachable")

    def _post(self, path: str, body: dict[str, Any], timeout: float = 60.0) -> dict[str, Any]:
        response = self.http.post(path, json=body, timeout=timeout)
        if response.status_code >= 400:
            raise DemoError(f"POST {path} -> {response.status_code}: {response.text[:300]}")
        return response.json()

    def recent(self, series: str, since: datetime | None = None) -> list[float]:
        """Values of a series newer than `since` (default: the last FRESH_SECONDS).

        Points from an earlier incident (or from before traffic stopped) must never
        count as the current state, or a stale spike would look like the injection.
        """
        data = self._get("/api/metrics", service=SERVICE, range="15m")
        if data["status"] == "unavailable":
            raise DemoError(f"metrics unavailable: {data['errors']}")
        cutoff = since or datetime.now(UTC) - timedelta(seconds=FRESH_SECONDS)
        return [
            p["value"]
            for p in data["series"].get(series, [])
            if p["value"] is not None and _parse_ts(p["timestamp"]) >= cutoff
        ]

    def wait_for(self, what: str, check: Callable[[], bool], timeout: float, every: float = 5.0):
        deadline = time.monotonic() + timeout
        while True:
            if check():
                return
            if time.monotonic() > deadline:
                raise DemoError(f"timed out after {timeout:.0f}s waiting for {what}")
            time.sleep(every)

    # -- steps ---------------------------------------------------------------

    def preflight(self) -> str:
        health = self._get("/api/health")
        if health["status"] == "down":
            raise DemoError(f"API dependencies down: {health['checks']}")
        lab = self._get("/api/lab")
        if not lab["enabled"]:
            raise DemoError("incident lab disabled: set ENABLE_INCIDENT_LAB=true on the API")
        target = next((s for s in lab["services"] if s["name"] == SERVICE), None)
        if not target or not target["reachable"]:
            raise DemoError(f"{SERVICE} is not reachable from the API")
        return f"API {health['status']}, lab enabled, {SERVICE} mode={target['mode']}"

    def reset(self) -> str:
        lab = self._get("/api/lab")
        changed = []
        for service in lab["services"]:
            if service["reachable"] and service["mode"] not in (None, "none"):
                self._post("/api/lab/failure", {"service": service["name"], "mode": "none"})
                changed.append(service["name"])
        return f"reset {', '.join(changed)}" if changed else "already healthy"

    def prepare(self, batch: int = 40, timeout: float = 300.0) -> None:
        """Healthy services plus steady normal traffic until p95 has settled.

        Traffic keeps flowing while waiting: the 1-minute p95 only forgets the last
        incident's slow requests if new requests keep arriving.
        """
        self.out(self.preflight())
        self.out(self.reset())
        self.out("sending baseline traffic until checkout p95 is healthy")

        def ready() -> bool:
            if self.at_baseline():
                return True
            self._post("/api/lab/traffic", {"requests": batch})
            return False

        self.wait_for("a healthy p95 baseline", ready, timeout, every=15)
        self.out("baseline ready: checkout p95 has been normal for the last minute")

    def at_baseline(self) -> bool:
        """Recent traffic exists and every recent latency and error point is healthy.

        Errors matter too: a failing dependency (say, payments in errors mode from
        the Incident Lab) would otherwise be diagnosed instead of the injection.
        """
        latency = self.recent("p95_latency_s")
        errors = self.recent("error_rate")
        return (
            len(latency) >= 3
            and max(latency) < HEALTHY_P95_S
            and max(errors, default=0.0) < HEALTHY_ERROR_RATIO
        )

    def check_baseline(self) -> str:
        # Right after a run the previous incident's points are still recent; injecting
        # now would make that old spike look like the new one.
        if not self.at_baseline():
            raise DemoError(
                f"{SERVICE} is not at a healthy, recent baseline (latency or errors elevated); "
                "run `python scripts/demo.py prepare` first"
            )
        return (
            f"{SERVICE} healthy for the last minute (p95 < {HEALTHY_P95_S * 1000:.0f} ms, no 5xx)"
        )

    def run(self, mode: str = "latency", traffic: int = 60, keep: bool = False) -> DemoResult:
        scenario = SCENARIOS[mode]
        result = DemoResult(ok=False)

        def stage(name: str, fn: Callable[[], str]) -> None:
            started = time.monotonic()
            detail = fn()
            result.stages.append(Stage(name, time.monotonic() - started, detail))
            self.out(f"  {name:<12} {result.stages[-1].seconds:6.1f}s  {detail}")

        try:
            stage("preflight", self.preflight)
            stage("reset", self.reset)
            stage("baseline", self.check_baseline)
            stage("inject", lambda: self._inject(mode))
            stage("traffic", lambda: self._traffic(traffic))
            stage("telemetry", lambda: self._wait_capture(scenario))
            stage("investigate", lambda: self._investigate(scenario, result))
            stage("verify", lambda: self._verify(scenario, result))
            result.ok = True
        except (DemoError, httpx.HTTPError) as exc:
            self.out(f"  FAILED: {exc}")
        finally:
            if not keep:
                try:
                    self.reset()
                except (DemoError, httpx.HTTPError) as exc:
                    self.out(f"  reset failed: {exc}")
        return result

    def _inject(self, mode: str) -> str:
        self.injected_at = datetime.now(UTC)
        self._post("/api/lab/failure", {"service": SERVICE, "mode": mode})
        state = next(s for s in self._get("/api/lab")["services"] if s["name"] == SERVICE)
        if state["mode"] != mode:  # confirm with the service itself, not the request
            raise DemoError(f"{SERVICE} reports mode={state['mode']}, expected {mode}")
        return f"{SERVICE} failure mode = {mode} (confirmed by the service)"

    def _traffic(self, requests: int) -> str:
        accepted = self._post("/api/lab/traffic", {"requests": requests})
        return f"{accepted['requests']} requests to {accepted['target']} (in the background)"

    def _wait_capture(self, scenario: dict[str, Any]) -> str:
        series, threshold = scenario["series"], scenario["threshold"]
        seen: list[float] = []

        def captured() -> bool:
            # Only points measured after the injection can show it.
            values = self.recent(series, since=self.injected_at)
            seen[:] = values[-1:]
            return bool(values) and values[-1] >= threshold

        self.wait_for(f"{series} >= {threshold}", captured, timeout=180)
        return f"Prometheus shows {series} = {seen[0]:.3g} (threshold {threshold})"

    def _investigate(self, scenario: dict[str, Any], result: DemoResult) -> str:
        detail = self._post(
            "/api/investigations", {"query": scenario["question"], "wait": True}, timeout=240
        )
        result.investigation = detail
        return f'asked "{scenario["question"]}" -> {detail["status"]} in {detail["latency_ms"]} ms'

    def _verify(self, scenario: dict[str, Any], result: DemoResult) -> str:
        detail = result.investigation or {}
        report = detail.get("report") or {}
        if detail.get("status") != "completed":
            raise DemoError(f"investigation {detail.get('status')}: {detail.get('summary')}")
        if detail.get("root_cause") != scenario["expected"]:
            raise DemoError(
                f"diagnosed {detail.get('root_cause')!r}, expected {scenario['expected']!r}: "
                f"{report.get('conclusion')}"
            )
        if not report.get("observations") or not report.get("recommendations"):
            raise DemoError("report has no facts or no recommendation")
        return f"{detail['root_cause']} at {detail['confidence']:.0%} estimated confidence"

    def summary(self, result: DemoResult) -> None:
        detail = result.investigation or {}
        report = detail.get("report") or {}
        self.out("")
        if report:
            self.out(f"Diagnosis:  {report.get('conclusion')}")
            for obs in report.get("observations", [])[:5]:
                self.out(f"  fact      {obs['statement']}")
            for ev in report.get("evidence", [])[:2]:
                self.out(f"  evidence  {ev['citation']} (score {ev['score']:.2f})")
            for rec in report.get("recommendations", [])[:2]:
                self.out(f"  recommend {rec['action']}")
            self.out(f"Open in the UI: {self.ui_url}/investigations/{detail['id']}")
        verdict = "PASSED" if result.ok else "FAILED"
        self.out(f"\nDemo {verdict}: injection to diagnosis took {result.presented_seconds:.0f}s")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("command", choices=["prepare", "run", "reset"])
    parser.add_argument("--api-url", default="http://127.0.0.1:8000")
    parser.add_argument("--ui-url", default="http://localhost:3001")
    parser.add_argument("--mode", choices=sorted(SCENARIOS), default="latency")
    parser.add_argument("--traffic", type=int, default=60, help="requests to send (1-300)")
    parser.add_argument("--keep", action="store_true", help="leave the failure injected")
    args = parser.parse_args(argv)

    demo = Demo(args.api_url, args.ui_url)
    try:
        if args.command == "prepare":
            demo.prepare()
            return 0
        if args.command == "reset":
            demo.out(demo.reset())
            return 0
        demo.out(f"Demo: inject {args.mode} into {SERVICE}, then ask OpsPilot why")
        result = demo.run(args.mode, args.traffic, args.keep)
        demo.summary(result)
        return 0 if result.ok else 1
    except (DemoError, httpx.HTTPError) as exc:
        demo.out(f"error: {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
