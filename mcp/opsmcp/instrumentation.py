"""Prometheus metrics and structured logging for tool calls."""

from __future__ import annotations

import functools
import logging
import time
from collections.abc import Awaitable, Callable
from typing import Any, ParamSpec, TypeVar

import structlog
from prometheus_client import Counter, Histogram

P = ParamSpec("P")
R = TypeVar("R")

BUCKETS = (0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0)

TOOL_CALLS = Counter(
    "opspilot_mcp_tool_calls_total",
    "MCP tool calls handled by the server",
    ["tool", "outcome"],  # outcome: ok | partial | unavailable | invalid | error
)
TOOL_DURATION = Histogram(
    "opspilot_mcp_tool_duration_seconds", "MCP tool latency", ["tool"], buckets=BUCKETS
)
BACKEND_LATENCY = Histogram(
    "opspilot_mcp_backend_request_duration_seconds",
    "Latency of requests from the MCP server to observability backends",
    ["backend", "outcome"],
    buckets=BUCKETS,
)

logger = structlog.get_logger("opsmcp.tools")


def configure_logging(service: str, level: str) -> None:
    def add_service(_logger, _method, event_dict):
        event_dict.setdefault("service", service)
        return event_dict

    numeric = getattr(logging, level.upper(), logging.INFO)
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.stdlib.add_log_level,
            add_service,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(numeric),
        logger_factory=structlog.PrintLoggerFactory(),
    )


def instrumented(tool: str) -> Callable[[Callable[P, Awaitable[R]]], Callable[P, Awaitable[R]]]:
    """Log latency and outcome of every call and record Prometheus metrics.

    Arguments are logged (they are validated, small and contain no secrets);
    results are not, since log lines can be large.
    """

    def decorator(func: Callable[P, Awaitable[R]]) -> Callable[P, Awaitable[R]]:
        @functools.wraps(func)
        async def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            start = time.perf_counter()
            outcome = "error"
            try:
                result = await func(*args, **kwargs)
                outcome = getattr(result, "status", "ok")
                return result
            except ValueError:
                outcome = "invalid"
                raise
            finally:
                elapsed = time.perf_counter() - start
                TOOL_CALLS.labels(tool=tool, outcome=outcome).inc()
                TOOL_DURATION.labels(tool=tool).observe(elapsed)
                log = logger.warning if outcome in {"error", "unavailable"} else logger.info
                log(
                    "tool_call",
                    tool_name=tool,
                    outcome=outcome,
                    latency_ms=round(elapsed * 1000, 1),
                    arguments=_loggable(kwargs),
                )

        return wrapper

    return decorator


def _loggable(kwargs: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in kwargs.items() if k != "deps" and not k.startswith("_")}
