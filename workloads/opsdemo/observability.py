"""Structured logging, Prometheus metrics and request-ID propagation.

Metric labels are bounded on purpose (DECISIONS D-007): ``route`` is the route
*template* (``/users/{user_id}``), never the raw path, and unmatched paths
collapse into a single ``unmatched`` value.
"""

from __future__ import annotations

import logging
import re
import time
import uuid

import structlog
from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram
from starlette.types import ASGIApp, Message, Receive, Scope, Send

REQUEST_ID_HEADER = "X-Request-ID"
_VALID_REQUEST_ID = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
# Never record scrape / probe traffic as business requests.
_UNINSTRUMENTED_PATHS = frozenset({"/metrics", "/health"})

LATENCY_BUCKETS = (0.025, 0.05, 0.1, 0.2, 0.3, 0.5, 0.75, 1.0, 1.5, 2.0, 3.0, 5.0, 10.0)


def configure_logging(service: str, version: str, level: str) -> None:
    """JSON logs on stdout with service/version on every line (Loki-friendly)."""

    def add_service(_logger, _method, event_dict):
        event_dict.setdefault("service", service)
        event_dict.setdefault("version", version)
        return event_dict

    logging.basicConfig(format="%(message)s", level=getattr(logging, level.upper(), logging.INFO))
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.stdlib.add_log_level,
            add_service,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, level.upper(), logging.INFO)
        ),
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=False,
    )


class WorkloadMetrics:
    """Per-app registry so several apps can coexist (tests) without collisions."""

    def __init__(self, service: str, version: str) -> None:
        self.service = service
        self.registry = CollectorRegistry()
        self.requests = Counter(
            "http_requests_total",
            "HTTP requests handled",
            ["service", "method", "route", "status"],
            registry=self.registry,
        )
        self.latency = Histogram(
            "http_request_duration_seconds",
            "HTTP request latency",
            ["service", "method", "route"],
            buckets=LATENCY_BUCKETS,
            registry=self.registry,
        )
        self.errors = Counter(
            "http_request_errors_total",
            "HTTP requests that ended in a 5xx response",
            ["service", "route"],
            registry=self.registry,
        )
        self.in_progress = Gauge(
            "http_requests_in_progress",
            "HTTP requests currently being handled",
            ["service"],
            registry=self.registry,
        )
        self.db_latency = Histogram(
            "db_query_duration_seconds",
            "Simulated database query latency",
            ["service", "operation"],
            buckets=LATENCY_BUCKETS,
            registry=self.registry,
        )
        self.downstream_latency = Histogram(
            "downstream_request_duration_seconds",
            "Latency of calls to other services",
            ["service", "target", "outcome"],
            buckets=LATENCY_BUCKETS,
            registry=self.registry,
        )
        info = Gauge(
            "app_info",
            "Static build information (value is always 1)",
            ["service", "version"],
            registry=self.registry,
        )
        info.labels(service=service, version=version).set(1)


def current_request_id() -> str | None:
    return structlog.contextvars.get_contextvars().get("request_id")


class RequestContextMiddleware:
    """Request IDs, access logs and RED metrics for every HTTP request."""

    def __init__(self, app: ASGIApp, metrics: WorkloadMetrics, slow_request_ms: int) -> None:
        self.app = app
        self.metrics = metrics
        self.slow_request_ms = slow_request_ms
        self.logger = structlog.get_logger("access")

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        incoming = dict(scope["headers"]).get(REQUEST_ID_HEADER.lower().encode(), b"").decode()
        request_id = incoming if _VALID_REQUEST_ID.match(incoming) else uuid.uuid4().hex
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(request_id=request_id)

        status_code = 500

        async def send_wrapper(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
                message.setdefault("headers", []).append(
                    (REQUEST_ID_HEADER.lower().encode(), request_id.encode())
                )
            await send(message)

        instrumented = scope["path"] not in _UNINSTRUMENTED_PATHS
        service = self.metrics.service
        if instrumented:
            self.metrics.in_progress.labels(service=service).inc()
        start = time.perf_counter()
        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            elapsed = time.perf_counter() - start
            if instrumented:
                self.metrics.in_progress.labels(service=service).dec()
                self._record(scope, status_code, elapsed)

    def _record(self, scope: Scope, status_code: int, elapsed: float) -> None:
        route_obj = scope.get("route")
        route = getattr(route_obj, "path", None) or "unmatched"
        method = scope["method"]
        service = self.metrics.service

        self.metrics.requests.labels(
            service=service, method=method, route=route, status=str(status_code)
        ).inc()
        self.metrics.latency.labels(service=service, method=method, route=route).observe(elapsed)
        if status_code >= 500:
            self.metrics.errors.labels(service=service, route=route).inc()

        latency_ms = round(elapsed * 1000, 1)
        fields = {"method": method, "route": route, "status": status_code, "latency_ms": latency_ms}
        if status_code >= 500:
            self.logger.error("request_completed", **fields)
        elif latency_ms >= self.slow_request_ms:
            self.logger.warning("request_slow", **fields)
        else:
            self.logger.info("request_completed", **fields)
