"""System test: MCP tools against the live stack (marker: system).

Agent-side path:  MCP client -> MCP server -> Prometheus / Loki / OpsPilot API -> workloads.

    ENABLE_FAILURE_INJECTION=true docker compose up -d --build \
        postgres migrate api checkout payments users prometheus loki alloy grafana mcp
    pytest -m system tests/system/test_mcp_stack.py

Override MCP_URL / CHECKOUT_URL / PROMETHEUS_URL / MCP_AUTH_TOKEN as needed.
"""

from __future__ import annotations

import os
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import httpx
import pytest
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

pytestmark = pytest.mark.system

MCP_URL = os.environ.get("MCP_URL", "http://127.0.0.1:8001")
CHECKOUT = os.environ.get("CHECKOUT_URL", "http://127.0.0.1:8080")
PROMETHEUS = os.environ.get("PROMETHEUS_URL", "http://127.0.0.1:9090")
TOKEN = os.environ.get("MCP_AUTH_TOKEN")
CART = {"user_id": "u-7", "items": [{"sku": "sku-1", "quantity": 1, "unit_price_cents": 999}]}


@asynccontextmanager
async def mcp_session() -> AsyncIterator[ClientSession]:
    headers = {"Authorization": f"Bearer {TOKEN}"} if TOKEN else {}
    async with httpx.AsyncClient(headers=headers, timeout=60) as http:
        async with streamable_http_client(f"{MCP_URL}/mcp", http_client=http) as streams:
            read, write, _ = streams
            async with ClientSession(read, write) as session:
                await session.initialize()
                yield session


async def call(session: ClientSession, tool: str, **arguments: Any) -> dict[str, Any]:
    result = await session.call_tool(tool, arguments)
    assert not result.isError, result.content
    return result.structuredContent


def send_checkouts(count: int) -> None:
    """Generate traffic. A loaded laptop can time out the odd request; most must succeed."""
    with httpx.Client(timeout=30) as client:
        ok = sum(
            client.post(f"{CHECKOUT}/checkout", json=CART).status_code == 201 for _ in range(count)
        )
    assert ok >= 0.8 * count, f"only {ok}/{count} checkouts succeeded"


def set_mode(mode: str) -> None:
    response = httpx.post(f"{CHECKOUT}/admin/failure", json={"mode": mode}, timeout=10)
    assert response.status_code == 200, "run the stack with ENABLE_FAILURE_INJECTION=true"


def test_prometheus_scrapes_the_mcp_server():
    targets = httpx.get(f"{PROMETHEUS}/api/v1/targets", timeout=10).json()["data"]["activeTargets"]
    assert {t["labels"]["instance"]: t["health"] for t in targets}.get("mcp:8001") == "up"


async def test_tools_answer_with_live_data():
    send_checkouts(20)
    time.sleep(25)  # scrape + rate window
    async with mcp_session() as session:
        health = await call(session, "get_service_health", service="checkout")
        assert health["status"] == "ok"
        assert health["targets_up"] >= 1
        assert health["version"]
        assert {d["service"] for d in health["dependency_status"]} >= {"users", "payments"}

        # Telemetry needs two scrapes of the downstream counter; poll briefly.
        deadline = time.monotonic() + 60
        while True:
            deps = await call(session, "get_service_dependencies", service="checkout")
            sources = {d["service"]: d["sources"] for d in deps["dependencies"]}
            if "telemetry" in sources.get("payments", []) or time.monotonic() > deadline:
                break
            time.sleep(5)
        assert sources["payments"] == ["catalog", "telemetry"]

        deployments = await call(session, "get_recent_deployments", service="checkout")
        assert any(d["status"] == "active" for d in deployments["deployments"])

        metrics = await call(
            session,
            "query_metrics",
            query='service:http_requests:rate1m{service="checkout"}',
            start_time="now-10m",
        )
        assert metrics["status"] == "ok" and metrics["series"]

        logs = await call(session, "get_recent_logs", service="checkout", minutes=10)
        assert logs["status"] == "ok" and logs["entries"]
        assert any(e["metadata"].get("request_id") for e in logs["entries"])


async def test_latency_incident_is_visible_through_mcp():
    set_mode("latency")
    try:
        send_checkouts(15)
        deadline = time.monotonic() + 90
        async with mcp_session() as session:
            while True:
                health = await call(session, "get_service_health", service="checkout")
                if health["health"] == "degraded" or time.monotonic() > deadline:
                    break
                time.sleep(5)
            assert health["health"] == "degraded", health
            assert health["p95_latency_ms"] > 1000
            # The time is spent inside checkout: its p95 dwarfs its dependencies'.
            for dep in health["dependency_status"]:
                if dep["p95_latency_ms"] is not None:
                    assert health["p95_latency_ms"] > 2 * dep["p95_latency_ms"], dep

            logs = await call(
                session, "get_recent_logs", service="checkout", minutes=10, severity="warning"
            )
            assert any(e["message"] == "request_slow" for e in logs["entries"])

            events = await call(session, "get_incident_events", service="checkout", minutes=30)
            assert events["status"] in {"ok", "partial"}
    finally:
        set_mode("none")
