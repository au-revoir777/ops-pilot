"""Request-level security controls: API key, CORS, concurrency cap, log redaction."""

from __future__ import annotations

import asyncio
import re
from collections.abc import AsyncGenerator

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from pydantic import ValidationError

from app import security
from app.config import Settings, get_settings
from app.main import create_app
from app.security import redact_secrets

KEY = "unit-test-api-key-0123456789"


@pytest.fixture
def keyed_settings(monkeypatch):
    monkeypatch.setenv("API_KEY", KEY)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


async def client_for(app: FastAPI) -> AsyncGenerator[AsyncClient, None]:
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.fixture
async def keyed_client(keyed_settings) -> AsyncGenerator[AsyncClient, None]:
    async for c in client_for(create_app()):
        yield c


class TestApiKey:
    async def test_api_requires_the_key_when_configured(self, keyed_client):
        response = await keyed_client.get("/api/config")
        assert response.status_code == 401
        assert response.json()["error"]["code"] == "UNAUTHORIZED"
        assert KEY not in response.text

    async def test_wrong_key_is_rejected(self, keyed_client):
        response = await keyed_client.get("/api/config", headers={"X-API-Key": "nope"})
        assert response.status_code == 401

    async def test_right_key_is_accepted(self, keyed_client):
        response = await keyed_client.get("/api/config", headers={"X-API-Key": KEY})
        assert response.status_code == 200

    @pytest.mark.parametrize("path", ["/health", "/metrics"])
    async def test_probes_stay_open(self, keyed_client, path):
        assert (await keyed_client.get(path)).status_code == 200

    async def test_every_api_route_is_protected(self, keyed_settings):
        """Every /api route, every method, rejects a request without the key."""
        app = create_app()
        api_routes = [(t, m) for _, t, m in app.state.route_index if t.startswith("/api/")]
        assert len(api_routes) >= 15
        async for c in client_for(app):
            for template, methods in api_routes:
                path = re.sub(r"\{[^}]+\}", "00000000-0000-0000-0000-000000000000", template)
                for method in methods - {"HEAD"}:
                    response = await c.request(method, path, json={})
                    assert response.status_code == 401, (method, template, response.text)

    def test_production_refuses_to_start_without_a_key(self):
        with pytest.raises(ValidationError, match="API_KEY must be set"):
            Settings(_env_file=None, app_env="production")

    def test_key_is_a_secret(self):
        settings = Settings(_env_file=None, api_key=KEY)
        assert KEY not in repr(settings)


async def test_cors_allows_no_credentials_and_no_origins_by_default():
    async for c in client_for(create_app()):
        response = await c.options(
            "/api/config",
            headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "GET"},
        )
        assert "access-control-allow-origin" not in response.headers
        assert response.headers.get("access-control-allow-credentials") != "true"


async def test_concurrency_cap_rejects_with_429(monkeypatch):
    monkeypatch.setattr(security, "_slots", asyncio.Semaphore(1))
    monkeypatch.setattr(security, "_slots_size", get_settings().max_concurrent_investigations)
    monkeypatch.setattr(security, "_semaphore", lambda: security._slots)
    holder = security.investigation_slot()
    await holder.__anext__()  # one investigation running
    with pytest.raises(security.TooManyInvestigations):
        await security.investigation_slot().__anext__()
    with pytest.raises(StopAsyncIteration):
        await holder.__anext__()  # it finishes and frees the slot
    second = security.investigation_slot()
    await second.__anext__()  # now a new one may start


class TestLogRedaction:
    def run(self, **event):
        return redact_secrets(None, "info", {"event": "something", **event})

    def test_secret_named_fields_are_masked(self):
        out = self.run(api_key="abc", Authorization="Bearer x", db_password="p", count=3)
        assert out["api_key"] == out["Authorization"] == out["db_password"] == "[REDACTED]"
        assert out["count"] == 3

    def test_credentials_inside_strings_are_masked(self):
        out = self.run(
            url="postgresql://opspilot:s3cret@db:5432/x",
            header="Bearer abcdefghijklmnop",
            note="key sk-abcdefghijklmnopqrstu",
        )
        assert "s3cret" not in out["url"] and "[REDACTED]@" in out["url"]
        assert out["header"] == "Bearer [REDACTED]"
        assert "sk-abc" not in out["note"]

    def test_nested_values_and_the_event_text(self):
        out = redact_secrets(
            None, "info", {"event": "connect postgresql://u:pw@h/db", "extra": {"token": "t"}}
        )
        assert "pw@" not in out["event"]
        assert out["extra"] == {"token": "[REDACTED]"}

    def test_correlation_fields_are_untouched(self):
        out = self.run(request_id="abc-123", service="opspilot-api")
        assert out["request_id"] == "abc-123"
