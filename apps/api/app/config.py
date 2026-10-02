"""OpsPilot API application configuration.

All settings are loaded from environment variables via Pydantic Settings.
No credentials are hard-coded.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Central configuration for the OpsPilot API."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # --- General ---
    app_env: str = Field(default="development", description="Runtime environment")
    log_level: str = Field(default="INFO", description="Logging level")

    # --- Database ---
    database_url: str = Field(
        default="postgresql+asyncpg://opspilot:opspilot_dev@localhost:5432/opspilot",
        description="Async SQLAlchemy database URL",
    )

    # --- LLM ---
    llm_provider: str = Field(default="openai", description="LLM provider name")
    llm_model: str = Field(default="gpt-4o", description="LLM model identifier")
    llm_api_key: str = Field(default="", description="LLM API key (from env/secrets)")

    # --- Embeddings ---
    embedding_model: str = Field(
        default="text-embedding-3-small", description="Embedding model name"
    )
    embedding_dimensions: int = Field(default=1536, description="Embedding vector dimensions")

    # --- MCP ---
    mcp_server_url: str = Field(
        default="http://localhost:8001", description="MCP server base URL"
    )

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

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return cached application settings."""
    return Settings()
