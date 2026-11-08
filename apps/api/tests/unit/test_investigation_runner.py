"""Unit tests for the investigation runner and API routes (no database)."""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from httpx import ASGITransport, AsyncClient

from app.agents.graph import InvestigationAgent
from app.agents.simulation import NOW, ScenarioRetriever, ScenarioToolClient
from app.config import Settings
from app.db.models import InvestigationEventType, InvestigationStatus
from app.db.session import get_db_session
from app.main import create_app
from app.services.exceptions import AgentFailed, InvestigationTimeout
from app.services.investigation_runner import InvestigationRunner, report_events

SETTINGS = Settings(_env_file=None, llm_provider="none")
TELEMETRY = {
    "known_services": ["checkout"],
    "service": "checkout",
    "health": {"health": "degraded", "p95_ms": 2100, "error_rate": 0.0, "version": "1.8.2",
               "deps": {}},
    "latency_history": {"baseline_s": 0.2, "current_s": 2.1, "step_minutes_ago": 10},
    "db_history": {"baseline_s": 0.04, "current_s": 0.9, "step_minutes_ago": 10},
    "logs": {"slow_query_detected": 20},
    "deployments": [{"version": "1.8.2", "previous": "1.8.1", "minutes_ago": 12}],
}  # fmt: skip


def agent_factory(error: Exception | None = None):
    @asynccontextmanager
    async def factory(_session):
        if error is not None:
            yield SimpleNamespace(run=AsyncMock(side_effect=error))
        else:
            yield InvestigationAgent(ScenarioToolClient(TELEMETRY), ScenarioRetriever([]), SETTINGS,
                                     now=lambda: NOW)  # fmt: skip

    return factory


def runner_with_mocks(error: Exception | None = None) -> InvestigationRunner:
    runner = InvestigationRunner(AsyncMock(), agent_factory(error), SETTINGS)
    runner.investigations = AsyncMock()
    runner.investigations.change_status.return_value = SimpleNamespace(
        query="why is checkout slow", service="checkout"
    )
    runner.investigations.record_result.side_effect = lambda *a, **kw: kw
    return runner


async def test_run_persists_result_and_evidence_events():
    runner = runner_with_mocks()
    stored = await runner.run(uuid.uuid4())
    runner.investigations.change_status.assert_awaited_once()
    assert stored["result"]["root_cause"] == "deployment_db_regression"
    assert stored["result"]["report"]["service"] == "checkout"
    kinds = {event_type for event_type, _, _ in stored["events"]}
    assert {
        InvestigationEventType.EVIDENCE,
        InvestigationEventType.TOOL_CALL,
        InvestigationEventType.HYPOTHESIS,
        InvestigationEventType.CONCLUSION,
    } <= kinds
    assert stored["latency_ms"] >= 0


@pytest.mark.parametrize(
    ("error", "expected"),
    [(TimeoutError(), InvestigationTimeout), (RuntimeError("x"), AgentFailed)],
)
async def test_failures_mark_investigation_failed(error, expected):
    runner = runner_with_mocks(error)
    investigation_id = uuid.uuid4()
    with pytest.raises(expected) as excinfo:
        await runner.run(investigation_id)
    assert str(investigation_id) in str(excinfo.value)
    last = runner.investigations.change_status.await_args_list[-1]
    assert last.args == (investigation_id, InvestigationStatus.FAILED)
    runner.investigations.record_result.assert_not_awaited()


async def test_report_events_cover_every_part_of_the_report():
    agent = InvestigationAgent(ScenarioToolClient(TELEMETRY), ScenarioRetriever(
        [{"source": "runbooks/x.md", "content": "roll back slow query", "services": ["checkout"]}]
    ), SETTINGS, now=lambda: NOW)  # fmt: skip
    report = await agent.run("why is checkout slow")
    events = report_events(report)
    evidence = [d for t, _, d in events if t is InvestigationEventType.EVIDENCE]
    assert len(evidence) == len(report.observations) + len(report.evidence)
    assert {e["source_type"] for e in evidence} == {"telemetry", "knowledge"}
    tool_events = [d for t, _, d in events if t is InvestigationEventType.TOOL_CALL]
    assert {e["tool_name"] for e in tool_events} >= {"get_service_health", "get_recent_logs"}
    assert events[-1][0] is InvestigationEventType.CONCLUSION


@pytest.fixture
async def client():
    app = create_app()

    async def _session():
        yield AsyncMock()

    app.dependency_overrides[get_db_session] = _session
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.mark.parametrize(
    "payload",
    [{}, {"wait": True}, {"query": "ok?"[:2]}, {"query": "valid", "incident_id": "nope"}],
)
async def test_create_route_validation(client, payload):
    response = await client.post("/api/investigations", json=payload)
    assert response.status_code == 422


async def test_create_route_documents_202_and_new_fields(client):
    schema = (await client.get("/openapi.json")).json()
    post = schema["paths"]["/api/investigations"]["post"]
    assert "202" in post["responses"]
    body = schema["components"]["schemas"]["InvestigationCreate"]["properties"]
    assert {"query", "incident_id", "service", "window_minutes", "wait"} <= set(body)
