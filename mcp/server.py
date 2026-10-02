"""OpsPilot MCP Server - Skeleton.

Uses the official Model Context Protocol Python SDK (mcp.server.fastmcp).
Exposes typed, read-only operational tools for the investigation agent.

Transport: Streamable HTTP (default for v2.x SDK).
The MCP SDK handles JSON-RPC framing, schema generation, and validation.

Fully implemented in Phase 5.
"""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

# ---------------------------------------------------------------------------
# MCP Server instance
# ---------------------------------------------------------------------------
mcp = FastMCP(
    "OpsPilot MCP",
    instructions=(
        "Operational tools for SRE incident investigation. "
        "All tools are read-only. No shell execution. No infrastructure mutation."
    ),
)


# ---------------------------------------------------------------------------
# Tool stubs — full implementations in Phase 5
# ---------------------------------------------------------------------------
@mcp.tool()
def get_service_health(service: str) -> dict:
    """Get health status for a service including error rate, latency, and dependencies.

    Args:
        service: Name of the service to check (e.g. 'checkout', 'payments', 'users').

    Returns:
        Dictionary with status, error_rate, p95_latency_ms, request_rate,
        and dependency_status.
    """
    return {
        "status": "not_implemented",
        "service": service,
        "message": "Tool will be implemented in Phase 5",
    }


@mcp.tool()
def query_metrics(query: str, start_time: str, end_time: str) -> dict:
    """Query Prometheus metrics for a given time range.

    Args:
        query: PromQL query string.
        start_time: ISO 8601 start time.
        end_time: ISO 8601 end time.

    Returns:
        Dictionary with metric name, timestamps, and values.
    """
    return {"status": "not_implemented", "query": query}


@mcp.tool()
def get_recent_logs(
    service: str, minutes: int = 30, severity: str | None = None
) -> dict:
    """Retrieve recent logs for a service.

    Args:
        service: Service name.
        minutes: Number of minutes to look back (default 30).
        severity: Optional log severity filter (e.g. 'ERROR', 'WARN').

    Returns:
        List of log entries with timestamp, level, message, and metadata.
    """
    return {"status": "not_implemented", "service": service}


@mcp.tool()
def get_recent_deployments(service: str) -> dict:
    """Get recent deployment history for a service.

    Args:
        service: Service name.

    Returns:
        List of deployments with version, deployment_time, and status.
    """
    return {"status": "not_implemented", "service": service}


@mcp.tool()
def get_service_dependencies(service: str) -> dict:
    """Get the dependency graph for a service.

    Args:
        service: Service name.

    Returns:
        List of upstream and downstream dependencies.
    """
    return {"status": "not_implemented", "service": service}


@mcp.tool()
def get_incident_events(service: str, minutes: int = 60) -> dict:
    """Get recent incident-related events for a service.

    Args:
        service: Service name.
        minutes: Number of minutes to look back (default 60).

    Returns:
        List of incident events.
    """
    return {"status": "not_implemented", "service": service}


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    mcp.run(transport="streamable-http")
