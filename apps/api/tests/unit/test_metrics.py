"""Unit tests for the API's Prometheus metrics and log context (no database)."""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from prometheus_client import REGISTRY

from app import main, metrics
from app.db.models import (
    Incident,
    IncidentSeverity,
    IncidentStatus,
    Investigation,
    InvestigationStatus,
)
from app.db.session import get_db_session
from app.services.exceptions import DatabaseOperationError
from app.services.incident import IncidentService
from app.services.investigation import InvestigationService
from app.services.transactions import transaction


def sample(name: str, **labels: str) -> float:
    return REGISTRY.get_sample_value(name, labels) or 0.0


@pytest.fixture
def app() -> FastAPI:
    app = main.create_app()

    async def _session():
        yield AsyncMock()

    app.dependency_overrides[get_db_session] = _session
    return app


@pytest.fixture
async def client(app: FastAPI) -> AsyncGenerator[AsyncClient, None]:
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


async def test_metrics_endpoint_exposes_build_info(client: AsyncClient):
    response = await client.get("/metrics")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    assert 'app_info{service="opspilot-api",version="0.1.0"} 1.0' in response.text


async def test_metrics_endpoint_hidden_from_openapi(client: AsyncClient):
    assert "/metrics" not in (await client.get("/openapi.json")).json()["paths"]


async def test_metrics_use_full_route_template(client: AsyncClient):
    labels = {
        "service": "opspilot-api",
        "method": "GET",
        "route": "/api/incidents/{incident_id}",
        "status": "422",
    }
    before = sample("http_requests_total", **labels)
    await client.get("/api/incidents/not-a-uuid")
    await client.get("/api/incidents/also-not-a-uuid")
    assert sample("http_requests_total", **labels) == before + 2


async def test_unmatched_paths_collapse_to_one_label(client: AsyncClient):
    labels = {"service": "opspilot-api", "method": "GET", "route": "unmatched", "status": "404"}
    before = sample("http_requests_total", **labels)
    await client.get(f"/nope/{uuid.uuid4()}")
    assert sample("http_requests_total", **labels) == before + 1


async def test_probes_and_scrapes_are_not_counted(client: AsyncClient):
    await client.get("/health")
    await client.get("/metrics")
    text = (await client.get("/metrics")).text
    assert 'route="/health"' not in text
    assert 'route="/metrics"' not in text


async def test_server_errors_counted(app: FastAPI, client: AsyncClient):
    from app.dependencies import get_incident_service

    service = AsyncMock()
    service.list_incidents.side_effect = RuntimeError("boom")
    app.dependency_overrides[get_incident_service] = lambda: service
    labels = {"service": "opspilot-api", "route": "/api/incidents"}
    before = sample("http_request_errors_total", **labels)
    assert (await client.get("/api/incidents")).status_code == 500
    assert sample("http_request_errors_total", **labels) == before + 1


def mock_session() -> AsyncMock:
    session = AsyncMock()
    session.add = MagicMock()
    return session


async def test_incident_creation_and_transition_counted():
    incidents = AsyncMock()
    incidents.add.side_effect = lambda inc: inc
    service = IncidentService(mock_session(), incidents=incidents, workloads=MagicMock())
    before = sample("opspilot_incidents_created_total", severity="SEV1")
    await service.create_incident(title="x", severity=IncidentSeverity.SEV1)
    assert sample("opspilot_incidents_created_total", severity="SEV1") == before + 1

    incidents.get.return_value = Incident(id=uuid.uuid4(), status=IncidentStatus.OPEN)
    labels = {"from_status": "open", "to_status": "mitigated"}
    before = sample("opspilot_incident_transitions_total", **labels)
    await service.update_status(uuid.uuid4(), IncidentStatus.MITIGATED)
    assert sample("opspilot_incident_transitions_total", **labels) == before + 1


async def test_rolled_back_work_is_not_counted():
    session = mock_session()
    incidents = AsyncMock()
    incidents.get.return_value = Incident(id=uuid.uuid4(), status=IncidentStatus.CLOSED)
    labels = {"from_status": "closed", "to_status": "open"}
    before = sample("opspilot_incident_transitions_total", **labels)
    with pytest.raises(Exception):  # noqa: B017 - InvalidIncidentState
        await IncidentService(session, incidents=incidents).update_status(
            uuid.uuid4(), IncidentStatus.OPEN
        )
    assert sample("opspilot_incident_transitions_total", **labels) == before


async def test_finished_investigation_records_outcome_and_duration():
    investigations = AsyncMock()
    started = Investigation(id=uuid.uuid4(), status=InvestigationStatus.RUNNING)
    from datetime import UTC, datetime, timedelta

    started.started_at = datetime.now(UTC) - timedelta(seconds=30)
    investigations.get.return_value = started
    investigations.next_event_sequence.return_value = 2
    service = InvestigationService(
        mock_session(), investigations=investigations, incidents=AsyncMock()
    )

    before = sample("opspilot_investigations_finished_total", outcome="completed")
    before_count = sample("opspilot_investigation_duration_seconds_count", outcome="completed")
    before_sum = sample("opspilot_investigation_duration_seconds_sum", outcome="completed")
    await service.change_status(started.id, InvestigationStatus.COMPLETED)

    assert sample("opspilot_investigations_finished_total", outcome="completed") == before + 1
    assert (
        sample("opspilot_investigation_duration_seconds_count", outcome="completed")
        == before_count + 1
    )
    added = sample("opspilot_investigation_duration_seconds_sum", outcome="completed") - before_sum
    assert 29 <= added <= 40


async def test_db_errors_counted_by_operation():
    from sqlalchemy.exc import OperationalError

    session = mock_session()
    session.commit.side_effect = OperationalError("COMMIT", {}, Exception("gone"))
    before = sample("opspilot_db_errors_total", operation="unit_test_op")
    with pytest.raises(DatabaseOperationError):
        async with transaction(session, "unit_test_op"):
            pass
    assert sample("opspilot_db_errors_total", operation="unit_test_op") == before + 1


def test_every_log_line_gets_service_and_version():
    event = main._add_service_context(None, "info", {"event": "x"})
    assert event["service"] == metrics.SERVICE
    assert event["version"] == "0.1.0"
    # Explicit values are never overwritten.
    assert main._add_service_context(None, "info", {"service": "other"})["service"] == "other"
