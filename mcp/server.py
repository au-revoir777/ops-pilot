"""OpsPilot MCP Server — Skeleton.

The Model Context Protocol server exposes typed operational tools
for the investigation agent. All tools are read-only.

Fully implemented in Phase 5.
"""

from __future__ import annotations

from fastapi import FastAPI

app = FastAPI(
    title="OpsPilot MCP Server",
    description="Typed operational tools for the investigation agent",
    version="0.1.0",
)


@app.get("/health")
async def health() -> dict:
    return {"status": "healthy", "service": "opspilot-mcp"}
