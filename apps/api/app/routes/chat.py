"""Chat / conversational endpoint for the investigation agent.

Skeleton - will be wired to the LangGraph agent in Phase 6-7.
"""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter()


@router.post("/chat")
async def chat() -> dict:
    """Send a message to the investigation agent."""
    return {"status": "not_implemented"}
