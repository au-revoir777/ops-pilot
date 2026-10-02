"""Incident management endpoints.

Skeleton — will be fully implemented in Phase 1 / Phase 7.
"""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter()


@router.get("/incidents")
async def list_incidents() -> dict:
    """List active and historical incidents."""
    return {"incidents": [], "total": 0}


@router.get("/incidents/{incident_id}")
async def get_incident(incident_id: str) -> dict:
    """Get a specific incident by ID."""
    return {"incident_id": incident_id, "status": "not_implemented"}
