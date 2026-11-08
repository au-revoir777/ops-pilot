"""Investigation API endpoints. Thin: validate input, call the runner/service, shape output."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, BackgroundTasks, Query, Response
from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.config import get_settings
from app.db.models.incident import IncidentSeverity
from app.db.models.investigation import InvestigationEventType, InvestigationStatus
from app.db.repositories.investigation import InvestigationFilters, SortField
from app.dependencies import (
    AgentFactoryDep,
    BackgroundSessionFactoryDep,
    InvestigationServiceDep,
    SessionDep,
)
from app.security import InvestigationSlotDep
from app.services.investigation_runner import InvestigationRunner, run_in_background

router = APIRouter()


class InvestigationCreate(BaseModel):
    """Start an investigation from a question, an existing incident, or both."""

    query: str | None = Field(
        default=None,
        min_length=3,
        max_length=1000,
        description="e.g. 'Investigate why checkout latency increased'",
    )
    incident_id: uuid.UUID | None = None
    service: str | None = Field(
        default=None, min_length=1, max_length=100, pattern=r"^[a-z0-9][a-z0-9_-]*$"
    )
    window_minutes: int | None = Field(default=None, ge=5, le=360)
    wait: bool = Field(
        default=True,
        description="true: run the agent and return the result (201). "
        "false: return 202 immediately and run in the background; poll GET.",
    )

    @model_validator(mode="after")
    def _need_question_or_incident(self) -> InvestigationCreate:
        if self.query is None and self.incident_id is None:
            raise ValueError("provide a query, an incident_id, or both")
        return self


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
    query: str | None
    service: str | None
    root_cause: str | None
    diagnosis: str | None
    confidence: float | None
    latency_ms: int | None
    summary: str | None
    started_at: datetime | None
    completed_at: datetime | None
    created_at: datetime
    updated_at: datetime


class InvestigationListItem(InvestigationSummary):
    severity: IncidentSeverity | None = None  # from the investigated incident


class InvestigationDetail(InvestigationSummary):
    report: dict[str, Any] | None = Field(
        description="Full agent report: observations, evidence, hypotheses, recommendations"
    )
    events: list[InvestigationEventResponse]


@router.post(
    "/investigations",
    response_model=InvestigationDetail,
    status_code=201,
    responses={202: {"description": "Accepted; the agent runs in the background"}},
)
async def create_investigation(
    _slot: InvestigationSlotDep,
    data: InvestigationCreate,
    session: SessionDep,
    agent_factory: AgentFactoryDep,
    session_factory: BackgroundSessionFactoryDep,
    background: BackgroundTasks,
    response: Response,
) -> InvestigationDetail:
    settings = get_settings()
    runner = InvestigationRunner(session, agent_factory, settings)
    investigation = await runner.create(
        query=data.query, incident_id=data.incident_id, service=data.service
    )
    if not data.wait:
        background.add_task(run_in_background, session_factory, agent_factory, settings,
                            investigation.id, data.window_minutes)  # fmt: skip
        response.status_code = 202
        return InvestigationDetail.model_validate(investigation)
    finished = await runner.run(investigation.id, window_minutes=data.window_minutes)
    return InvestigationDetail.model_validate(finished)


@router.get("/investigations", response_model=list[InvestigationListItem])
async def list_investigations(
    service: InvestigationServiceDep,
    response: Response,
    status: InvestigationStatus | None = None,
    service_name: Annotated[
        str | None, Query(alias="service", max_length=100, pattern=r"^[a-z0-9][a-z0-9_-]*$")
    ] = None,
    severity: IncidentSeverity | None = None,
    q: Annotated[str | None, Query(max_length=200)] = None,
    since: datetime | None = None,
    until: datetime | None = None,
    sort: SortField = "created_at",
    order: Literal["asc", "desc"] = "desc",
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[InvestigationListItem]:
    """History view: filtered, sorted, paginated server-side. X-Total-Count has the total."""
    filters = InvestigationFilters(
        status=status, service=service_name, severity=severity, text=q or None,
        since=since, until=until, sort=sort, ascending=order == "asc",
    )  # fmt: skip
    investigations, total = await service.list_investigations(
        limit=limit, offset=offset, filters=filters
    )
    response.headers["X-Total-Count"] = str(total)
    return [
        InvestigationListItem.model_validate(i).model_copy(
            update={"severity": i.incident.severity if i.incident else None}
        )
        for i in investigations
    ]


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
