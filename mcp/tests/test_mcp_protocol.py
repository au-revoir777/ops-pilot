"""Integration tests over the real MCP protocol.

The server runs in uvicorn on a free localhost port; an MCP SDK client talks to
it over Streamable HTTP (initialize, tools/list, tools/call), exactly as the
agent will. Backends are faked so the test runs anywhere.
"""

from __future__ import annotations

import socket
import threading
import time
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager

import httpx
import pytest
import uvicorn
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from mcp_fakes import FakeBackends, vector
from opsmcp.config import McpSettings
from opsmcp.server import create_app

pytestmark = pytest.mark.integration

TOKEN = "integration-test-token"
EXPECTED_TOOLS = {
    "get_service_health",
    "query_metrics",
    "get_recent_logs",
    "get_recent_deployments",
    "get_service_dependencies",
    "get_incident_events",
}


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest.fixture(scope="module")
def fake() -> FakeBackends:
    fake = FakeBackends()
    fake.instant = {
        "max by (instance) (up)": vector(({"instance": "checkout:8080"}, 1)),
        'service:http_requests:rate1m{service="checkout"}': vector(({}, 3.0)),
        'app_info{service="checkout"}': vector(({"service": "checkout", "version": "1.8.2"}, 1)),
        'service:http_errors:ratio_rate1m{service="checkout"}': vector(({}, 0.0)),
        'service:http_latency_seconds:p95_1m{service="checkout"}': vector(({}, 2.2)),
    }
    return fake


@pytest.fixture(scope="module")
def server_url(fake, tmp_path_factory) -> Iterator[str]:
    catalog = tmp_path_factory.mktemp("catalog") / "services.yml"
    catalog.write_text("services:\n  checkout: {depends_on: [payments]}\n", encoding="utf-8")
    settings = McpSettings(
        _env_file=None,
        prometheus_url="http://prometheus.test",
        loki_url="http://loki.test",
        api_url="http://api.test",
        catalog_path=str(catalog),
        mcp_auth_token=TOKEN,
    )
    app = create_app(settings, transport=httpx.MockTransport(fake))
    port = free_port()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not server.started:
        assert time.monotonic() < deadline, "MCP server did not start"
        time.sleep(0.05)
    yield f"http://127.0.0.1:{port}"
    server.should_exit = True
    thread.join(timeout=10)


@asynccontextmanager
async def mcp_session(server_url: str) -> AsyncIterator[ClientSession]:
    """An initialised MCP client session (opened inside the test's own task)."""
    headers = {"Authorization": f"Bearer {TOKEN}"}
    async with httpx.AsyncClient(headers=headers, timeout=30) as http:
        async with streamable_http_client(f"{server_url}/mcp", http_client=http) as streams:
            read, write, _ = streams
            async with ClientSession(read, write) as session:
                await session.initialize()
                yield session


async def test_tools_are_listed_with_input_and_output_schemas(server_url):
    async with mcp_session(server_url) as session:
        await _test_tools_are_listed_with_input_and_output_schemas(session)


async def _test_tools_are_listed_with_input_and_output_schemas(session):
    listed = (await session.list_tools()).tools
    assert {t.name for t in listed} == EXPECTED_TOOLS
    for tool in listed:
        assert tool.inputSchema["type"] == "object"
        assert tool.outputSchema is not None, tool.name
        assert tool.annotations.readOnlyHint is True
        assert tool.description


async def test_call_returns_structured_content(server_url):
    async with mcp_session(server_url) as session:
        await _test_call_returns_structured_content(session)


async def _test_call_returns_structured_content(session):
    result = await session.call_tool("get_service_health", {"service": "checkout"})
    assert not result.isError
    health = result.structuredContent
    assert health["health"] == "degraded"
    assert health["p95_latency_ms"] == 2200.0
    assert health["version"] == "1.8.2"
    assert any("p95 latency" in reason for reason in health["reasons"])


async def test_schema_rejects_invalid_arguments(server_url):
    async with mcp_session(server_url) as session:
        await _test_schema_rejects_invalid_arguments(session)


async def _test_schema_rejects_invalid_arguments(session):
    result = await session.call_tool("get_recent_logs", {"service": "checkout", "minutes": 0})
    assert result.isError
    injected = await session.call_tool("get_service_health", {"service": 'checkout"} or up{'})
    assert injected.isError


async def test_backend_outage_is_structured_not_an_exception(server_url, fake):
    async with mcp_session(server_url) as session:
        await _test_backend_outage_is_structured_not_an_exception(session, fake)


async def _test_backend_outage_is_structured_not_an_exception(session, fake):
    fake.down.add("loki.test")
    try:
        result = await session.call_tool("get_recent_logs", {"service": "checkout"})
    finally:
        fake.down.discard("loki.test")
    assert not result.isError
    assert result.structuredContent["status"] == "unavailable"
    assert result.structuredContent["errors"][0]["error"] == "logs_unavailable"


async def test_requests_without_token_are_rejected(server_url):
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{server_url}/mcp",
            json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
            headers={"Accept": "application/json, text/event-stream"},
        )
        assert response.status_code == 401
        wrong = await client.post(
            f"{server_url}/mcp", json={}, headers={"Authorization": "Bearer nope"}
        )
        assert wrong.status_code == 401


async def test_health_and_metrics_endpoints(server_url):
    async with mcp_session(server_url) as session:
        await session.call_tool("get_service_health", {"service": "checkout"})
    async with httpx.AsyncClient() as client:
        assert (await client.get(f"{server_url}/health")).json()["status"] == "healthy"
        metrics = (await client.get(f"{server_url}/metrics")).text
    assert 'opspilot_mcp_tool_calls_total{outcome="ok",tool="get_service_health"}' in metrics
    assert "opspilot_mcp_backend_request_duration_seconds_bucket" in metrics
