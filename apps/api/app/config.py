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
    llm_provider: str = Field(default="openai", description="LLM provider name")
    llm_model: str = Field(default="gpt-4o", description="LLM model identifier")
    llm_api_key: str = Field(default="", description="LLM API key (from env/secrets)")

    # --- Embeddings (consumed in Phase 4; not part of the Phase 1 schema) ---
    embedding_model: str = Field(
        default="text-embedding-3-small", description="Embedding model name"
    )
    embedding_dimensions: int = Field(default=1536, description="Embedding vector dimensions")

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
    agent_max_steps: int = Field(default=15, description="Max agent graph steps")
    agent_timeout_seconds: int = Field(default=120, description="Agent execution timeout")

    # --- RAG ---
    rag_chunk_size: int = Field(default=512, description="RAG chunk size in tokens")
    rag_chunk_overlap: int = Field(default=50, description="RAG chunk overlap in tokens")
    rag_top_k: int = Field(default=5, description="Number of RAG results to retrieve")
    rag_similarity_threshold: float = Field(
        default=0.7, description="Minimum cosine similarity for RAG results"
    )

    @model_validator(mode="after")
    def _guard_test_database(self) -> Settings:
        """Refuse to run the test environment against a non-test database."""
        if self.app_env == "test" and self.database_url is not None:
            assert_test_database_url(self.database_url.get_secret_value())
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
