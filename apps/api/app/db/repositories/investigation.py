"""Investigation repository (investigations and their event timeline)."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from sqlalchemy import Select, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models.incident import Incident, IncidentSeverity
from app.db.models.investigation import Investigation, InvestigationEvent, InvestigationStatus

SortField = Literal["created_at", "latency_ms", "confidence"]
SORT_COLUMNS = {
    "created_at": Investigation.created_at,
    "latency_ms": Investigation.latency_ms,
    "confidence": Investigation.confidence,
}


def escape_like(text: str) -> str:
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


@dataclass(frozen=True)
class InvestigationFilters:
    """History filters. All optional; combined with AND."""

    status: InvestigationStatus | None = None
    service: str | None = None
    severity: IncidentSeverity | None = None
    text: str | None = None
    since: datetime | None = None
    until: datetime | None = None
    sort: SortField = "created_at"
    ascending: bool = False


class InvestigationRepository:
    """Data access for investigations. Never commits; the service owns the transaction."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(
        self,
        investigation_id: uuid.UUID,
        *,
        with_events: bool = False,
        for_update: bool = False,
    ) -> Investigation | None:
        stmt = select(Investigation).where(Investigation.id == investigation_id)
        if with_events:
            # One extra SELECT ... WHERE investigation_id IN (...) rather than N lazy loads.
            # populate_existing refreshes instances already in the identity map, so
            # events appended earlier in this session are included.
            stmt = stmt.options(selectinload(Investigation.events)).execution_options(
                populate_existing=True
            )
        if for_update:
            # Locks the investigation row so event sequence numbers cannot collide.
            stmt = stmt.with_for_update(of=Investigation)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    def _filtered(self, filters: InvestigationFilters) -> Select[tuple[Investigation]]:
        stmt = select(Investigation)
        if filters.status is not None:
            stmt = stmt.where(Investigation.status == filters.status)
        if filters.service is not None:
            stmt = stmt.where(Investigation.service == filters.service)
        if filters.severity is not None:
            stmt = stmt.join(Investigation.incident).where(Incident.severity == filters.severity)
        if filters.since is not None:
            stmt = stmt.where(Investigation.created_at >= filters.since)
        if filters.until is not None:
            stmt = stmt.where(Investigation.created_at <= filters.until)
        if filters.text:
            pattern = f"%{escape_like(filters.text)}%"
            stmt = stmt.where(
                or_(
                    Investigation.query.ilike(pattern, escape="\\"),
                    Investigation.diagnosis.ilike(pattern, escape="\\"),
                    Investigation.root_cause.ilike(pattern, escape="\\"),
                )
            )
        return stmt

    async def list_recent(
        self, *, limit: int = 50, offset: int = 0, filters: InvestigationFilters | None = None
    ) -> Sequence[Investigation]:
        filters = filters or InvestigationFilters()
        column = SORT_COLUMNS[filters.sort]
        order = column.asc().nulls_last() if filters.ascending else column.desc().nulls_last()
        stmt = (
            self._filtered(filters)
            .options(selectinload(Investigation.incident))
            .order_by(order, Investigation.id.desc())
        )
        result = await self.session.execute(stmt.limit(limit).offset(offset))
        return result.scalars().all()

    async def count(self, filters: InvestigationFilters | None = None) -> int:
        filtered = self._filtered(filters or InvestigationFilters()).subquery()
        stmt = select(func.count()).select_from(filtered)
        return int((await self.session.execute(stmt)).scalar_one())

    async def list_for_incident(self, incident_id: uuid.UUID) -> Sequence[Investigation]:
        stmt = (
            select(Investigation)
            .where(Investigation.incident_id == incident_id)
            .order_by(Investigation.created_at.desc(), Investigation.id.desc())
        )
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def add(self, investigation: Investigation) -> Investigation:
        self.session.add(investigation)
        await self.session.flush()
        await self.session.refresh(investigation, attribute_names=["created_at", "updated_at"])
        return investigation

    async def next_event_sequence(self, investigation_id: uuid.UUID) -> int:
        """Next sequence number. Call while holding the investigation row lock."""
        stmt = select(func.coalesce(func.max(InvestigationEvent.sequence), 0) + 1).where(
            InvestigationEvent.investigation_id == investigation_id
        )
        result = await self.session.execute(stmt)
        return int(result.scalar_one())

    async def add_event(self, event: InvestigationEvent) -> InvestigationEvent:
        self.session.add(event)
        await self.session.flush()
        await self.session.refresh(event, attribute_names=["created_at"])
        return event

    async def list_events(self, investigation_id: uuid.UUID) -> Sequence[InvestigationEvent]:
        stmt = (
            select(InvestigationEvent)
            .where(InvestigationEvent.investigation_id == investigation_id)
            .order_by(InvestigationEvent.sequence)
        )
        result = await self.session.execute(stmt)
        return result.scalars().all()
