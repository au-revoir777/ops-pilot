"""Unit tests for workload HTTP behaviour; downstream services are stubbed."""

from __future__ import annotations

import json
import time
from collections.abc import AsyncIterator

import httpx
import pytest

from opsdemo import checkout, payments, users
from workload_testing import make_settings, open_client

pytestmark = pytest.mark.unit

CART = {"user_id": "u-42", "items": [{"sku": "sku-1", "quantity": 2, "unit_price_cents": 1500}]}


class StubDownstream:
    """httpx transport that plays the users and payments services."""

    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.users_status = 200
        self.payments_status = 201
        self.fail_with: Exception | None = None

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.fail_with is not None:
            raise self.fail_with
        if request.url.host == "users.test":
            return httpx.Response(self.users_status, json={"user_id": "u-42", "tier": "standard"})
        body = json.loads(request.content)
        return httpx.Response(
            self.payments_status,
            json={"payment_id": "pay_1", "order_id": body["order_id"], "status": "captured"},
        )


@pytest.fixture
def downstream() -> StubDownstream:
    return StubDownstream()


async def client_for(module, downstream: StubDownstream | None = None, **overrides):
    transport = httpx.MockTransport(downstream) if downstream else None
    app = module.create_app(make_settings(**overrides), transport=transport)
    return app, open_client(app)


@pytest.fixture
async def checkout_client(downstream) -> AsyncIterator[httpx.AsyncClient]:
    _, gen = await client_for(checkout, downstream, service_name="checkout")
    async for client in gen:
        yield client


def metric_lines(text: str, name: str) -> list[str]:
    return [line for line in text.splitlines() if line.startswith(name)]


# ---------------------------------------------------------------------------
# Common endpoints
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("module", [checkout, payments, users])
async def test_health_is_liveness_only(module):
    _, gen = await client_for(
        module, enable_failure_injection=True, failure_mode="errors", failure_error_rate=1.0
    )
    async for client in gen:
        response = await client.get("/health")
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "healthy"
        assert body["version"] == "9.9.9"
        assert "failure_mode" not in body  # investigations must infer it from telemetry


@pytest.mark.parametrize("module", [checkout, payments, users])
async def test_metrics_endpoint_exposes_build_info(module):
    _, gen = await client_for(module)
    async for client in gen:
        response = await client.get("/metrics")
        assert response.status_code == 200
        assert 'app_info{service="test-service",version="9.9.9"} 1.0' in response.text


async def test_request_id_generated_or_reused():
    _, gen = await client_for(users)
    async for client in gen:
        assert len((await client.get("/users/u-1")).headers["x-request-id"]) == 32
        reused = await client.get("/users/u-1", headers={"X-Request-ID": "trace-123"})
        assert reused.headers["x-request-id"] == "trace-123"
        unsafe = await client.get("/users/u-1", headers={"X-Request-ID": "x\ny"})
        assert unsafe.headers["x-request-id"] != "x\ny"


async def test_metrics_use_route_templates_not_raw_paths():
    _, gen = await client_for(users)
    async for client in gen:
        for user_id in ("u-1", "u-2", "u-3", "nobody"):
            await client.get(f"/users/{user_id}")
        await client.get("/no/such/path/123")
        text = (await client.get("/metrics")).text

    requests = metric_lines(text, "http_requests_total{")
    assert any(
        'route="/users/{user_id}",service="test-service",status="200"} 3.0' in line
        for line in requests
    )
    assert any(
        'route="/users/{user_id}",service="test-service",status="404"} 1.0' in line
        for line in requests
    )
    assert any('route="unmatched"' in line for line in requests)
    assert not any("u-1" in line or "/no/such" in line for line in requests)
    assert not any('route="/metrics"' in line or 'route="/health"' in line for line in requests)


# ---------------------------------------------------------------------------
# Business endpoints
# ---------------------------------------------------------------------------


async def test_checkout_happy_path(checkout_client, downstream):
    response = await checkout_client.post("/checkout", json=CART, headers={"X-Request-ID": "r-1"})
    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "confirmed"
    assert body["amount_cents"] == 3000
    assert body["payment_id"] == "pay_1"

    users_call, payments_call = downstream.requests
    assert users_call.url == "http://users.test/users/u-42"
    assert json.loads(payments_call.content)["amount_cents"] == 3000
    # The request ID follows the request into every downstream call.
    assert {r.headers["x-request-id"] for r in downstream.requests} == {"r-1"}


async def test_checkout_normal_latency_is_well_under_injected_levels(checkout_client):
    start = time.perf_counter()
    for _ in range(5):
        assert (await checkout_client.post("/checkout", json=CART)).status_code == 201
    assert (time.perf_counter() - start) / 5 < 0.25


async def test_checkout_unknown_user(checkout_client, downstream):
    downstream.users_status = 404
    response = await checkout_client.post("/checkout", json=CART)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "UNKNOWN_USER"
    assert len(downstream.requests) == 1  # never charged


async def test_checkout_payment_declined(checkout_client, downstream):
    downstream.payments_status = 402
    response = await checkout_client.post("/checkout", json=CART)
    assert response.status_code == 402
    assert response.json()["error"]["code"] == "PAYMENT_DECLINED"


async def test_checkout_dependency_5xx_becomes_502(checkout_client, downstream):
    downstream.payments_status = 503
    response = await checkout_client.post("/checkout", json=CART)
    assert response.status_code == 502
    assert response.json()["error"]["code"] == "DEPENDENCY_ERROR"


@pytest.mark.parametrize(
    ("error", "status", "code"),
    [
        (httpx.ConnectError("refused"), 502, "DEPENDENCY_UNAVAILABLE"),
        (httpx.ReadTimeout("slow"), 504, "DEPENDENCY_TIMEOUT"),
    ],
)
async def test_checkout_dependency_transport_failures(
    checkout_client, downstream, error, status, code
):
    downstream.fail_with = error
    response = await checkout_client.post("/checkout", json=CART)
    assert response.status_code == status
    assert response.json()["error"]["code"] == code
    assert "refused" not in response.text and "slow" not in response.text


@pytest.mark.parametrize(
    "payload",
    [
        {"user_id": "u-1", "items": []},
        {"user_id": "u-1", "items": [{"sku": "a", "quantity": 0, "unit_price_cents": 1}]},
        {"user_id": "", "items": CART["items"]},
    ],
)
async def test_checkout_validation(checkout_client, payload):
    assert (await checkout_client.post("/checkout", json=payload)).status_code == 422


async def test_users_lookup():
    _, gen = await client_for(users)
    async for client in gen:
        assert (await client.get("/users/u-10")).json()["tier"] == "premium"
        assert (await client.get("/users/u-1001")).status_code == 404
        assert (await client.get("/users/admin")).status_code == 404


async def test_payments_capture_and_decline():
    _, gen = await client_for(payments)
    async for client in gen:
        ok = await client.post(
            "/payments", json={"order_id": "o1", "user_id": "u-1", "amount_cents": 500}
        )
        assert ok.status_code == 201
        assert ok.json()["status"] == "captured"
        declined = await client.post(
            "/payments", json={"order_id": "o2", "user_id": "u-1", "amount_cents": 2_000_000}
        )
        assert declined.status_code == 402


# ---------------------------------------------------------------------------
# Failure behaviour
# ---------------------------------------------------------------------------


async def test_errors_mode_returns_structured_500s_and_counts_them(downstream, capsys):
    _, gen = await client_for(
        checkout,
        downstream,
        service_name="checkout",
        enable_failure_injection=True,
        failure_mode="errors",
        failure_error_rate=1.0,
    )
    async for client in gen:
        response = await client.post("/checkout", json=CART)
        assert response.status_code == 500
        assert response.json()["error"]["code"] == "INTERNAL_ERROR"
        assert downstream.requests == []  # failed before doing any work
        text = (await client.get("/metrics")).text

    assert 'http_request_errors_total{route="/checkout",service="checkout"} 1.0' in text
    logs = [
        json.loads(line) for line in capsys.readouterr().out.splitlines() if line.startswith("{")
    ]
    failure = next(entry for entry in logs if entry["event"] == "request_processing_failed")
    assert failure["level"] == "error"
    assert failure["service"] == "checkout"
    assert failure["request_id"] == response.headers["x-request-id"]
    # Request-time logs look like a real outage; nothing mentions injection.
    request_logs = [entry for entry in logs if "request_id" in entry]
    assert "inject" not in json.dumps(request_logs).lower()


async def test_latency_mode_slows_requests_and_logs_slow_request(downstream, capsys):
    _, gen = await client_for(
        checkout, downstream, enable_failure_injection=True, failure_mode="latency"
    )
    async for client in gen:
        start = time.perf_counter()
        assert (await client.post("/checkout", json=CART)).status_code == 201
        assert time.perf_counter() - start >= 0.24
        health_start = time.perf_counter()
        await client.get("/health")
        assert time.perf_counter() - health_start < 0.1  # probes are never slowed

    events = [
        json.loads(line) for line in capsys.readouterr().out.splitlines() if line.startswith("{")
    ]
    slow = next(e for e in events if e["event"] == "request_slow")
    assert slow["route"] == "/checkout"
    assert slow["level"] == "warning"


async def test_db_mode_emits_slow_query_signals(downstream, capsys):
    _, gen = await client_for(
        checkout,
        downstream,
        service_name="checkout",
        enable_failure_injection=True,
        failure_mode="db",
    )
    async for client in gen:
        assert (await client.post("/checkout", json=CART)).status_code == 201
        text = (await client.get("/metrics")).text

    events = [
        json.loads(line) for line in capsys.readouterr().out.splitlines() if line.startswith("{")
    ]
    slow_queries = [e for e in events if e["event"] == "slow_query_detected"]
    assert {e["operation"] for e in slow_queries} >= {"select_cart_items"}
    assert all(e["query_time_ms"] >= 200 for e in slow_queries)
    # Every query landed above the 0.2 s bucket boundary.
    assert (
        "db_query_duration_seconds_bucket"
        '{le="0.2",operation="select_cart_items",service="checkout"} 0.0' in text
    )


async def test_failure_mode_configured_but_disabled_is_ignored(downstream):
    _, gen = await client_for(checkout, downstream, failure_mode="errors", failure_error_rate=1.0)
    async for client in gen:
        assert (await client.post("/checkout", json=CART)).status_code == 201


# ---------------------------------------------------------------------------
# Admin endpoint
# ---------------------------------------------------------------------------


async def test_admin_disabled_by_default():
    _, gen = await client_for(users)
    async for client in gen:
        response = await client.post("/admin/failure", json={"mode": "errors"})
        assert response.status_code == 403
        assert (await client.get("/admin/failure")).status_code == 403


async def test_admin_switches_mode_at_runtime():
    _, gen = await client_for(users, enable_failure_injection=True, failure_error_rate=1.0)
    async for client in gen:
        assert (await client.get("/users/u-1")).status_code == 200
        switched = await client.post("/admin/failure", json={"mode": "errors"})
        assert switched.json() == {"service": "test-service", "mode": "errors"}
        assert (await client.get("/admin/failure")).json()["mode"] == "errors"
        assert (await client.get("/users/u-1")).status_code == 500
        await client.post("/admin/failure", json={"mode": "none"})
        assert (await client.get("/users/u-1")).status_code == 200
        assert (await client.post("/admin/failure", json={"mode": "meltdown"})).status_code == 422


async def test_admin_token_enforced_when_configured():
    _, gen = await client_for(
        users, enable_failure_injection=True, failure_admin_token="s3cret-token"
    )
    async for client in gen:
        assert (await client.post("/admin/failure", json={"mode": "db"})).status_code == 401
        wrong = await client.post(
            "/admin/failure", json={"mode": "db"}, headers={"X-Admin-Token": "nope"}
        )
        assert wrong.status_code == 401
        ok = await client.post(
            "/admin/failure", json={"mode": "db"}, headers={"X-Admin-Token": "s3cret-token"}
        )
        assert ok.status_code == 200


async def test_admin_endpoint_hidden_from_openapi():
    _, gen = await client_for(users)
    async for client in gen:
        assert "/admin/failure" not in (await client.get("/openapi.json")).json()["paths"]
