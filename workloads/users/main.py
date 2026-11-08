"""Users microservice — demo workload."""

from __future__ import annotations

import os
import time
from datetime import UTC, datetime

from fastapi import FastAPI, Response
from prometheus_client import Counter, Histogram, generate_latest

SERVICE_NAME = os.getenv("SERVICE_NAME", "users")
PORT = int(os.getenv("PORT", "8082"))
VERSION = os.getenv("SERVICE_VERSION", "1.3.0")

REQUEST_COUNT = Counter(
    "http_requests_total",
    "Total HTTP requests",
    ["service", "method", "endpoint", "status"],
)
REQUEST_LATENCY = Histogram(
    "http_request_duration_seconds",
    "HTTP request latency",
    ["service", "method", "endpoint"],
    buckets=[0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.0, 5.0],
)

app = FastAPI(title=f"OpsPilot Workload — {SERVICE_NAME}", version=VERSION)


@app.get("/health")
async def health() -> dict:
    return {
        "status": "healthy",
        "service": SERVICE_NAME,
        "version": VERSION,
        "timestamp": datetime.now(UTC).isoformat(),
    }


@app.get("/metrics")
async def metrics() -> Response:
    return Response(content=generate_latest(), media_type="text/plain")


@app.get("/users/{user_id}")
async def get_user(user_id: str) -> dict:
    start = time.monotonic()
    latency = time.monotonic() - start
    REQUEST_COUNT.labels(service=SERVICE_NAME, method="GET", endpoint="/users", status="200").inc()
    REQUEST_LATENCY.labels(service=SERVICE_NAME, method="GET", endpoint="/users").observe(latency)
    return {"user_id": user_id, "service": SERVICE_NAME, "version": VERSION}
