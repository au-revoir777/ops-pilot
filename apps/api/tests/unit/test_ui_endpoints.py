"""Unit tests for the UI-facing read endpoints: config, metrics, deployments, replay."""

from __future__ import annotations

from contextlib import asynccontextmanager

import pytest
from httpx import ASGITransport, AsyncClient

from app.config import get_settings
from app.main import create_app
from app.routes.system import get_mcp_connector


class RecordingTools:
    def __init__(self, results):
        self.results = results
        self.calls = []

    async def call(self, tool, arguments):
        self.calls.append((tool, arguments))
        return self.results(tool, arguments)


@pytest.fixture
def tools():
    def results(tool, arguments):
        if tool == "query_metrics":
            points = [{"timestamp": "2026-11-08T12:00:00Z", "value": 0.2}]
            return {"status": "ok", "series": [{"metric": {}, "points": points}]}
        return {"status": "ok", "deployments": [{"version": "1.8.2", "status": "active"}]}

    return RecordingTools(results)


@pytest.fixture
async def client(tools):
    app = create_app()

    @asynccontextmanager
    async def connect():
        yield tools

    app.dependency_overrides[get_mcp_connector] = lambda: connect
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


async def test_config_exposes_only_safe_values(client, monkeypatch):
    from pydantic import SecretStr

    monkeypatch.setattr(get_settings(), "llm_api_key", SecretStr("sk-very-secret"))
    response = await client.get("/api/config")
    body = response.json()
    assert body["read_only"] is True
    assert body["llm_provider"] == "none" and body["llm_model"] is None
    assert set(body) == {"environment", "version", "read_only", "llm_provider", "llm_model",
                         "incident_lab_enabled", "grafana_url"}  # fmt: skip
    assert "sk-very-secret" not in response.text


async def test_metrics_use_only_allow_listed_queries(client, tools):
    body = (await client.get("/api/metrics", params={"service": "checkout", "range": "1h"})).json()
    assert body["status"] == "ok"
    assert set(body["series"]) == {"request_rate", "error_rate", "p50_latency_s", "p95_latency_s",
                                   "p99_latency_s"}  # fmt: skip
    assert all(args["start_time"] == "now-60m" for _, args in tools.calls)
    assert all('service="checkout"' in args["query"] for _, args in tools.calls)


@pytest.mark.parametrize(
    "params", [{"service": 'x"}) or vector(1'}, {"service": "checkout", "range": "7d"}, {}]
)
async def test_metrics_validation(client, params):
    assert (await client.get("/api/metrics", params=params)).status_code == 422


async def test_metrics_partial_when_some_queries_fail(tools):
    tools.results = lambda tool, args: (
        {"status": "unavailable", "errors": [{"error": "metrics_unavailable"}]}
        if "p99" in args["query"]
        else {"status": "ok", "series": []}
    )
    app = create_app()

    @asynccontextmanager
    async def connect():
        yield tools

    app.dependency_overrides[get_mcp_connector] = lambda: connect
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        body = (await c.get("/api/metrics", params={"service": "checkout"})).json()
    assert body["status"] == "partial"
    assert body["errors"] == ["p99_latency_s: metrics_unavailable"]


async def test_deployments(client, tools):
    body = (await client.get("/api/services/checkout/deployments", params={"hours": 2})).json()
    assert body["deployments"][0]["version"] == "1.8.2"
    assert tools.calls == [("get_recent_deployments", {"service": "checkout", "lookback_hours": 2})]


async def test_replay_catalogue_and_run(client):
    cases = (await client.get("/api/replays")).json()
    assert len(cases) >= 10
    loki_down = next(c for c in cases if c["id"] == "loki-down-deploy-db")
    assert loki_down["unavailable_sources"] == ["get_recent_logs"]

    result = (await client.post("/api/replays/deploy-db-regression")).json()
    assert result["match"] is True and result["service_match"] is True
    assert result["report"]["root_cause"] == "deployment_db_regression"
    assert (await client.post("/api/replays/nope")).status_code == 404
