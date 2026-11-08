"""FastAPI dependency injection providers."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import session as db_session
from app.db.session import get_db_session
from app.services.incident import IncidentService
from app.services.investigation import InvestigationService
from app.services.investigation_runner import (
    AgentFactory,
    SessionFactory,
    default_agent_factory,
)

SessionDep = Annotated[AsyncSession, Depends(get_db_session)]


def get_incident_service(session: SessionDep) -> IncidentService:
    return IncidentService(session)


def get_investigation_service(session: SessionDep) -> InvestigationService:
    return InvestigationService(session)


def get_agent_factory() -> AgentFactory:
    """How the API builds an agent (MCP client + RAG). Overridden in tests."""
    return default_agent_factory(get_settings())


def get_background_session_factory() -> SessionFactory:
    """Sessions for background investigations (outlive the request's session).

    Resolved lazily, so requests that never start background work do not need it.
    """
    return lambda: db_session.session_factory()()


IncidentServiceDep = Annotated[IncidentService, Depends(get_incident_service)]
InvestigationServiceDep = Annotated[InvestigationService, Depends(get_investigation_service)]
AgentFactoryDep = Annotated[AgentFactory, Depends(get_agent_factory)]
BackgroundSessionFactoryDep = Annotated[SessionFactory, Depends(get_background_session_factory)]
