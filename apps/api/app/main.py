"""OpsPilot — FastAPI application entry-point.

Responsibilities:
  - Create and configure the FastAPI app
  - Mount routers
  - Configure CORS
  - Configure structured logging
  - Expose lifespan hooks for startup / shutdown
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.routes import chat, health, incidents, investigations

# ---------------------------------------------------------------------------
# Structured logging setup
# ---------------------------------------------------------------------------

def _configure_logging(log_level: str) -> None:
    """Configure structlog for JSON-based structured logging."""
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.stdlib.filter_by_level,
            structlog.stdlib.add_logger_name,
            structlog.stdlib.add_log_level,
            structlog.stdlib.PositionalArgumentsFormatter(),
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
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
# Lifespan
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Startup and shutdown hooks."""
    settings = get_settings()
    _configure_logging(settings.log_level)
    logger = structlog.get_logger("opspilot.startup")
    logger.info(
        "opspilot_starting",
        env=settings.app_env,
        api_port=settings.api_port,
    )
    yield
    logger.info("opspilot_shutdown")


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

    # -- CORS --
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.api_cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # -- Routers --
    app.include_router(health.router, tags=["Health"])
    app.include_router(incidents.router, prefix="/api", tags=["Incidents"])
    app.include_router(investigations.router, prefix="/api", tags=["Investigations"])
    app.include_router(chat.router, prefix="/api", tags=["Chat"])

    return app


# Module-level app instance for uvicorn
app = create_app()
