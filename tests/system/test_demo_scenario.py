"""System test: the flagship demo against the live stack (marker: system).

    ENABLE_INCIDENT_LAB=true ENABLE_FAILURE_INJECTION=true docker compose up -d
    python scripts/demo.py prepare
    pytest -m system tests/system/test_demo_scenario.py

Runs the spec's scenario end to end through the public API: inject latency into
checkout, generate traffic, wait for Prometheus to show it, ask "Why is checkout
latency high?", and require the expected diagnosis with facts, retrieved
evidence and a recommendation. Override OPSPILOT_API_URL as needed.
"""

from __future__ import annotations

import os

import pytest

from demo import Demo

pytestmark = pytest.mark.system

API = os.environ.get("OPSPILOT_API_URL", "http://127.0.0.1:8000")


def test_flagship_latency_demo():
    demo = Demo(API, "http://localhost:3001")
    result = demo.run("latency")
    demo.summary(result)
    assert result.ok, [(s.name, s.detail) for s in result.stages]
    report = result.investigation["report"]
    signals = {sig for obs in report["observations"] for sig in obs["signals"]}
    assert {"latency_step", "db_latency_flat", "dependencies_healthy"} <= signals
    assert report["evidence"], "no knowledge-base evidence was retrieved"
    assert report["recommendations"]
    # The audience-facing path: injection to diagnosis.
    assert result.presented_seconds < 180
