"""Tool access for the agent: an allow-listed MCP client.

The agent can only call the six read-only MCP tools below; any other name is
refused before a request is made. Results come back as the server's
structured content. Transport failures become an ``unavailable`` result, so a
dead MCP server is reported as missing evidence instead of crashing the run.
"""

from __future__ import annotations

import time
from collections.abc import AsyncIterator
from contextlib import AsyncExitStack, asynccontextmanager
from typing import Any, Protocol

import httpx
import structlog
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from app.metrics import TOOL_CALL_DURATION, TOOL_CALLS

logger = structlog.get_logger(__name__)

ALLOWED_TOOLS = frozenset(
    {
        "get_service_health",
        "query_metrics",
        "get_recent_logs",
        "get_recent_deployments",
        "get_service_dependencies",
        "get_incident_events",
    }
)


class ToolNotAllowed(ValueError):
    pass


class ToolClient(Protocol):
    async def call(self, tool: str, arguments: dict[str, Any]) -> dict[str, Any]: ...


def unavailable(reason: str) -> dict[str, Any]:
    return {
        "status": "unavailable",
        "errors": [{"source": "mcp", "error": "mcp_unavailable", "detail": reason}],
    }


class McpToolClient:
    """Calls tools on the OpsPilot MCP server through the official MCP client."""

    def __init__(self, session: ClientSession | None) -> None:
        self.session = session

    async def call(self, tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if tool not in ALLOWED_TOOLS:
            raise ToolNotAllowed(f"tool '{tool}' is not on the allow-list")
        start = time.perf_counter()
        outcome = "error"
        try:
            if self.session is None:
                outcome = "unavailable"
                return unavailable("MCP server not reachable")
            result = await self.session.call_tool(tool, arguments)
            if result.isError:
                outcome = "invalid"
                text = result.content[0].text if result.content else "tool error"
                return {
                    "status": "error",
                    "errors": [{"source": "mcp", "error": "tool_error", "detail": text[:300]}],
                }
            content = result.structuredContent or {}
            outcome = content.get("status", "ok")
            return content
        except Exception as exc:  # transport failures mid-run
            outcome = "unavailable"
            logger.warning("mcp_call_failed", tool=tool, error_type=type(exc).__name__)
            return unavailable(type(exc).__name__)
        finally:
            TOOL_CALLS.labels(tool=tool, outcome=outcome).inc()
            TOOL_CALL_DURATION.labels(tool=tool).observe(time.perf_counter() - start)


@asynccontextmanager
async def connect_mcp(
    url: str, token: str | None, timeout: float = 30.0
) -> AsyncIterator[ToolClient]:
    """Open one MCP session for an investigation; degrade to 'unavailable' if it fails."""
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    http = httpx.AsyncClient(headers=headers, timeout=timeout)
    stack = AsyncExitStack()
    try:
        read, write, _ = await stack.enter_async_context(
            streamable_http_client(f"{url.rstrip('/')}/mcp", http_client=http)
        )
        session = await stack.enter_async_context(ClientSession(read, write))
        await session.initialize()
        client = McpToolClient(session)
    except Exception as exc:
        logger.warning("mcp_unavailable", error_type=type(exc).__name__)
        await stack.aclose()
        client = McpToolClient(None)
    try:
        yield client
    finally:
        try:
            await stack.aclose()
        except Exception as exc:
            # The SDK's background reader re-raises transport errors (e.g. a read
            # timeout) when the session closes. Each call already reported them
            # as 'unavailable'; don't turn a finished request into a 500.
            logger.warning("mcp_close_failed", error_type=type(exc).__name__)
        await http.aclose()
