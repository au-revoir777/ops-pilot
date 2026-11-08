"""Integration-test fixtures: a real, disposable PostgreSQL + pgvector database.

Database: TEST_DATABASE_URL, defaulting to the ``postgres-test`` Compose service
(``docker compose --profile test up -d postgres-test``), which runs on tmpfs
bound to 127.0.0.1:5433. CI starts the same image as a service container.
The database name must end in ``_test``; anything else is refused.

Schema: built once per session with ``alembic upgrade head`` (the real
migrations, not ``metadata.create_all``), so tests exercise the schema that
production will run.

Isolation: every test runs inside an outer transaction on a dedicated
connection that is rolled back at the end. The session joins it with
``join_transaction_mode="create_savepoint"``, so a service's ``commit()``
only releases a SAVEPOINT and its ``rollback()`` returns to that savepoint.
Services behave exactly as in production, and nothing leaks between tests.
"""

from __future__ import annotations

import os
from collections.abc import AsyncGenerator, Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import pool
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, AsyncSession, create_async_engine

from app.config import assert_test_database_url
from app.db.session import get_db_session
from app.main import create_app

# Throwaway credentials for the local tmpfs test container only.
DEFAULT_TEST_DATABASE_URL = (
    "postgresql+asyncpg://opspilot_test:opspilot_test@127.0.0.1:5433/opspilot_test"
)
ALEMBIC_INI = Path(__file__).resolve().parents[2] / "alembic.ini"


@pytest.fixture(scope="session")
def database_url() -> str:
    url = os.environ.get("TEST_DATABASE_URL", DEFAULT_TEST_DATABASE_URL)
    assert_test_database_url(url)
    return url


@pytest.fixture(scope="session")
def alembic_config(database_url: str) -> Config:
    config = Config(str(ALEMBIC_INI))
    config.attributes["database_url"] = database_url
    config.attributes["configure_logger"] = False
    return config


@pytest.fixture(scope="session")
def migrated_database(alembic_config: Config) -> Iterator[None]:
    """Start from an empty schema and migrate to head once per test session."""
    command.downgrade(alembic_config, "base")
    command.upgrade(alembic_config, "head")
    yield


@pytest.fixture
async def engine(database_url: str, migrated_database: None) -> AsyncGenerator[AsyncEngine, None]:
    # NullPool: each test gets a fresh connection on its own event loop.
    engine = create_async_engine(database_url, poolclass=pool.NullPool)
    yield engine
    await engine.dispose()


@pytest.fixture
async def connection(engine: AsyncEngine) -> AsyncGenerator[AsyncConnection, None]:
    async with engine.connect() as conn:
        outer = await conn.begin()
        yield conn
        if outer.is_active:
            await outer.rollback()


@pytest.fixture
async def db_session(connection: AsyncConnection) -> AsyncGenerator[AsyncSession, None]:
    session = AsyncSession(
        bind=connection,
        expire_on_commit=False,
        autoflush=False,
        join_transaction_mode="create_savepoint",
    )
    yield session
    await session.close()


@pytest.fixture
def app(db_session: AsyncSession) -> FastAPI:
    app = create_app()

    async def _session() -> AsyncGenerator[AsyncSession, None]:
        yield db_session

    app.dependency_overrides[get_db_session] = _session
    return app


@pytest.fixture
async def client(app: FastAPI) -> AsyncGenerator[AsyncClient, None]:
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
