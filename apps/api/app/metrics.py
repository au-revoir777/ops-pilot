"""Prometheus metrics for the OpsPilot API.

Label values are always bounded (DECISIONS D-007 / D-022): routes are route
templates, statuses are enum values, and nothing carries IDs, user input or
free text. Agent-side metrics are declared here as a contract so dashboards and
alerts exist before Phases 5-6 start emitting them.
"""

from __future__ import annotations

import re
import time
from typing import Any

from prometheus_client import Counter, Gauge, Histogram
from starlette.routing import compile_path
from starlette.types import ASGIApp, Message, Receive, Scope, Send

SERVICE = "opspilot-api"
_UNINSTRUMENTED_PATHS = frozenset({"/metrics", "/health", "/ready"})
LATENCY_BUCKETS = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0)
LONG_BUCKETS = (0.5, 1, 2.5, 5, 10, 20, 30, 60, 120, 300)

# --- HTTP (same names and labels as the demo workloads, so one dashboard fits all)
HTTP_REQUESTS = Counter(
    "http_requests_total", "HTTP requests handled", ["service", "method", "route", "status"]
)
HTTP_LATENCY = Histogram(
    "http_request_duration_seconds",
    "HTTP request latency",
    ["service", "method", "route"],
    buckets=LATENCY_BUCKETS,
)
HTTP_ERRORS = Counter(
    "http_request_errors_total", "HTTP requests that ended in a 5xx", ["service", "route"]
)
HTTP_IN_PROGRESS = Gauge(
    "http_requests_in_progress", "HTTP requests currently being handled", ["service"]
)
APP_INFO = Gauge("app_info", "Build information (value is always 1)", ["service", "version"])

# --- Domain
INCIDENTS_CREATED = Counter("opspilot_incidents_created_total", "Incidents created", ["severity"])
INCIDENT_STATUS_CHANGES = Counter(
    "opspilot_incident_transitions_total", "Incident status changes", ["from_status", "to_status"]
)
INVESTIGATIONS_CREATED = Counter("opspilot_investigations_created_total", "Investigations opened")
INVESTIGATIONS_FINISHED = Counter(
    "opspilot_investigations_finished_total",
    "Investigations that reached a terminal state",
    ["outcome"],
)
INVESTIGATION_DURATION = Histogram(
    "opspilot_investigation_duration_seconds",
    "Time from investigation start (running) to a terminal state",
    ["outcome"],
    buckets=LONG_BUCKETS,
)
DB_ERRORS = Counter("opspilot_db_errors_total", "Failed database transactions", ["operation"])

# --- Agent / RAG / MCP contract (emitted from Phases 4-6)
TOOL_CALLS = Counter("opspilot_tool_calls_total", "MCP tool calls", ["tool", "outcome"])
TOOL_CALL_DURATION = Histogram(
    "opspilot_tool_call_duration_seconds", "MCP tool call latency", ["tool"],
    buckets=LATENCY_BUCKETS,
)  # fmt: skip
RAG_RETRIEVAL_DURATION = Histogram(
    "opspilot_rag_retrieval_duration_seconds", "RAG retrieval latency", buckets=LATENCY_BUCKETS
)
RAG_RETRIEVALS = Counter(
    "opspilot_rag_retrievals_total", "RAG retrievals by outcome (hit, empty, error)", ["outcome"]
)
RAG_DOCUMENTS_INGESTED = Counter(
    "opspilot_rag_documents_ingested_total",
    "Knowledge-base documents processed by ingestion",
    ["outcome"],
)
AGENT_EXECUTION_DURATION = Histogram(
    "opspilot_agent_execution_duration_seconds",
    "End-to-end agent run latency",
    ["outcome"],
    buckets=LONG_BUCKETS,
)
LLM_ERRORS = Counter("opspilot_llm_errors_total", "Failed LLM calls", ["error_type"])
LLM_TOKENS = Counter("opspilot_llm_tokens_total", "LLM tokens used", ["kind"])


def set_build_info(version: str) -> None:
    APP_INFO.labels(service=SERVICE, version=version).set(1)


RouteIndex = list[tuple["re.Pattern[str]", str, frozenset[str]]]


def index_routes(app: Any, routers: list[tuple[Any, str]]) -> None:
    """Record every route's full template (prefix included) on the app.

    Built from our own routers at startup instead of read back from
    ``scope["route"]`` or FastAPI's internal route tree: both changed between
    FastAPI versions (0.162 nests included routers and puts the un-prefixed
    route in the scope), which silently changed the labels.
    """
    index: RouteIndex = []
    for router, prefix in routers:
        for route in router.routes:
            path = getattr(route, "path", None)
            if path is None:
                continue
            regex, template, _ = compile_path(prefix + path)
            index.append((regex, template, frozenset(getattr(route, "methods", None) or ())))
    app.state.route_index = index


def route_template(scope: Scope) -> str:
    """The matched route's full template (``/api/incidents/{incident_id}``)."""
    app = scope.get("app")
    index: RouteIndex = getattr(getattr(app, "state", None), "route_index", None) or []
    path, method = scope["path"], scope.get("method", "")
    partial = None
    for regex, template, methods in index:
        if regex.match(path):
            if not methods or method in methods:
                return template
            partial = partial or template  # right path, wrong method (405)
    return partial or "unmatched"


class MetricsMiddleware:
    """RED metrics per route template. Probes and /metrics are not counted."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["path"] in _UNINSTRUMENTED_PATHS:
            await self.app(scope, receive, send)
            return

        status_code = 500

        async def send_wrapper(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
            await send(message)

        HTTP_IN_PROGRESS.labels(service=SERVICE).inc()
        start = time.perf_counter()
        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            elapsed = time.perf_counter() - start
            HTTP_IN_PROGRESS.labels(service=SERVICE).dec()
            route = route_template(scope)
            method = scope["method"]
            HTTP_REQUESTS.labels(
                service=SERVICE, method=method, route=route, status=str(status_code)
            ).inc()
            HTTP_LATENCY.labels(service=SERVICE, method=method, route=route).observe(elapsed)
            if status_code >= 500:
                HTTP_ERRORS.labels(service=SERVICE, route=route).inc()
