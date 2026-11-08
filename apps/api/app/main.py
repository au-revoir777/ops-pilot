"""OpsPilot — FastAPI application entry-point.

Responsibilities:
  - Create and configure the FastAPI app
  - Mount routers
  - Configure CORS
  - Configure structured logging and per-request correlation IDs
  - Map domain exceptions to structured error responses
  - Create / dispose the database engine in the lifespan
"""

from __future__ import annotations

import logging
import re
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app import metrics
from app.config import get_settings
from app.db.session import close_db_engine, init_engine
from app.routes import (
    chat,
    health,
    incidents,
    investigations,
    knowledge,
    lab,
    replay,
    system,
    telemetry,
)
from app.services.exceptions import OpsPilotError

REQUEST_ID_HEADER = "X-Request-ID"
_VALID_REQUEST_ID = re.compile(r"^[A-Za-z0-9._-]{1,64}$")

# ---------------------------------------------------------------------------
# Structured logging setup
# ---------------------------------------------------------------------------


def _add_service_context(_logger, _method, event_dict):
    """Every log line carries service and version for correlation in Loki."""
    event_dict.setdefault("service", metrics.SERVICE)
    event_dict.setdefault("version", health.VERSION)
    return event_dict


def _configure_logging(log_level: str) -> None:
    """Configure structlog for JSON-based structured logging."""
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.stdlib.filter_by_level,
            structlog.stdlib.add_logger_name,
            structlog.stdlib.add_log_level,
            structlog.stdlib.PositionalArgumentsFormatter(),
            _add_service_context,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.UnicodeDecoder(),
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )
    logging.basicConfig(format="%(message)s", level=getattr(logging, log_level.upper(), "INFO"))


# ---------------------------------------------------------------------------
# Correlation IDs
# ---------------------------------------------------------------------------


class CorrelationIdMiddleware:
    """Bind a request ID to structlog's context and echo it in the response.

    An incoming X-Request-ID is reused only if it is short and URL-safe, so a
    client cannot inject arbitrary content into the logs.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        incoming = dict(scope["headers"]).get(REQUEST_ID_HEADER.lower().encode(), b"").decode()
        request_id = incoming if _VALID_REQUEST_ID.match(incoming) else uuid.uuid4().hex

        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(request_id=request_id)

        async def send_with_request_id(message: Message) -> None:
            if message["type"] == "http.response.start":
                message.setdefault("headers", []).append(
                    (REQUEST_ID_HEADER.lower().encode(), request_id.encode())
                )
            await send(message)

        await self.app(scope, receive, send_with_request_id)


def _current_request_id() -> str | None:
    return structlog.contextvars.get_contextvars().get("request_id")


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Create the single engine/pool at startup; dispose of it on shutdown."""
    settings = get_settings()
    _configure_logging(settings.log_level)
    logger = structlog.get_logger("opspilot.startup")
    init_engine(settings)
    logger.info("opspilot_starting", env=settings.app_env, api_port=settings.api_port)
    try:
        yield
    finally:
        await close_db_engine()
        logger.info("opspilot_shutdown")


# ---------------------------------------------------------------------------
# Exception handlers
# ---------------------------------------------------------------------------


def _error_body(code: str, message: str) -> dict[str, object]:
    return {"error": {"code": code, "message": message, "request_id": _current_request_id()}}


async def opspilot_error_handler(request: Request, exc: OpsPilotError) -> JSONResponse:
    """Map domain errors to their HTTP status. Server-side errors hide their message."""
    logger = structlog.get_logger("opspilot.errors")
    if exc.status_code >= 500:
        logger.error("request_failed", path=request.url.path, code=exc.code)
        # Only messages written for clients (no internals) are passed through.
        message = (
            str(exc)
            if exc.public_message
            else ("The request could not be completed. Please retry later.")
        )
    else:
        logger.info("request_rejected", path=request.url.path, code=exc.code)
        message = str(exc)
    return JSONResponse(status_code=exc.status_code, content=_error_body(exc.code, message))


async def unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
    """Last resort: log the traceback server-side, return a generic 500."""
    structlog.get_logger("opspilot.errors").exception(
        "unhandled_exception", path=request.url.path, error_type=type(exc).__name__
    )
    return JSONResponse(
        status_code=500, content=_error_body("INTERNAL_ERROR", "Internal server error")
    )


# ---------------------------------------------------------------------------
# Application factory
# ---------------------------------------------------------------------------


def create_app() -> FastAPI:
    """Build the FastAPI application."""
    settings = get_settings()

    app = FastAPI(
        title="OpsPilot API",
        description="AI-Powered Production Incident Investigation and SRE Copilot",
        version="0.1.0",
        docs_url="/docs" if not settings.is_production else None,
        redoc_url="/redoc" if not settings.is_production else None,
        lifespan=lifespan,
    )

    app.add_exception_handler(OpsPilotError, opspilot_error_handler)
    app.add_exception_handler(Exception, unhandled_error_handler)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.api_cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=[REQUEST_ID_HEADER],
    )
    app.add_middleware(metrics.MetricsMiddleware)
    # Added last so it is the outermost middleware and wraps everything else.
    app.add_middleware(CorrelationIdMiddleware)

    metrics.set_build_info(health.VERSION)

    @app.get("/metrics", include_in_schema=False)
    async def prometheus_metrics() -> Response:
        # Scraped over the internal network only; not routed by the public ALB.
        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

    app.include_router(health.router, tags=["Health"])
    app.include_router(incidents.router, prefix="/api", tags=["Incidents"])
    app.include_router(investigations.router, prefix="/api", tags=["Investigations"])
    app.include_router(knowledge.router, prefix="/api", tags=["Knowledge"])
    app.include_router(system.router, prefix="/api", tags=["System"])
    app.include_router(lab.router, prefix="/api", tags=["Incident lab"])
    app.include_router(telemetry.router, prefix="/api", tags=["Telemetry"])
    app.include_router(replay.router, prefix="/api", tags=["Replay"])
    app.include_router(chat.router, prefix="/api", tags=["Chat"])

    return app


# Module-level app instance for uvicorn
app = create_app()
