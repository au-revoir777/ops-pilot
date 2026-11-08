"""Unit tests for liveness/readiness probes and API-level error handling (no DB)."""

from collections.abc import AsyncGenerator
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.exc import OperationalError

from app.db.session import get_db_session
from app.dependencies import get_incident_service
from app.main import create_app
from app.services.exceptions import DatabaseOperationError, IncidentNotFound


@pytest.fixture
def app() -> FastAPI:
    return create_app()


@pytest.fixture
async def client(app: FastAPI) -> AsyncGenerator[AsyncClient, None]:
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


def override_session(app: FastAPI, session: object) -> None:
    async def _session():
        yield session

    app.dependency_overrides[get_db_session] = _session


async def test_health_returns_200_without_database(client: AsyncClient):
    response = await client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert data["service"] == "opspilot-api"
    assert data["checks"] == {"api": "healthy"}


async def test_ready_returns_200_when_database_responds(app: FastAPI, client: AsyncClient):
    session = AsyncMock()
    override_session(app, session)
    response = await client.get("/ready")
    assert response.status_code == 200
    assert response.json()["checks"]["database"] == "healthy"
    session.execute.assert_awaited_once()


async def test_ready_returns_503_when_database_fails(app: FastAPI, client: AsyncClient):
    session = AsyncMock()
    session.execute.side_effect = OperationalError("SELECT 1", {}, Exception("conn refused"))
    override_session(app, session)
    response = await client.get("/ready")
    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "not_ready"
    assert body["checks"]["database"] == "unhealthy"
    assert "conn refused" not in response.text


async def test_request_id_generated_and_echoed(client: AsyncClient):
    response = await client.get("/health")
    assert len(response.headers["x-request-id"]) == 32

    response = await client.get("/health", headers={"X-Request-ID": "abc-123"})
    assert response.headers["x-request-id"] == "abc-123"


async def test_malicious_request_id_replaced(client: AsyncClient):
    response = await client.get("/health", headers={"X-Request-ID": "bad id\nwith newline"})
    assert response.headers["x-request-id"] != "bad id\nwith newline"


async def test_not_found_is_structured(app: FastAPI, client: AsyncClient):
    service = AsyncMock()
    service.get_incident.side_effect = IncidentNotFound("Incident x not found")
    app.dependency_overrides[get_incident_service] = lambda: service
    response = await client.get(
        "/api/incidents/6f1c1a52-5d4e-4a0e-9a59-0b1f2b6b0d11", headers={"X-Request-ID": "req-1"}
    )
    assert response.status_code == 404
    assert response.json() == {
        "error": {
            "code": "INCIDENT_NOT_FOUND",
            "message": "Incident x not found",
            "request_id": "req-1",
        }
    }


async def test_database_error_hides_internal_message(app: FastAPI, client: AsyncClient):
    service = AsyncMock()
    service.list_incidents.side_effect = DatabaseOperationError("relation incidents missing")
    app.dependency_overrides[get_incident_service] = lambda: service
    response = await client.get("/api/incidents")
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "DATABASE_ERROR"
    assert "relation" not in response.text


async def test_unhandled_exception_returns_generic_500(app: FastAPI, client: AsyncClient):
    service = AsyncMock()
    service.list_incidents.side_effect = RuntimeError("password=hunter2")
    app.dependency_overrides[get_incident_service] = lambda: service
    response = await client.get("/api/incidents")
    assert response.status_code == 500
    assert response.json()["error"]["code"] == "INTERNAL_ERROR"
    assert "hunter2" not in response.text


async def test_invalid_uuid_is_422(app: FastAPI, client: AsyncClient):
    override_session(app, AsyncMock())
    response = await client.get("/api/incidents/not-a-uuid")
    assert response.status_code == 422


async def test_invalid_payload_is_422(app: FastAPI, client: AsyncClient):
    override_session(app, AsyncMock())
    response = await client.post("/api/incidents", json={"title": "", "severity": "SEV9"})
    assert response.status_code == 422


async def test_removed_chat_skeleton_is_gone(client: AsyncClient):
    # The unimplemented endpoint was removed (attack surface, Phase 11).
    response = await client.post("/api/chat")
    assert response.status_code == 404
