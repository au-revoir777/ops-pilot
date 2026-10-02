"""FastAPI dependency injection providers.

Centralizes database sessions, settings, and service dependencies
so they can be injected into route handlers.
"""

from __future__ import annotations

from app.config import Settings, get_settings


def get_current_settings() -> Settings:
    """Dependency: return application settings."""
    return get_settings()
