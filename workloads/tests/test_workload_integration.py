"""Integration tests: users, payments and checkout running as real HTTP servers.

Each service runs in its own uvicorn server (own thread and event loop) on a
free localhost port, and checkout reaches the others over real TCP, the same
way it does in Docker Compose.
"""

from __future__ import annotations

import socket
import statistics
import threading
import time
from collections.abc import Iterator
from dataclasses import dataclass

import httpx
import pytest
import uvicorn

from opsdemo import checkout, payments, users
from workload_testing import make_settings

pytestmark = pytest.mark.integration

CART = {"user_id": "u-7", "items": [{"sku": "sku-9", "quantity": 1, "unit_price_cents": 4999}]}


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@dataclass
class RunningService:
    url: str
    server: uvicorn.Server
    thread: threading.Thread


def start(app, port: int) -> RunningService:
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning", lifespan="on")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not server.started:
        if time.monotonic() > deadline:
            raise RuntimeError(f"service on port {port} did not start")
        time.sleep(0.05)
    return RunningService(f"http://127.0.0.1:{port}", server, thread)


@pytest.fixture(scope="module")
def services() -> Iterator[dict[str, RunningService]]:
    ports = {name: free_port() for name in ("users", "payments", "checkout")}
    common = {"enable_failure_injection": True, "failure_error_rate": 1.0}
    running = {
        "users": start(
            users.create_app(make_settings(service_name="users", **common)), ports["users"]
        ),
        "payments": start(
            payments.create_app(make_settings(service_name="payments", **common)), ports["payments"]
        ),
    }
    running["checkout"] = start(
        checkout.create_app(
            make_settings(
                service_name="checkout",
                users_url=running["users"].url,
                payments_url=running["payments"].url,
                failure_db_latency_ms=600,
                **common,
            )
        ),
        ports["checkout"],
    )
    yield running
    for service in running.values():
        service.server.should_exit = True
    for service in running.values():
        service.thread.join(timeout=10)


@pytest.fixture
def http() -> Iterator[httpx.Client]:
    with httpx.Client(timeout=10) as client:
        yield client


@pytest.fixture(autouse=True)
def reset_failure_modes(services, http) -> Iterator[None]:
    yield
    for service in services.values():
        http.post(f"{service.url}/admin/failure", json={"mode": "none"})


def metric_value(http: httpx.Client, url: str, prefix: str) -> float:
    for line in http.get(f"{url}/metrics").text.splitlines():
        if line.startswith(prefix):
            return float(line.rsplit(" ", 1)[1])
    return 0.0


@pytest.mark.parametrize("name", ["users", "payments", "checkout"])
def test_health_over_http(services, http, name):
    response = http.get(f"{services[name].url}/health")
    assert response.status_code == 200
    assert response.json()["service"] == name


def test_checkout_calls_users_and_payments_over_http(services, http):
    payments_url = services["payments"].url
    captured = (
        'http_requests_total{method="POST",route="/payments",service="payments",status="201"}'
    )
    lookups = (
        'http_requests_total{method="GET",route="/users/{user_id}",service="users",status="200"}'
    )
    payments_before = metric_value(http, payments_url, captured)
    users_before = metric_value(http, services["users"].url, lookups)

    response = http.post(f"{services['checkout'].url}/checkout", json=CART)

    assert response.status_code == 201, response.text
    assert response.json()["amount_cents"] == 4999
    assert response.json()["payment_id"].startswith("pay_")
    assert metric_value(http, payments_url, captured) == payments_before + 1
    assert metric_value(http, services["users"].url, lookups) == users_before + 1


def test_unknown_user_is_rejected_without_charging(services, http):
    charged = 'http_requests_total{method="POST",route="/payments",service="payments",status="201"}'
    before = metric_value(http, services["payments"].url, charged)
    response = http.post(
        f"{services['checkout'].url}/checkout", json={**CART, "user_id": "u-99999"}
    )
    assert response.status_code == 422
    assert metric_value(http, services["payments"].url, charged) == before


def test_baseline_latency_matches_demo_scenario(services, http):
    timings = []
    for _ in range(20):
        start = time.perf_counter()
        assert http.post(f"{services['checkout'].url}/checkout", json=CART).status_code == 201
        timings.append(time.perf_counter() - start)
    p95 = statistics.quantiles(timings, n=20)[-1]
    assert p95 < 0.4  # demo baseline is ~200 ms p95


def test_db_incident_is_visible_in_latency_and_metrics(services, http):
    url = services["checkout"].url
    switched = http.post(f"{url}/admin/failure", json={"mode": "db"})
    assert switched.json()["mode"] == "db"

    start = time.perf_counter()
    assert http.post(f"{url}/checkout", json=CART).status_code == 201
    assert time.perf_counter() - start >= 0.45

    metrics = http.get(f"{url}/metrics").text
    slow_bucket = (
        "db_query_duration_seconds_bucket"
        '{le="0.3",operation="select_cart_items",service="checkout"}'
    )
    total = 'db_query_duration_seconds_count{operation="select_cart_items",service="checkout"}'
    values = {
        line.rsplit(" ", 1)[0]: float(line.rsplit(" ", 1)[1])
        for line in metrics.splitlines()
        if line.startswith("db_query_duration_seconds")
    }
    assert values[total] > values[slow_bucket]  # at least one query slower than 300 ms


def test_payments_outage_cascades_as_502_from_checkout(services, http):
    http.post(f"{services['payments'].url}/admin/failure", json={"mode": "errors"})
    response = http.post(f"{services['checkout'].url}/checkout", json=CART)
    assert response.status_code == 502
    assert response.json()["error"]["code"] == "DEPENDENCY_ERROR"
    errors = 'http_request_errors_total{route="/checkout",service="checkout"}'
    assert metric_value(http, services["checkout"].url, errors) >= 1


def test_request_id_is_echoed_end_to_end(services, http):
    response = http.post(
        f"{services['checkout'].url}/checkout", json=CART, headers={"X-Request-ID": "demo-trace-1"}
    )
    assert response.headers["x-request-id"] == "demo-trace-1"
