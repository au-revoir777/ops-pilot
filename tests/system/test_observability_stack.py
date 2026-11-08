"""System tests for the running observability stack (marker: system).

Needs the Compose stack with failure injection enabled:

    ENABLE_FAILURE_INJECTION=true docker compose up -d --build \
        postgres migrate api checkout payments users prometheus loki alloy grafana
    pytest -m system

URLs default to the standard local ports; override with PROMETHEUS_URL,
LOKI_URL, GRAFANA_URL, CHECKOUT_URL, API_URL (and GRAFANA_ADMIN_*).
"""

from __future__ import annotations

import os
import time
import uuid
from collections.abc import Callable, Iterator

import httpx
import pytest

pytestmark = pytest.mark.system

PROMETHEUS = os.environ.get("PROMETHEUS_URL", "http://127.0.0.1:9090")
LOKI = os.environ.get("LOKI_URL", "http://127.0.0.1:3100")
GRAFANA = os.environ.get("GRAFANA_URL", "http://127.0.0.1:3000")
CHECKOUT = os.environ.get("CHECKOUT_URL", "http://127.0.0.1:8080")
API = os.environ.get("API_URL", "http://127.0.0.1:8000")
GRAFANA_AUTH = (
    os.environ.get("GRAFANA_ADMIN_USER", "admin"),
    os.environ.get("GRAFANA_ADMIN_PASSWORD", "admin"),
)
CART = {"user_id": "u-7", "items": [{"sku": "sku-1", "quantity": 1, "unit_price_cents": 999}]}
SCRAPE_WAIT = 25  # > scrape interval + rate window granularity
SLOW_REQUEST_LOGS = (
    'sum(count_over_time({service="checkout", level="warning"} |= "request_slow" [5m]))'
)


@pytest.fixture(scope="module")
def http() -> Iterator[httpx.Client]:
    with httpx.Client(timeout=30) as client:
        yield client


def prom_query(http: httpx.Client, query: str) -> list[dict]:
    response = http.get(f"{PROMETHEUS}/api/v1/query", params={"query": query})
    response.raise_for_status()
    return response.json()["data"]["result"]


def eventually(check: Callable[[], bool], timeout: float = 60, interval: float = 3) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if check():
            return True
        time.sleep(interval)
    return False


def send_checkouts(http: httpx.Client, count: int, request_id: str | None = None) -> None:
    headers = {"X-Request-ID": request_id} if request_id else {}
    for _ in range(count):
        assert http.post(f"{CHECKOUT}/checkout", json=CART, headers=headers).status_code == 201


def test_all_application_targets_are_up(http):
    response = http.get(f"{PROMETHEUS}/api/v1/targets", params={"state": "active"})
    targets = response.json()["data"]["activeTargets"]
    by_instance = {t["labels"]["instance"]: t["health"] for t in targets}
    for instance in ("api:8000", "checkout:8080", "payments:8081", "users:8082", "loki:3100"):
        assert by_instance.get(instance) == "up", (instance, by_instance)


def test_recording_and_alerting_rules_loaded(http):
    groups = http.get(f"{PROMETHEUS}/api/v1/rules").json()["data"]["groups"]
    names = {rule["name"] for group in groups for rule in group["rules"]}
    assert {"service:http_latency_seconds:p95_1m", "HighLatencyP95", "TargetDown"} <= names
    assert all(group["rules"][0]["health"] in {"ok", "unknown"} for group in groups)


def test_version_is_queryable_for_correlation(http):
    versions = {
        r["metric"]["service"]: r["metric"]["version"] for r in prom_query(http, "app_info")
    }
    assert {"checkout", "payments", "users", "opspilot-api"} <= set(versions)


def test_grafana_datasources_and_dashboard(http):
    for uid in ("prometheus", "loki"):
        health = http.get(f"{GRAFANA}/api/datasources/uid/{uid}/health", auth=GRAFANA_AUTH)
        assert health.json()["status"] == "OK", (uid, health.text)
    dashboard = http.get(f"{GRAFANA}/api/dashboards/uid/opspilot-services", auth=GRAFANA_AUTH)
    assert dashboard.status_code == 200
    assert dashboard.json()["dashboard"]["title"] == "OpsPilot — Services"


def test_request_can_be_traced_across_services_in_loki(http):
    request_id = f"sys-{uuid.uuid4().hex[:12]}"
    send_checkouts(http, 1, request_id=request_id)

    def services_seen() -> set[str]:
        response = http.get(
            f"{LOKI}/loki/api/v1/query_range",
            params={
                "query": f'{{service=~"checkout|users|payments"}} | request_id="{request_id}"',
                "limit": 50,
                "since": "5m",
            },
        )
        return {stream["stream"]["service"] for stream in response.json()["data"]["result"]}

    assert eventually(lambda: services_seen() == {"checkout", "users", "payments"}), services_seen()


def test_api_logs_and_metrics_carry_service_context(http):
    assert http.post(f"{API}/api/incidents", json={"title": "system test"}).status_code == 201

    def api_logs_present() -> bool:
        response = http.get(
            f"{LOKI}/loki/api/v1/query_range",
            params={
                "query": '{service="opspilot-api", version="0.1.0"}',
                "limit": 5,
                "since": "5m",
            },
        )
        return bool(response.json()["data"]["result"])

    assert eventually(api_logs_present)
    assert eventually(
        lambda: bool(prom_query(http, "opspilot_incidents_created_total > 0")), timeout=40
    )


def test_injected_latency_is_visible_in_metrics_and_logs(http):
    """The Phase 3 acceptance check: inject latency, telemetry must change."""
    p95 = 'service:http_latency_seconds:p95_1m{service="checkout"}'

    def checkout_p95() -> float:
        result = prom_query(http, p95)
        return float(result[0]["value"][1]) if result else float("nan")

    switch = http.post(f"{CHECKOUT}/admin/failure", json={"mode": "none"})
    assert switch.status_code == 200, "run the stack with ENABLE_FAILURE_INJECTION=true"

    # Wait for a clean baseline: an earlier test may have left slow requests in
    # the 1-minute rate window. Keep traffic flowing so the window refills.
    def baseline_is_normal() -> bool:
        send_checkouts(http, 10)
        value = checkout_p95()
        return value == value and value < 1.0  # not NaN, and back to normal

    assert eventually(baseline_is_normal, timeout=120, interval=SCRAPE_WAIT), checkout_p95()
    baseline = checkout_p95()

    try:
        http.post(f"{CHECKOUT}/admin/failure", json={"mode": "latency"})
        send_checkouts(http, 15)
        # Injected latency is ~2 s; p95 must rise well above whatever baseline we had.
        assert eventually(lambda: checkout_p95() > max(1.5, baseline + 1.0), timeout=60), (
            baseline,
            checkout_p95(),
        )
        slow_logs = http.get(
            f"{LOKI}/loki/api/v1/query",
            params={"query": SLOW_REQUEST_LOGS},
        ).json()["data"]["result"]
        assert slow_logs and float(slow_logs[0]["value"][1]) >= 1
    finally:
        http.post(f"{CHECKOUT}/admin/failure", json={"mode": "none"})
