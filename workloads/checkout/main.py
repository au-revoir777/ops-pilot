"""Checkout microservice — demo workload.

Exposes /health, /metrics, and /checkout business endpoint.
Supports controlled failure injection via FAILURE_MODE env var.
"""

from __future__ import annotations

import asyncio
import logging
import os
import random
import time
from datetime import UTC, datetime

from fastapi import FastAPI, Response
from prometheus_client import Counter, Histogram, generate_latest

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
SERVICE_NAME = os.getenv("SERVICE_NAME", "checkout")
PORT = int(os.getenv("PORT", "8080"))
FAILURE_MODE = os.getenv("FAILURE_MODE", "none")
ENABLE_FAILURE_INJECTION = os.getenv("ENABLE_FAILURE_INJECTION", "false").lower() in (
    "true", "1", "yes"
)
VERSION = os.getenv("SERVICE_VERSION", "1.8.2")

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(SERVICE_NAME)

# ---------------------------------------------------------------------------
# Prometheus metrics
# ---------------------------------------------------------------------------
REQUEST_COUNT = Counter(
    "http_requests_total",
    "Total HTTP requests",
    ["service", "method", "endpoint", "status"],
)
REQUEST_LATENCY = Histogram(
    "http_request_duration_seconds",
    "HTTP request latency",
    ["service", "method", "endpoint"],
    buckets=[0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.0, 5.0, 10.0],
)
ERROR_COUNT = Counter(
    "http_errors_total",
    "Total HTTP errors",
    ["service", "error_type"],
)

# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------
app = FastAPI(title=f"OpsPilot Workload — {SERVICE_NAME}", version=VERSION)


@app.get("/health")
async def health() -> dict:
    """Service health check."""
    return {
        "status": "healthy",
        "service": SERVICE_NAME,
        "version": VERSION,
        "failure_mode": FAILURE_MODE,
        "failure_injection_enabled": ENABLE_FAILURE_INJECTION,
        "timestamp": datetime.now(UTC).isoformat(),
    }


@app.get("/metrics")
async def metrics() -> Response:
    """Prometheus-compatible metrics endpoint."""
    return Response(content=generate_latest(), media_type="text/plain")


@app.post("/checkout")
async def checkout() -> dict:
    """Simulated checkout endpoint with failure injection."""
    start = time.monotonic()
    endpoint = "/checkout"

    try:
        # ----- Failure injection -----
        if ENABLE_FAILURE_INJECTION:
            if FAILURE_MODE == "latency":
                delay = random.uniform(1.5, 3.0)  # noqa: S311
            await asyncio.sleep(delay)
            logger.warning(
                '{"level":"WARN","service":"%s","message":"slow_query_detected",'
                '"query_time_ms":%.0f,"version":"%s","timestamp":"%s"}',
                SERVICE_NAME,
                delay * 1000,
                VERSION,
                datetime.now(UTC).isoformat(),
            )

        elif ENABLE_FAILURE_INJECTION and FAILURE_MODE == "errors":
            if random.random() < 0.5:  # noqa: S311
                ERROR_COUNT.labels(service=SERVICE_NAME, error_type="http_500").inc()
                REQUEST_COUNT.labels(
                    service=SERVICE_NAME, method="POST", endpoint=endpoint, status="500"
                ).inc()
                return {"error": "Internal server error", "status": 500}

        elif ENABLE_FAILURE_INJECTION and FAILURE_MODE == "db":
            delay = random.uniform(2.0, 5.0)  # noqa: S311
            await asyncio.sleep(delay)
            logger.warning(
                '{"level":"WARN","service":"%s","message":"database_connection_slow",'
                '"latency_ms":%.0f,"version":"%s","timestamp":"%s"}',
                SERVICE_NAME,
                delay * 1000,
                VERSION,
                datetime.now(UTC).isoformat(),
            )

        # ----- Normal response -----
        latency = time.monotonic() - start
        REQUEST_LATENCY.labels(
            service=SERVICE_NAME, method="POST", endpoint=endpoint
        ).observe(latency)
        REQUEST_COUNT.labels(
            service=SERVICE_NAME, method="POST", endpoint=endpoint, status="200"
        ).inc()

        logger.info(
            '{"level":"INFO","service":"%s","message":"checkout_completed",'
            '"latency_ms":%.1f,"version":"%s","timestamp":"%s"}',
            SERVICE_NAME,
            latency * 1000,
            VERSION,
            datetime.now(UTC).isoformat(),
        )

        return {
            "status": "success",
            "order_id": f"ORD-{random.randint(10000, 99999)}",  # noqa: S311
            "latency_ms": round(latency * 1000, 1),
            "service": SERVICE_NAME,
            "version": VERSION,
        }

    except Exception as exc:
        ERROR_COUNT.labels(service=SERVICE_NAME, error_type="unhandled").inc()
        logger.error(
            '{"level":"ERROR","service":"%s","message":"checkout_failed",'
            '"error":"%s","timestamp":"%s"}',
            SERVICE_NAME,
            str(exc),
            datetime.now(UTC).isoformat(),
        )
        return {"error": str(exc), "status": 500}


@app.post("/admin/failure")
async def set_failure_mode(body: dict, response: Response) -> dict:
    """Runtime failure injection control."""
    global FAILURE_MODE

    if not ENABLE_FAILURE_INJECTION:
        response.status_code = 403
        return {"error": "Failure injection is disabled in this environment"}

    mode = body.get("mode", "none")
    if mode not in ("none", "latency", "errors", "db"):
        response.status_code = 400
        return {"error": f"Unknown failure mode: {mode}"}

    FAILURE_MODE = mode
    logger.info(
        '{"level":"INFO","service":"%s","message":"failure_mode_changed",'
        '"mode":"%s","timestamp":"%s"}',
        SERVICE_NAME,
        mode,
        datetime.now(UTC).isoformat(),
    )
    return {"status": "ok", "failure_mode": FAILURE_MODE}
