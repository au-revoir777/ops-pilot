"""MCP server configuration (environment-driven)."""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class McpSettings(BaseSettings):
    model_config = SettingsConfigDict(case_sensitive=False, extra="ignore", env_ignore_empty=True)

    service_name: str = Field(default="opspilot-mcp")
    log_level: str = Field(default="INFO")

    # Backends are fixed by configuration; callers can never supply a URL.
    prometheus_url: str = Field(default="http://prometheus:9090")
    loki_url: str = Field(default="http://loki:3100")
    api_url: str = Field(default="http://api:8000")
    catalog_path: str = Field(default="/etc/opspilot/services.yml")
    backend_timeout_seconds: float = Field(default=5.0, gt=0, le=30)

    # When set, every MCP request must carry "Authorization: Bearer <token>".
    mcp_auth_token: SecretStr | None = Field(default=None)

    # Health classification thresholds.
    degraded_error_ratio: float = Field(default=0.05, ge=0, le=1)
    degraded_p95_ms: float = Field(default=1000, gt=0)

    # Guard rails on how much data one tool call may pull.
    max_query_range_hours: int = Field(default=24, ge=1, le=168)
    max_points_per_series: int = Field(default=300, ge=10, le=2000)
    max_series: int = Field(default=50, ge=1, le=500)
    max_log_lines: int = Field(default=200, ge=1, le=1000)
    max_lookback_minutes: int = Field(default=360, ge=5, le=10080)
    deployment_lookback_hours: int = Field(default=24, ge=1, le=72)


@lru_cache(maxsize=1)
def get_settings() -> McpSettings:
    return McpSettings()
