"""API -> database -> agent integration tests (agent replays simulated telemetry)."""

from __future__ import annotations

from contextlib import asynccontextmanager

import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Incident, Investigation, InvestigationStatus
from app.dependencies import get_agent_factory
from app.routes.system import get_mcp_connector, get_mcp_probe

QUESTION = {"query": "Investigate why checkout latency increased"}


async def test_question_runs_agent_and_persists_result(
    client: AsyncClient, db_session: AsyncSession
):
    response = await client.post("/api/investigations", json=QUESTION)
    assert response.status_code == 201, response.text
    body = response.json()

    assert body["status"] == "completed"
    assert body["service"] == "checkout"
    assert body["root_cause"] == "deployment_db_regression"
    assert body["diagnosis"].startswith("Most likely root cause: Release 1.8.2")
    assert 0 < body["confidence"] <= 0.95
    assert body["latency_ms"] >= 0
    assert body["report"]["recommendations"][0]["requires_human_approval"] is True

    types = [e["event_type"] for e in body["events"]]
    assert types[0] == "status_change" and types[-1] == "status_change"
    for kind in ("evidence", "tool_call", "hypothesis", "conclusion"):
        assert kind in types, kind
    evidence = [e["details"] for e in body["events"] if e["event_type"] == "evidence"]
    assert {e["source_type"] for e in evidence} == {"telemetry", "knowledge"}
    sequences = [e["sequence"] for e in body["events"]]
    assert sequences == list(range(1, len(sequences) + 1))

    # An ad-hoc question gets its own incident, now under investigation.
    incident = await db_session.get(Incident, body["incident_id"])
    assert incident.title == "Investigation: Investigate why checkout latency increased"
    assert incident.status.value == "investigating"

    # Persisted, not just returned.
    fetched = (await client.get(f"/api/investigations/{body['id']}")).json()
    assert fetched["root_cause"] == body["root_cause"]
    assert fetched["report"] == body["report"]


async def test_background_mode_returns_202_and_completes(client: AsyncClient):
    response = await client.post("/api/investigations", json={**QUESTION, "wait": False})
    assert response.status_code == 202
    assert response.json()["status"] == "pending"
    # The test transport waits for background tasks before returning.
    fetched = (await client.get(f"/api/investigations/{response.json()['id']}")).json()
    assert fetched["status"] == "completed"
    assert fetched["root_cause"] == "deployment_db_regression"


@pytest.mark.parametrize("agent_case", ["unknown-service"])
async def test_inconclusive_investigation_completes_without_root_cause(client: AsyncClient):
    response = await client.post(
        "/api/investigations", json={"query": "Why is the mobile app broken?"}
    )
    body = response.json()
    assert response.status_code == 201
    assert body["status"] == "completed"
    assert body["root_cause"] is None
    assert body["report"]["missing_evidence"]


def failing_factory(error: Exception):
    @asynccontextmanager
    async def factory(_session):
        class Agent:
            async def run(self, *args, **kwargs):
                raise error

        yield Agent()

    return factory


async def test_agent_timeout_marks_investigation_failed(
    app: FastAPI, client: AsyncClient, db_session: AsyncSession
):
    app.dependency_overrides[get_agent_factory] = lambda: failing_factory(TimeoutError())
    response = await client.post("/api/investigations", json=QUESTION)
    assert response.status_code == 504
    error = response.json()["error"]
    assert error["code"] == "INVESTIGATION_TIMEOUT"
    assert error["request_id"]
    investigation = (await db_session.execute(select(Investigation))).scalars().one()
    assert investigation.status is InvestigationStatus.FAILED
    assert "timed out" in investigation.summary


async def test_agent_crash_marks_failed_without_leaking_details(
    app: FastAPI, client: AsyncClient, db_session: AsyncSession
):
    app.dependency_overrides[get_agent_factory] = lambda: failing_factory(RuntimeError("secret"))
    response = await client.post("/api/investigations", json=QUESTION)
    assert response.status_code == 500
    assert response.json()["error"]["code"] == "AGENT_FAILED"
    assert "secret" not in response.text
    investigation = (await db_session.execute(select(Investigation))).scalars().one()
    assert investigation.status is InvestigationStatus.FAILED


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"query": "x"},
        {"query": "valid question", "service": "Bad Name"},
        {"query": "valid question", "window_minutes": 1},
    ],
)
async def test_investigation_validation(client: AsyncClient, payload):
    assert (await client.post("/api/investigations", json=payload)).status_code == 422


class FakeTools:
    def __init__(self, result):
        self.result = result

    async def call(self, tool, arguments):
        return self.result


def connector_for(result):
    @asynccontextmanager
    async def connect():
        yield FakeTools(result)

    return lambda: connect


async def test_services_merge_registered_and_telemetry(app: FastAPI, client: AsyncClient):
    await client.post("/api/incidents", json={"title": "x", "service_name": "billing"})
    series = [
        {"metric": {"service": "checkout", "project": "opsdemo"}, "points": []},
        {"metric": {"service": "billing", "project": "shop"}, "points": []},
    ]
    app.dependency_overrides[get_mcp_connector] = connector_for({"status": "ok", "series": series})
    body = (await client.get("/api/services")).json()
    assert body["telemetry_status"] == "ok"
    services = {s["name"]: s for s in body["services"]}
    assert services["billing"]["sources"] == ["registered", "telemetry"]
    assert services["billing"]["project"] == "shop"
    assert services["checkout"]["sources"] == ["telemetry"]


async def test_services_when_telemetry_is_unavailable(app: FastAPI, client: AsyncClient):
    app.dependency_overrides[get_mcp_connector] = connector_for({"status": "unavailable"})
    body = (await client.get("/api/services")).json()
    assert body["telemetry_status"] == "unavailable"


@pytest.mark.parametrize(("mcp_up", "expected_mcp"), [(True, "ok"), (False, "down")])
async def test_dependency_health(app: FastAPI, client: AsyncClient, mcp_up, expected_mcp):
    async def probe() -> bool:
        return mcp_up

    app.dependency_overrides[get_mcp_probe] = lambda: probe
    response = await client.get("/api/health")
    body = response.json()
    assert response.status_code == 200  # only a database outage makes this 503
    assert body["checks"]["database"] == "ok"
    assert body["checks"]["mcp"] == expected_mcp
    assert body["checks"]["knowledge_base"] == "empty"  # nothing ingested in this test DB
    assert body["checks"]["llm"] == "disabled"
    assert body["status"] == "degraded"


async def test_list_investigations_newest_first(client: AsyncClient, db_session: AsyncSession):
    first = (await client.post("/api/investigations", json=QUESTION)).json()
    second = (await client.post("/api/investigations", json=QUESTION)).json()
    # Both rows share one test transaction, so now() gives them the same created_at;
    # age the first one explicitly to make the ordering observable.
    await db_session.execute(
        text(
            "UPDATE investigations SET created_at = created_at - interval '1 minute' WHERE id = :id"
        ),
        {"id": first["id"]},
    )
    listed = (await client.get("/api/investigations")).json()
    assert [i["id"] for i in listed[:2]] == [second["id"], first["id"]]
    assert listed[0]["root_cause"] == "deployment_db_regression"
    assert "report" not in listed[0]  # summaries only
    completed = (await client.get("/api/investigations", params={"status": "completed"})).json()
    assert len(completed) == 2
    assert (await client.get("/api/investigations", params={"limit": 0})).status_code == 422


class PerToolFake:
    async def call(self, tool, arguments):
        if tool == "query_metrics":
            return {"status": "ok", "series": [{"metric": {"service": "checkout"}, "points": []}]}
        return {"status": "ok", "health": "degraded", "p95_latency_ms": 2100.0,
                "error_rate": 0.0, "request_rate": 3.2, "version": "1.8.2"}  # fmt: skip


async def test_services_with_health(app: FastAPI, client: AsyncClient):
    @asynccontextmanager
    async def connect():
        yield PerToolFake()

    app.dependency_overrides[get_mcp_connector] = lambda: connect
    body = (await client.get("/api/services", params={"health": "true"})).json()
    [checkout] = body["services"]
    assert checkout["health"] == "degraded"
    assert checkout["p95_latency_ms"] == 2100.0
    assert checkout["version"] == "1.8.2"
