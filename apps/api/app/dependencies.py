"""FastAPI dependency injection providers."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db_session
from app.services.incident import IncidentService
from app.services.investigation import InvestigationService

SessionDep = Annotated[AsyncSession, Depends(get_db_session)]


def get_incident_service(session: SessionDep) -> IncidentService:
    return IncidentService(session)


def get_investigation_service(session: SessionDep) -> InvestigationService:
    return InvestigationService(session)


IncidentServiceDep = Annotated[IncidentService, Depends(get_incident_service)]
InvestigationServiceDep = Annotated[InvestigationService, Depends(get_investigation_service)]
