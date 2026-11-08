"""API integration tests: FastAPI app wired to the real PostgreSQL test database."""

from __future__ import annotations

import uuid

from httpx import AsyncClient


async def create_incident(client: AsyncClient, **overrides) -> dict:
    payload = {"title": "DB latency high", "severity": "SEV2", "service_name": "checkout"}
    payload.update(overrides)
    response = await client.post("/api/incidents", json=payload)
    assert response.status_code == 201, response.text
    return response.json()


async def test_readiness_with_real_database(client: AsyncClient):
    response = await client.get("/ready")
    assert response.status_code == 200
    assert response.json()["checks"]["database"] == "healthy"


async def test_create_and_get_incident(client: AsyncClient):
    created = await create_incident(client, description="P99 > 2s")
    assert created["status"] == "open"
    assert created["service_name"] == "checkout"
    assert created["resolved_at"] is None

    response = await client.get(f"/api/incidents/{created['id']}")
    assert response.status_code == 200
    assert response.json() == created


async def test_list_incidents_with_filter_and_pagination(client: AsyncClient):
    first = await create_incident(client, title="first")
    second = await create_incident(client, title="second", service_name="payments")
    await client.patch(f"/api/incidents/{second['id']}/status", json={"status": "resolved"})

    all_ids = {i["id"] for i in (await client.get("/api/incidents")).json()}
    assert {first["id"], second["id"]} <= all_ids

    resolved = (await client.get("/api/incidents", params={"status": "resolved"})).json()
    assert [i["id"] for i in resolved] == [second["id"]]

    assert len((await client.get("/api/incidents", params={"limit": 1})).json()) == 1
    assert (await client.get("/api/incidents", params={"limit": 0})).status_code == 422
    assert (await client.get("/api/incidents", params={"limit": 101})).status_code == 422


async def test_status_transitions(client: AsyncClient):
    incident = await create_incident(client)
    url = f"/api/incidents/{incident['id']}/status"

    resolved = await client.patch(url, json={"status": "resolved"})
    assert resolved.status_code == 200
    assert resolved.json()["resolved_at"] is not None

    closed = await client.patch(url, json={"status": "closed"})
    assert closed.status_code == 200

    reopen = await client.patch(url, json={"status": "open"})
    assert reopen.status_code == 409
    assert reopen.json()["error"]["code"] == "INVALID_INCIDENT_STATE"

    # The rejected transition was rolled back; the persisted state is unchanged.
    assert (await client.get(f"/api/incidents/{incident['id']}")).json()["status"] == "closed"


async def test_create_and_get_investigation(client: AsyncClient):
    incident = await create_incident(client)

    response = await client.post("/api/investigations", json={"incident_id": incident["id"]})
    assert response.status_code == 201
    investigation = response.json()
    # The agent ran (simulated tools) and its result was persisted.
    assert investigation["status"] == "completed"
    assert investigation["incident_id"] == incident["id"]
    assert investigation["query"] == "DB latency high"  # from the incident title
    assert investigation["events"][0]["message"] == "Investigation created"

    fetched = await client.get(f"/api/investigations/{investigation['id']}")
    assert fetched.status_code == 200
    assert fetched.json() == investigation

    # Opening an investigation moved the incident to "investigating" in the same transaction.
    incident_now = (await client.get(f"/api/incidents/{incident['id']}")).json()
    assert incident_now["status"] == "investigating"

    listed = await client.get(f"/api/incidents/{incident['id']}/investigations")
    assert [i["id"] for i in listed.json()] == [investigation["id"]]


async def test_cannot_investigate_closed_incident(client: AsyncClient):
    incident = await create_incident(client)
    url = f"/api/incidents/{incident['id']}/status"
    await client.patch(url, json={"status": "resolved"})
    await client.patch(url, json={"status": "closed"})

    response = await client.post("/api/investigations", json={"incident_id": incident["id"]})
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "INVALID_INCIDENT_STATE"


async def test_not_found_responses(client: AsyncClient):
    missing = str(uuid.uuid4())
    for method, url, body in [
        ("GET", f"/api/incidents/{missing}", None),
        ("PATCH", f"/api/incidents/{missing}/status", {"status": "resolved"}),
        ("GET", f"/api/investigations/{missing}", None),
        ("GET", f"/api/incidents/{missing}/investigations", None),
        ("POST", "/api/investigations", {"incident_id": missing}),
    ]:
        response = await client.request(method, url, json=body)
        assert response.status_code == 404, (method, url)
        assert response.json()["error"]["code"].endswith("NOT_FOUND")


async def test_invalid_requests(client: AsyncClient):
    assert (await client.get("/api/incidents/not-a-uuid")).status_code == 422
    assert (await client.post("/api/incidents", json={"title": ""})).status_code == 422
    assert (
        await client.post("/api/incidents", json={"title": "x", "severity": "SEV9"})
    ).status_code == 422
    bad_service = await client.post(
        "/api/incidents", json={"title": "x", "service_name": "Bad Name;"}
    )
    assert bad_service.status_code == 422
    assert (
        await client.post("/api/investigations", json={"incident_id": "nope"})
    ).status_code == 422


async def test_sql_injection_attempt_is_inert(client: AsyncClient):
    title = "x'); DROP TABLE incidents; --"
    created = await create_incident(client, title=title)
    assert (await client.get(f"/api/incidents/{created['id']}")).json()["title"] == title
    assert (await client.get("/api/incidents")).status_code == 200
