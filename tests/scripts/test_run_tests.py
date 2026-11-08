"""The test runner composes the right commands for each tier."""

from __future__ import annotations

import pytest

import run_tests

pytestmark = pytest.mark.unit


def names(tier: str, web: bool = True) -> list[str]:
    return [name for name, _, _ in run_tests.steps(tier, web)]


def test_tiers_select_by_marker():
    for tier in ("unit", "integration", "system", "evaluation"):
        command = run_tests.steps(tier, web=False)[0][1]
        assert command[-2:] == ["-m", tier]


def test_default_run_is_unit_plus_integration():
    # No -m: pyproject's addopts already exclude system and evaluation.
    command = run_tests.steps("all", web=False)[0][1]
    assert command[1:] == ["-m", "pytest"]


def test_frontend_steps_join_their_tier(monkeypatch):
    monkeypatch.setattr(run_tests.shutil, "which", lambda name: f"/usr/bin/{name}")
    assert names("unit") == ["pytest -m unit", "typecheck", "vitest", "contrast"]
    assert names("system") == ["pytest -m system", "playwright"]
    assert names("integration") == ["pytest -m integration"]
    assert names("unit", web=False) == ["pytest -m unit"]


def test_coverage_writes_a_report():
    command = run_tests.steps("coverage", web=False)[0][1]
    assert "--cov" in command and "--cov-report=xml" in command
