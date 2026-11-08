"""Test helpers shared by the demo-workload unit and integration tests."""

from __future__ import annotations

from collections.abc import AsyncIterator

import httpx
from fastapi import FastAPI

from opsdemo.config import WorkloadSettings


def make_settings(**overrides) -> WorkloadSettings:
    """Fast, deterministic settings for tests (seeded RNG, short injected delays)."""
    values = {
        "service_name": "test-service",
        "service_version": "9.9.9",
        "failure_seed": 1234,
        "failure_latency_ms": 300,
        "failure_db_latency_ms": 300,
        "slow_query_ms": 200,
        "slow_request_ms": 250,
        "users_url": "http://users.test",
        "payments_url": "http://payments.test",
    }
    values.update(overrides)
    return WorkloadSettings(_env_file=None, **values)


async def open_client(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    """In-process client that also runs the app lifespan (downstream HTTP client)."""
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://workload") as client:
            yield client
