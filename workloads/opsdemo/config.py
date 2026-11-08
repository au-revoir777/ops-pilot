"""Workload configuration (environment-driven, no secrets in code)."""

from __future__ import annotations

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from opsdemo.failures import FailureMode


class WorkloadSettings(BaseSettings):
    # env_ignore_empty: Compose passes unset optional vars as "" (e.g. FAILURE_SEED=).
    model_config = SettingsConfigDict(case_sensitive=False, extra="ignore", env_ignore_empty=True)

    service_name: str = Field(default="workload", description="Service label for logs/metrics")
    service_version: str = Field(default="0.0.0", description="Deployed version")
    log_level: str = Field(default="INFO")

    # --- Failure injection (off unless explicitly enabled; see DECISIONS D-008) ---
    enable_failure_injection: bool = Field(default=False)
    failure_mode: FailureMode = Field(default=FailureMode.NONE)
    failure_latency_ms: int = Field(default=2000, ge=0, le=30_000)
    # Per query. Checkout runs two queries per request, so 900 ms each takes p95
    # from ~200 ms to ~2 s: the primary demo scenario.
    failure_db_latency_ms: int = Field(default=900, ge=0, le=30_000)
    failure_error_rate: float = Field(default=0.5, ge=0.0, le=1.0)
    # Seed makes injected behaviour (and normal jitter) reproducible run to run.
    failure_seed: int | None = Field(default=None)
    # When set, /admin/failure also requires the X-Admin-Token header.
    failure_admin_token: SecretStr | None = Field(default=None)

    # --- Thresholds that turn into WARN logs ---
    slow_request_ms: int = Field(default=1000, ge=1)
    slow_query_ms: int = Field(default=500, ge=1)

    # --- Downstream dependencies (checkout only) ---
    users_url: str = Field(default="http://users:8082")
    payments_url: str = Field(default="http://payments:8081")
    downstream_timeout_seconds: float = Field(default=5.0, gt=0)


def load_settings(service_name: str, service_version: str) -> WorkloadSettings:
    """Settings from the environment, with per-service defaults for name/version."""
    settings = WorkloadSettings()
    defaults = {"service_name": service_name, "service_version": service_version}
    return settings.model_copy(
        update={k: v for k, v in defaults.items() if k not in settings.model_fields_set}
    )
