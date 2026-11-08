"""Async engine lifecycle and request-scoped sessions.

One engine (and therefore one connection pool) is created during application
startup and disposed on shutdown. Each request gets its own AsyncSession from
the shared session factory.
"""

from __future__ import annotations

import time
from collections.abc import AsyncGenerator
from typing import Any

import structlog
from sqlalchemy import event
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import Settings

logger = structlog.get_logger(__name__)

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def build_engine(settings: Settings) -> AsyncEngine:
    """Create an AsyncEngine configured from settings."""
    engine = create_async_engine(
        settings.require_database_url(),
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
        pool_timeout=settings.db_pool_timeout,
        pool_recycle=settings.db_pool_recycle,
        pool_pre_ping=settings.db_pool_pre_ping,
    )
    if settings.db_slow_query_ms > 0:
        install_slow_query_logging(engine, settings.db_slow_query_ms)
    return engine


def build_session_factory(bind: Any) -> async_sessionmaker[AsyncSession]:
    """Session factory used by the app (and by tests with a different bind)."""
    return async_sessionmaker(bind, expire_on_commit=False, autoflush=False)


def install_slow_query_logging(engine: AsyncEngine, threshold_ms: int) -> None:
    """Log statements slower than ``threshold_ms``.

    Only the SQL text is logged; bound parameters are never logged because they
    may contain user-supplied or sensitive data.
    """
    sync_engine = engine.sync_engine

    @event.listens_for(sync_engine, "before_cursor_execute")
    def _start_timer(conn, cursor, statement, parameters, context, executemany):
        conn.info.setdefault("query_start", []).append(time.perf_counter())

    @event.listens_for(sync_engine, "after_cursor_execute")
    def _log_slow(conn, cursor, statement, parameters, context, executemany):
        elapsed_ms = (time.perf_counter() - conn.info["query_start"].pop()) * 1000
        if elapsed_ms >= threshold_ms:
            logger.warning(
                "db_slow_query",
                duration_ms=round(elapsed_ms, 1),
                statement=statement[:500],
            )


def init_engine(settings: Settings) -> AsyncEngine:
    """Create the process-wide engine and session factory (called from lifespan)."""
    global _engine, _session_factory
    if _engine is None:
        _engine = build_engine(settings)
        _session_factory = build_session_factory(_engine)
    return _engine


def get_engine() -> AsyncEngine:
    if _engine is None:
        raise RuntimeError("Database engine not initialised; call init_engine() at startup")
    return _engine


async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency providing one session per request.

    The service layer owns commits. If a request ends with an uncommitted
    transaction (for example because an exception escaped), closing the session
    rolls it back.
    """
    if _session_factory is None:
        raise RuntimeError("Database engine not initialised; call init_engine() at startup")
    async with _session_factory() as session:
        yield session


async def close_db_engine() -> None:
    """Dispose of the engine's pool on shutdown."""
    global _engine, _session_factory
    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _session_factory = None
