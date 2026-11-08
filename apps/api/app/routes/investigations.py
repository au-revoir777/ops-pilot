"""Investigation API endpoints. Thin: validate input, call the service, shape the output."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict

from app.db.models.investigation import InvestigationEventType, InvestigationStatus
from app.dependencies import InvestigationServiceDep

router = APIRouter()


class InvestigationCreate(BaseModel):
    incident_id: uuid.UUID


class InvestigationEventResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    sequence: int
    event_type: InvestigationEventType
    message: str
    details: dict[str, Any] | None
    created_at: datetime


class InvestigationSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    incident_id: uuid.UUID
    status: InvestigationStatus
    summary: str | None
    started_at: datetime | None
    completed_at: datetime | None
    created_at: datetime
    updated_at: datetime


class InvestigationDetail(InvestigationSummary):
    events: list[InvestigationEventResponse]


@router.post("/investigations", response_model=InvestigationDetail, status_code=201)
async def create_investigation(
    data: InvestigationCreate, service: InvestigationServiceDep
) -> InvestigationDetail:
    investigation = await service.create_investigation(data.incident_id)
    return InvestigationDetail.model_validate(investigation)


@router.get("/investigations/{investigation_id}", response_model=InvestigationDetail)
async def get_investigation(
    investigation_id: uuid.UUID, service: InvestigationServiceDep
) -> InvestigationDetail:
    return InvestigationDetail.model_validate(await service.get_investigation(investigation_id))


@router.get("/incidents/{incident_id}/investigations", response_model=list[InvestigationSummary])
async def list_incident_investigations(
    incident_id: uuid.UUID, service: InvestigationServiceDep
) -> list[InvestigationSummary]:
    investigations = await service.list_for_incident(incident_id)
    return [InvestigationSummary.model_validate(i) for i in investigations]
