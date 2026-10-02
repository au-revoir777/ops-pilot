"""Unit tests for the health endpoint."""

import pytest


@pytest.mark.unit
class TestHealthEndpoint:
    """Tests for GET /health."""

    def test_health_returns_200(self, client):
        response = client.get("/health")
        assert response.status_code == 200

    def test_health_response_structure(self, client):
        response = client.get("/health")
        data = response.json()
        assert data["status"] == "healthy"
        assert data["service"] == "opspilot-api"
        assert data["version"] == "0.1.0"
        assert "timestamp" in data
        assert "checks" in data

    def test_health_checks_contain_expected_keys(self, client):
        response = client.get("/health")
        checks = response.json()["checks"]
        assert "api" in checks
        assert "database" in checks
        assert "mcp" in checks
        assert "rag" in checks

    def test_readiness_returns_200(self, client):
        response = client.get("/ready")
        assert response.status_code == 200
        assert response.json()["status"] == "ready"


@pytest.mark.unit
class TestIncidentEndpoints:
    """Skeleton tests for incident endpoints."""

    def test_list_incidents_returns_200(self, client):
        response = client.get("/api/incidents")
        assert response.status_code == 200
        assert "incidents" in response.json()

    def test_get_incident_returns_200(self, client):
        response = client.get("/api/incidents/test-123")
        assert response.status_code == 200


@pytest.mark.unit
class TestInvestigationEndpoints:
    """Skeleton tests for investigation endpoints."""

    def test_create_investigation_returns_200(self, client):
        response = client.post("/api/investigations")
        assert response.status_code == 200

    def test_get_investigation_returns_200(self, client):
        response = client.get("/api/investigations/test-456")
        assert response.status_code == 200


@pytest.mark.unit
class TestChatEndpoint:
    """Skeleton test for chat endpoint."""

    def test_chat_returns_200(self, client):
        response = client.post("/api/chat")
        assert response.status_code == 200
