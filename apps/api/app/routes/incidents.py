"""Incident API endpoints. Thin: validate input, call the service, shape the output.

Domain exceptions propagate to the centralized handlers in app.main.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

from app.db.models.incident import Incident, IncidentSeverity, IncidentStatus
from app.dependencies import IncidentServiceDep

router = APIRouter()


class IncidentCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=10_000)
    severity: IncidentSeverity = IncidentSeverity.SEV3
    service_name: str | None = Field(
        default=None, min_length=1, max_length=100, pattern=r"^[a-z0-9][a-z0-9_-]*$"
    )


class IncidentStatusUpdate(BaseModel):
    status: IncidentStatus


class IncidentResponse(BaseModel):
    id: uuid.UUID
    title: str
    description: str | None
    status: IncidentStatus
    severity: IncidentSeverity
    service_name: str | None
    resolved_at: datetime | None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_model(cls, incident: Incident) -> IncidentResponse:
        return cls(
            id=incident.id,
            title=incident.title,
            description=incident.description,
            status=incident.status,
            severity=incident.severity,
            service_name=incident.workload.name if incident.workload else None,
            resolved_at=incident.resolved_at,
            created_at=incident.created_at,
            updated_at=incident.updated_at,
        )


@router.post("/incidents", response_model=IncidentResponse, status_code=201)
async def create_incident(data: IncidentCreate, service: IncidentServiceDep) -> IncidentResponse:
    incident = await service.create_incident(
        title=data.title,
        description=data.description,
        severity=data.severity,
        service_name=data.service_name,
    )
    return IncidentResponse.from_model(incident)


@router.get("/incidents", response_model=list[IncidentResponse])
async def list_incidents(
    service: IncidentServiceDep,
    status: IncidentStatus | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[IncidentResponse]:
    incidents = await service.list_incidents(status=status, limit=limit, offset=offset)
    return [IncidentResponse.from_model(i) for i in incidents]


@router.get("/incidents/{incident_id}", response_model=IncidentResponse)
async def get_incident(incident_id: uuid.UUID, service: IncidentServiceDep) -> IncidentResponse:
    return IncidentResponse.from_model(await service.get_incident(incident_id))


@router.patch("/incidents/{incident_id}/status", response_model=IncidentResponse)
async def update_incident_status(
    incident_id: uuid.UUID,
    data: IncidentStatusUpdate,
    service: IncidentServiceDep,
) -> IncidentResponse:
    return IncidentResponse.from_model(await service.update_status(incident_id, data.status))
