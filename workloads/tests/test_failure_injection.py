"""Unit tests for the failure injector and workload settings."""

from __future__ import annotations

import random

import pytest
from pydantic import ValidationError

from opsdemo.config import WorkloadSettings, load_settings
from opsdemo.failures import (
    FailureInjectionDisabled,
    FailureInjector,
    FailureMode,
    FailureProfile,
)

pytestmark = pytest.mark.unit

PROFILE = FailureProfile(latency_ms=2000, db_latency_ms=900, error_rate=0.5, jitter=0.2)


def injector(
    mode: FailureMode, *, enabled: bool = True, seed: int = 7, **profile
) -> FailureInjector:
    prof = FailureProfile(**{**PROFILE.__dict__, **profile})
    return FailureInjector(enabled=enabled, mode=mode, profile=prof, rng=random.Random(seed))


def test_disabled_injector_ignores_configured_mode():
    inj = injector(FailureMode.LATENCY, enabled=False)
    assert inj.mode is FailureMode.NONE
    assert inj.request_delay_seconds() == 0
    assert inj.db_delay_seconds() == 0
    assert not inj.should_fail_request()


def test_disabled_injector_refuses_mode_changes():
    with pytest.raises(FailureInjectionDisabled):
        injector(FailureMode.NONE, enabled=False).set_mode(FailureMode.ERRORS)


def test_none_mode_injects_nothing():
    inj = injector(FailureMode.NONE)
    assert inj.request_delay_seconds() == 0
    assert inj.db_delay_seconds() == 0
    assert not any(inj.should_fail_request() for _ in range(100))


def test_latency_mode_delays_within_jitter_band_only_for_requests():
    inj = injector(FailureMode.LATENCY)
    delays = [inj.request_delay_seconds() for _ in range(200)]
    assert all(1.6 <= d <= 2.4 for d in delays)
    assert inj.db_delay_seconds() == 0
    assert not inj.should_fail_request()


def test_db_mode_only_slows_database():
    inj = injector(FailureMode.DB)
    assert all(0.72 <= inj.db_delay_seconds() <= 1.08 for _ in range(200))
    assert inj.request_delay_seconds() == 0


@pytest.mark.parametrize(("rate", "expected"), [(0.0, 0), (1.0, 1000)])
def test_error_rate_extremes(rate, expected):
    inj = injector(FailureMode.ERRORS, error_rate=rate)
    assert sum(inj.should_fail_request() for _ in range(1000)) == expected


def test_error_rate_is_roughly_honoured():
    inj = injector(FailureMode.ERRORS, error_rate=0.5)
    failures = sum(inj.should_fail_request() for _ in range(2000))
    assert 900 <= failures <= 1100


def test_same_seed_reproduces_the_same_incident():
    a = injector(FailureMode.ERRORS, seed=42)
    b = injector(FailureMode.ERRORS, seed=42)
    assert [a.should_fail_request() for _ in range(50)] == [
        b.should_fail_request() for _ in range(50)
    ]


def test_mode_can_change_at_runtime_when_enabled():
    inj = injector(FailureMode.NONE)
    inj.set_mode(FailureMode.DB)
    assert inj.mode is FailureMode.DB
    inj.set_mode(FailureMode.NONE)
    assert inj.db_delay_seconds() == 0


class TestSettings:
    def test_injection_disabled_by_default(self, monkeypatch):
        monkeypatch.delenv("ENABLE_FAILURE_INJECTION", raising=False)
        monkeypatch.delenv("FAILURE_MODE", raising=False)
        settings = WorkloadSettings()
        assert settings.enable_failure_injection is False
        assert settings.failure_mode is FailureMode.NONE

    def test_unknown_failure_mode_rejected(self):
        with pytest.raises(ValidationError):
            WorkloadSettings(failure_mode="meltdown")

    def test_error_rate_bounds(self):
        with pytest.raises(ValidationError):
            WorkloadSettings(failure_error_rate=1.5)

    def test_load_settings_uses_service_defaults(self, monkeypatch):
        monkeypatch.delenv("SERVICE_NAME", raising=False)
        monkeypatch.delenv("SERVICE_VERSION", raising=False)
        settings = load_settings("checkout", "1.8.2")
        assert (settings.service_name, settings.service_version) == ("checkout", "1.8.2")

    def test_environment_overrides_service_defaults(self, monkeypatch):
        monkeypatch.setenv("SERVICE_VERSION", "1.8.1")
        assert load_settings("checkout", "1.8.2").service_version == "1.8.1"

    def test_admin_token_is_secret(self):
        settings = WorkloadSettings(failure_admin_token="hunter2")
        assert "hunter2" not in repr(settings)
