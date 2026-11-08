"""Unit tests for the incident-lab proxy (workloads stubbed with httpx.MockTransport)."""

from __future__ import annotations

import json
from collections.abc import AsyncGenerator

import httpx
import pytest
from httpx import ASGITransport, AsyncClient

from app.config import get_settings
from app.main import create_app
from app.routes import lab


class Workloads:
    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.modes = {"checkout.test": "none", "payments.test": "none"}
        self.down: set[str] = set()

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        host = request.url.host
        if host in self.down:
            raise httpx.ConnectError("refused")
        if request.method == "POST":
            self.modes[host] = json.loads(request.content)["mode"]
        return httpx.Response(200, json={"service": host, "mode": self.modes[host]})


@pytest.fixture
def workloads() -> Workloads:
    return Workloads()


@pytest.fixture
async def client(workloads, monkeypatch) -> AsyncGenerator[AsyncClient, None]:
    settings = get_settings()
    monkeypatch.setattr(settings, "enable_incident_lab", True)
    monkeypatch.setattr(
        settings,
        "lab_targets",
        {"checkout": "http://checkout.test", "payments": "http://payments.test"},
    )
    monkeypatch.setattr(settings, "failure_admin_token", None)
    app = create_app()

    async def _http():
        async with httpx.AsyncClient(transport=httpx.MockTransport(workloads)) as c:
            yield c

    app.dependency_overrides[lab.get_lab_http] = _http
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


async def test_status_lists_demo_services_and_modes(client, workloads):
    workloads.down.add("payments.test")
    body = (await client.get("/api/lab")).json()
    assert body["enabled"] is True
    assert {s["name"]: (s["mode"], s["reachable"]) for s in body["services"]} == {
        "checkout": ("none", True),
        "payments": (None, False),
    }


async def test_set_failure_forwards_to_the_workload(client, workloads, monkeypatch):
    from pydantic import SecretStr

    monkeypatch.setattr(get_settings(), "failure_admin_token", SecretStr("lab-token"))
    response = await client.post("/api/lab/failure", json={"service": "checkout", "mode": "db"})
    assert response.status_code == 200
    assert response.json() == {"name": "checkout", "mode": "db", "reachable": True}
    sent = workloads.requests[-1]
    assert str(sent.url) == "http://checkout.test/admin/failure"
    assert sent.headers["x-admin-token"] == "lab-token"


async def test_only_allow_listed_services_can_be_targeted(client, workloads):
    response = await client.post("/api/lab/failure", json={"service": "my-shop", "mode": "errors"})
    assert response.status_code == 404
    assert workloads.requests == []


async def test_invalid_mode_rejected(client):
    response = await client.post(
        "/api/lab/failure", json={"service": "checkout", "mode": "meltdown"}
    )
    assert response.status_code == 422


async def test_unreachable_target_is_502(client, workloads):
    workloads.down.add("checkout.test")
    response = await client.post("/api/lab/failure", json={"service": "checkout", "mode": "db"})
    assert response.status_code == 502
    assert response.json()["error"]["code"] == "LAB_TARGET_UNAVAILABLE"


async def test_traffic_runs_in_background(client, monkeypatch):
    sent = []

    async def fake_send(url, count):
        sent.append((url, count))

    monkeypatch.setattr(lab, "send_traffic", fake_send)
    response = await client.post("/api/lab/traffic", json={"requests": 20})
    assert response.status_code == 202
    assert response.json() == {"target": "checkout", "requests": 20}
    assert sent == [("http://checkout.test", 20)]
    assert (await client.post("/api/lab/traffic", json={"requests": 1000})).status_code == 422


async def test_lab_disabled_by_default(monkeypatch):
    monkeypatch.setattr(get_settings(), "enable_incident_lab", False)
    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        assert (await client.get("/api/lab")).json() == {"enabled": False, "services": []}
        response = await client.post("/api/lab/failure", json={"service": "checkout", "mode": "db"})
        assert response.status_code == 403
        assert response.json()["error"]["code"] == "LAB_DISABLED"
