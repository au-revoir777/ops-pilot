"""Investigation endpoints.

Skeleton - the core investigation workflow will be implemented in Phase 6-7.
"""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter()


@router.post("/investigations")
async def create_investigation() -> dict:
    """Submit a new investigation request."""
    return {"status": "not_implemented"}


@router.get("/investigations/{investigation_id}")
async def get_investigation(investigation_id: str) -> dict:
    """Retrieve an investigation result."""
    return {"investigation_id": investigation_id, "status": "not_implemented"}
