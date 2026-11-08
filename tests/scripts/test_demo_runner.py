"""The demo runner's control flow against a fake API (no stack needed)."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import httpx
import pytest

import demo as demo_module
from demo import Demo

pytestmark = pytest.mark.unit


class FakeApi:
    """Just enough of the OpsPilot API for one demo run."""

    def __init__(self, root_cause: str = "application_latency", p95_after: float = 2.9) -> None:
        self.mode = "none"
        self.root_cause = root_cause
        self.p95_after = p95_after
        self.point_age_s = 0  # how old the newest metric point is
        self.calls: list[str] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        self.calls.append(f"{request.method} {path}")
        if path == "/api/health":
            return httpx.Response(200, json={"status": "ok", "checks": {}})
        if path == "/api/lab" and request.method == "GET":
            return httpx.Response(200, json={
                "enabled": True,
                "services": [{"name": "checkout", "mode": self.mode, "reachable": True}],
            })  # fmt: skip
        if path == "/api/lab/failure":
            self.mode = json.loads(request.content)["mode"]
            return httpx.Response(200, json={"name": "checkout", "mode": self.mode})
        if path == "/api/lab/traffic":
            return httpx.Response(202, json={"target": "checkout", "requests": 60})
        if path == "/api/metrics":
            value = self.p95_after if self.mode != "none" else 0.03
            now = datetime.now(UTC) + timedelta(seconds=1 if self.mode != "none" else 0)
            points = [
                {
                    "timestamp": (now - timedelta(seconds=self.point_age_s + 15 * i)).isoformat(),
                    "value": value,
                }
                for i in range(5)
            ]
            no_errors = [{**pt, "value": 0.0} for pt in points]
            return httpx.Response(200, json={
                "status": "ok", "errors": [],
                "series": {"p95_latency_s": points, "error_rate": no_errors},
            })  # fmt: skip
        if path == "/api/investigations":
            return httpx.Response(201, json={
                "id": "inv-1", "status": "completed", "latency_ms": 1500,
                "root_cause": self.root_cause, "confidence": 0.65, "summary": None,
                "report": {
                    "conclusion": "Most likely root cause: checkout request handling became slow",
                    "observations": [{"statement": "checkout p95 rose from 25 ms to 2900 ms"}],
                    "evidence": [{"citation": "troubleshooting/latency-troubleshooting.md#chunk-4",
                                  "score": 0.8}],
                    "recommendations": [{"action": "Profile checkout's request path"}],
                },
            })  # fmt: skip
        return httpx.Response(404, json={"error": {"code": "NOT_FOUND"}})


@pytest.fixture
def fake(monkeypatch):
    api = FakeApi()
    monkeypatch.setattr(demo_module.time, "sleep", lambda _s: None)
    return api


def make_demo(api: FakeApi) -> tuple[Demo, list[str]]:
    lines: list[str] = []
    demo = Demo("http://api", "http://ui", out=lines.append)
    demo.http = httpx.Client(base_url="http://api", transport=httpx.MockTransport(api.handler))
    return demo, lines


def test_run_passes_and_resets(fake):
    demo, lines = make_demo(fake)
    result = demo.run("latency")
    assert result.ok
    assert [s.name for s in result.stages] == [
        "preflight", "reset", "baseline", "inject", "traffic", "telemetry", "investigate",
        "verify",
    ]  # fmt: skip
    assert fake.mode == "none"  # always reset afterwards
    demo.summary(result)
    assert any("Open in the UI: http://ui/investigations/inv-1" in line for line in lines)
    assert "Demo PASSED" in lines[-1]


def test_wrong_diagnosis_fails_the_run(fake):
    fake.root_cause = "database_degradation"
    demo, lines = make_demo(fake)
    result = demo.run("latency")
    assert not result.ok
    assert any("expected 'application_latency'" in line for line in lines)
    assert fake.mode == "none"


def test_keep_leaves_the_failure_injected(fake):
    demo, _ = make_demo(fake)
    assert demo.run("latency", keep=True).ok
    assert fake.mode == "latency"


def test_run_refuses_to_start_without_a_fresh_baseline(fake):
    """Right after a run the old spike is still recent: refuse instead of misreading it."""
    fake.point_age_s = 600  # no traffic in the last ten minutes
    demo, lines = make_demo(fake)
    result = demo.run("latency")
    assert not result.ok
    assert any("run `python scripts/demo.py prepare` first" in line for line in lines)
    assert fake.mode == "none"  # nothing was injected


def test_telemetry_that_never_moves_times_out(fake, monkeypatch):
    fake.p95_after = 0.03
    clock = iter(range(0, 10_000, 30))
    monkeypatch.setattr(demo_module.time, "monotonic", lambda: next(clock))
    demo, lines = make_demo(fake)
    result = demo.run("latency")
    assert not result.ok
    assert any("timed out" in line for line in lines)
