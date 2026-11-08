"""OpsPilot API application configuration.

All settings are loaded from environment variables via Pydantic Settings.
No credentials are hard-coded: DATABASE_URL has no default and must be supplied
by the environment (or a local, git-ignored .env file).
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url

AppEnv = Literal["development", "test", "production"]

# Database names used by the test environment must end with this suffix.
# This is a cheap, effective guard against a test run truncating real data.
TEST_DATABASE_SUFFIX = "_test"


class Settings(BaseSettings):
    """Central configuration for the OpsPilot API."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
        # An empty value (e.g. EMBEDDING_API_KEY= in .env) means "not set".
        env_ignore_empty=True,
    )

    # --- General ---
    app_env: AppEnv = Field(default="development", description="Runtime environment")
    log_level: str = Field(default="INFO", description="Logging level")

    # --- Database ---
    # SecretStr keeps the password out of repr(), logs and tracebacks.
    database_url: SecretStr | None = Field(
        default=None,
        description="Async SQLAlchemy database URL (postgresql+asyncpg://...)",
    )
    db_pool_size: int = Field(default=5, ge=1, description="Connection pool size")
    db_max_overflow: int = Field(default=10, ge=0, description="Pool max overflow")
    db_pool_timeout: int = Field(default=30, ge=1, description="Pool checkout timeout (s)")
    db_pool_recycle: int = Field(default=1800, ge=-1, description="Connection recycle age (s)")
    db_pool_pre_ping: bool = Field(default=True, description="Validate connections on checkout")
    db_slow_query_ms: int = Field(
        default=250, ge=0, description="Log SQL statements slower than this (0 disables)"
    )
    db_readiness_timeout_seconds: float = Field(
        default=2.0, gt=0, description="Timeout for the /ready database probe"
    )

    # --- LLM ---
    # --- LLM (optional; DECISIONS D-031). "none" = deterministic agent only ---
    llm_provider: Literal["none", "openai", "anthropic"] = Field(default="none")
    llm_model: str = Field(default="gpt-4o-mini", description="Model id for the provider")
    llm_api_key: SecretStr | None = Field(default=None, description="From env/secrets only")
    llm_base_url: str | None = Field(default=None, description="Override for gateways/proxies")
    llm_timeout_seconds: float = Field(default=30, gt=0, le=120)

    # --- Embeddings (DECISIONS D-027) ---
    # local: BAAI/bge-small-en-v1.5 via fastembed (ONNX, no API key)
    # openai: text-embedding-3-small requested at 384 dimensions
    # hashing: deterministic lexical embedder for tests / offline use only
    embedding_provider: Literal["local", "openai", "hashing"] = Field(default="local")
    embedding_model: str = Field(default="BAAI/bge-small-en-v1.5")
    embedding_api_key: SecretStr | None = Field(default=None, description="For provider=openai")
    embedding_cache_dir: str | None = Field(default=None, description="Local model cache path")

    # --- MCP ---
    mcp_server_url: str = Field(default="http://localhost:8001", description="MCP server base URL")

    # --- Observability ---
    prometheus_url: str = Field(default="http://localhost:9090", description="Prometheus URL")
    loki_url: str = Field(default="http://localhost:3100", description="Loki URL")

    # --- API ---
    api_host: str = Field(default="0.0.0.0", description="API bind host")
    api_port: int = Field(default=8000, description="API bind port")
    api_cors_origins: list[str] = Field(
        default=["http://localhost:3001"], description="Allowed CORS origins"
    )
    api_key: str = Field(default="", description="API authentication key")

    # --- Agent ---
    agent_max_steps: int = Field(default=15, ge=5, le=50, description="LangGraph recursion limit")
    agent_max_iterations: int = Field(
        default=2, ge=1, le=4, description="Evidence-gathering rounds"
    )
    agent_max_tool_calls: int = Field(default=16, ge=1, le=50)
    agent_timeout_seconds: int = Field(default=120, ge=5, le=600)
    agent_window_minutes: int = Field(default=60, ge=5, le=360, description="Default lookback")
    agent_degraded_p95_ms: float = Field(default=1000, gt=0)
    agent_degraded_error_ratio: float = Field(default=0.05, ge=0, le=1)
    mcp_auth_token: SecretStr | None = Field(default=None, description="Bearer token for MCP")

    # --- Incident lab (UI failure injection; demo workloads only, D-034) ---
    enable_incident_lab: bool = Field(default=False)
    lab_targets: dict[str, str] = Field(
        default={
            "checkout": "http://checkout:8080",
            "payments": "http://payments:8081",
            "users": "http://users:8082",
        },
        description="Demo services the lab may control, name -> internal base URL",
    )
    lab_traffic_target: str = Field(default="checkout")
    public_grafana_url: str | None = Field(
        default=None, description="Grafana link shown in the UI (browser-reachable URL)"
    )
    failure_admin_token: SecretStr | None = Field(default=None)

    # --- RAG ---
    rag_docs_path: str = Field(default="../../docs/knowledge", description="Knowledge base root")
    # Sizes are in words (whitespace tokens), not model tokens: ~300 words stays
    # under bge-small's 512-token input limit for English prose.
    rag_chunk_size: int = Field(default=300, ge=50, le=1000, description="Max words per chunk")
    rag_chunk_overlap: int = Field(default=40, ge=0, le=200, description="Words of overlap")
    rag_top_k: int = Field(default=5, ge=1, le=20, description="Chunks returned per query")
    rag_max_chunks_per_document: int = Field(default=2, ge=1, le=10)
    rag_similarity_threshold: float = Field(
        default=0.55, ge=0.0, le=1.0, description="Minimum cosine similarity returned"
    )

    @model_validator(mode="after")
    def _guard_test_database(self) -> Settings:
        """Refuse to run the test environment against a non-test database."""
        if self.app_env == "test" and self.database_url is not None:
            assert_test_database_url(self.database_url.get_secret_value())
        return self

    @model_validator(mode="after")
    def _check_rag_settings(self) -> Settings:
        if self.rag_chunk_overlap >= self.rag_chunk_size:
            raise ValueError("RAG_CHUNK_OVERLAP must be smaller than RAG_CHUNK_SIZE")
        if self.embedding_provider == "openai" and self.embedding_model.startswith("BAAI/"):
            # Sensible default when switching provider without naming a model.
            self.embedding_model = "text-embedding-3-small"
        return self

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

    def require_database_url(self) -> str:
        """Return the raw database URL or fail with a clear (secret-free) message."""
        if self.database_url is None:
            raise RuntimeError("DATABASE_URL is not configured")
        return self.database_url.get_secret_value()


def assert_test_database_url(url: str) -> None:
    """Raise ValueError unless ``url`` points at a database named ``*_test``."""
    database = make_url(url).database or ""
    if not database.endswith(TEST_DATABASE_SUFFIX):
        raise ValueError(
            f"Test environment requires a database whose name ends with "
            f"'{TEST_DATABASE_SUFFIX}' (got '{database}')"
        )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return cached application settings."""
    return Settings()
