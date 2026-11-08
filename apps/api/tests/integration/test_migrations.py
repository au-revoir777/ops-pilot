"""Migration tests against a real PostgreSQL database.

These are synchronous tests because Alembic's env.py drives its own event loop.
"""

from __future__ import annotations

import asyncio

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import inspect, pool, text
from sqlalchemy.ext.asyncio import create_async_engine

from app.db.models import Base

APP_TABLES = {"workloads", "incidents", "investigations", "investigation_events"}


def _run(database_url: str, fn):
    async def _inner():
        engine = create_async_engine(database_url, poolclass=pool.NullPool)
        try:
            async with engine.connect() as conn:
                return await conn.run_sync(fn)
        finally:
            await engine.dispose()

    return asyncio.run(_inner())


def _tables(conn) -> set[str]:
    return set(inspect(conn).get_table_names()) - {"alembic_version"}


def _has_vector(conn) -> bool:
    return (
        conn.execute(text("SELECT 1 FROM pg_extension WHERE extname = 'vector'")).first()
        is not None
    )


@pytest.fixture
def at_head(alembic_config: Config, migrated_database: None, database_url: str):
    yield
    # Leave the database at head for the rest of the suite, whatever happened.
    command.upgrade(alembic_config, "head")


def test_upgrade_from_empty_database(alembic_config: Config, database_url: str, at_head):
    command.downgrade(alembic_config, "base")
    assert _run(database_url, _tables) == set()

    command.upgrade(alembic_config, "head")
    assert _run(database_url, _tables) == APP_TABLES
    assert _run(database_url, _has_vector)


def test_downgrade_then_reupgrade(alembic_config: Config, database_url: str, at_head):
    command.downgrade(alembic_config, "base")
    assert _run(database_url, _tables) == set()
    assert not _run(database_url, _has_vector)

    command.upgrade(alembic_config, "head")
    command.downgrade(alembic_config, "base")
    command.upgrade(alembic_config, "head")
    assert _run(database_url, _tables) == APP_TABLES


def test_models_match_migrations(database_url: str, migrated_database: None):
    """Autogenerate finds no differences: the migration is the complete schema."""

    def _diff(conn):
        context = MigrationContext.configure(conn, opts={"compare_type": True})
        return compare_metadata(context, Base.metadata)

    assert _run(database_url, _diff) == []
