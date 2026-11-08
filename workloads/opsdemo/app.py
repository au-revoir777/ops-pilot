"""Shared FastAPI app factory for the demo workloads.

Every workload gets: GET /health, GET /metrics, GET|POST /admin/failure,
request IDs, JSON access logs, RED metrics, structured errors and the
``inject_request_failures`` dependency for its business routes.
"""

from __future__ import annotations

import asyncio
import hmac
import random
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Annotated

import httpx
import structlog
from fastapi import APIRouter, Depends, FastAPI, Header, Request, Response
from fastapi.responses import JSONResponse
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from pydantic import BaseModel

from opsdemo.config import WorkloadSettings
from opsdemo.failures import (
    FailureInjectionDisabled,
    FailureInjector,
    FailureMode,
    FailureProfile,
)
from opsdemo.observability import (
    REQUEST_ID_HEADER,
    RequestContextMiddleware,
    WorkloadMetrics,
    configure_logging,
    current_request_id,
)

logger = structlog.get_logger("workload")


class WorkloadError(Exception):
    """An error with an HTTP status and a stable code, rendered as structured JSON."""

    def __init__(self, status_code: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message


class SimulatedDatabase:
    """Stands in for a real database: baseline latency plus injected slowness.

    Keeps the workloads lightweight (D-012) while still emitting the signals an
    investigation needs: a query-latency histogram and slow-query WARN logs.
    """

    def __init__(
        self,
        injector: FailureInjector,
        metrics: WorkloadMetrics,
        rng: random.Random,
        slow_query_ms: int,
    ) -> None:
        self.injector = injector
        self.metrics = metrics
        self.rng = rng
        self.slow_query_ms = slow_query_ms

    async def query(self, operation: str, base_ms: tuple[int, int] = (10, 40)) -> None:
        start = time.perf_counter()
        await asyncio.sleep(self.rng.uniform(*base_ms) / 1000 + self.injector.db_delay_seconds())
        elapsed = time.perf_counter() - start
        self.metrics.db_latency.labels(service=self.metrics.service, operation=operation).observe(
            elapsed
        )
        if elapsed * 1000 >= self.slow_query_ms:
            logger.warning(
                "slow_query_detected", operation=operation, query_time_ms=round(elapsed * 1000)
            )


@dataclass
class WorkloadContext:
    settings: WorkloadSettings
    injector: FailureInjector
    metrics: WorkloadMetrics
    db: SimulatedDatabase
    rng: random.Random

    async def simulate_work(self, low_ms: int, high_ms: int) -> None:
        """Baseline CPU/IO time so normal latency looks like a real service."""
        await asyncio.sleep(self.rng.uniform(low_ms, high_ms) / 1000)


def get_context(request: Request) -> WorkloadContext:
    return request.app.state.ctx


ContextDep = Annotated[WorkloadContext, Depends(get_context)]


async def inject_request_failures(ctx: ContextDep) -> None:
    """Dependency for business routes: applies latency / error injection."""
    delay = ctx.injector.request_delay_seconds()
    if delay:
        await asyncio.sleep(delay)
    if ctx.injector.should_fail_request():
        # Logged the way a real unhandled error would be; nothing says "injected".
        logger.error("request_processing_failed", error_type="InternalError")
        raise WorkloadError(500, "INTERNAL_ERROR", "Internal server error")


def build_downstream_client(
    settings: WorkloadSettings, transport: httpx.AsyncBaseTransport | None = None
) -> httpx.AsyncClient:
    """HTTP client that forwards the current request ID to other services."""

    async def propagate_request_id(request: httpx.Request) -> None:
        request_id = current_request_id()
        if request_id:
            request.headers[REQUEST_ID_HEADER] = request_id

    return httpx.AsyncClient(
        timeout=settings.downstream_timeout_seconds,
        transport=transport,
        event_hooks={"request": [propagate_request_id]},
    )


# ---------------------------------------------------------------------------
# Common routes
# ---------------------------------------------------------------------------


class FailureModeUpdate(BaseModel):
    mode: FailureMode


def _require_admin(
    ctx: ContextDep, x_admin_token: Annotated[str | None, Header()] = None
) -> WorkloadContext:
    if not ctx.injector.enabled:
        raise WorkloadError(403, "FAILURE_INJECTION_DISABLED", "Failure injection is disabled")
    expected = ctx.settings.failure_admin_token
    if expected is not None and not hmac.compare_digest(
        (x_admin_token or "").encode(), expected.get_secret_value().encode()
    ):
        raise WorkloadError(401, "UNAUTHORIZED", "Missing or invalid admin token")
    return ctx


AdminDep = Annotated[WorkloadContext, Depends(_require_admin)]


def _common_router() -> APIRouter:
    router = APIRouter()

    @router.get("/health")
    async def health(ctx: ContextDep) -> dict[str, str]:
        # Liveness only. Deliberately does not reveal the failure mode: an
        # investigation has to find the problem from telemetry, like in production.
        return {
            "status": "healthy",
            "service": ctx.settings.service_name,
            "version": ctx.settings.service_version,
            "timestamp": datetime.now(UTC).isoformat(),
        }

    @router.get("/metrics")
    async def metrics(ctx: ContextDep) -> Response:
        return Response(generate_latest(ctx.metrics.registry), media_type=CONTENT_TYPE_LATEST)

    @router.get("/admin/failure", include_in_schema=False)
    async def get_failure_mode(ctx: AdminDep) -> dict[str, str]:
        return {"service": ctx.settings.service_name, "mode": ctx.injector.mode.value}

    @router.post("/admin/failure", include_in_schema=False)
    async def set_failure_mode(body: FailureModeUpdate, ctx: AdminDep) -> dict[str, str]:
        previous = ctx.injector.mode
        try:
            ctx.injector.set_mode(body.mode)
        except FailureInjectionDisabled as exc:  # pragma: no cover - guarded by AdminDep
            raise WorkloadError(403, "FAILURE_INJECTION_DISABLED", str(exc)) from exc
        logger.info("failure_mode_changed", previous=previous.value, mode=body.mode.value)
        return {"service": ctx.settings.service_name, "mode": body.mode.value}

    return router


async def _workload_error_handler(_request: Request, exc: WorkloadError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": {"code": exc.code, "message": exc.message, "request_id": current_request_id()}
        },
    )


async def _unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("unhandled_exception", path=request.url.path, error_type=type(exc).__name__)
    return JSONResponse(
        status_code=500,
        content={
            "error": {
                "code": "INTERNAL_ERROR",
                "message": "Internal server error",
                "request_id": current_request_id(),
            }
        },
    )


def create_workload_app(
    settings: WorkloadSettings,
    *,
    title: str,
    transport: httpx.AsyncBaseTransport | None = None,
) -> FastAPI:
    """Build a workload app. ``transport`` lets tests stub downstream services."""
    configure_logging(settings.service_name, settings.service_version, settings.log_level)

    rng = random.Random(settings.failure_seed)  # noqa: S311 - simulation, not security
    metrics = WorkloadMetrics(settings.service_name, settings.service_version)
    injector = FailureInjector(
        enabled=settings.enable_failure_injection,
        mode=settings.failure_mode,
        profile=FailureProfile(
            latency_ms=settings.failure_latency_ms,
            db_latency_ms=settings.failure_db_latency_ms,
            error_rate=settings.failure_error_rate,
        ),
        rng=rng,
    )
    ctx = WorkloadContext(
        settings=settings,
        injector=injector,
        metrics=metrics,
        db=SimulatedDatabase(injector, metrics, rng, settings.slow_query_ms),
        rng=rng,
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.http = build_downstream_client(settings, transport)
        if settings.failure_mode is not FailureMode.NONE and not injector.enabled:
            logger.warning(
                "failure_mode_ignored",
                reason="ENABLE_FAILURE_INJECTION is false",
                configured_mode=settings.failure_mode.value,
            )
        logger.info("service_started", failure_injection_enabled=injector.enabled)
        try:
            yield
        finally:
            await app.state.http.aclose()

    app = FastAPI(title=title, version=settings.service_version, lifespan=lifespan)
    app.state.ctx = ctx
    app.add_exception_handler(WorkloadError, _workload_error_handler)
    app.add_exception_handler(Exception, _unhandled_error_handler)
    app.add_middleware(
        RequestContextMiddleware, metrics=metrics, slow_request_ms=settings.slow_request_ms
    )
    app.include_router(_common_router())
    return app
