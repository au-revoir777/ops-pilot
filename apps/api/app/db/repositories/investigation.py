"""Investigation repository (investigations and their event timeline)."""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models.investigation import Investigation, InvestigationEvent, InvestigationStatus


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

    async def list_recent(
        self, *, limit: int = 50, offset: int = 0, status: InvestigationStatus | None = None
    ) -> Sequence[Investigation]:
        stmt = select(Investigation)
        if status is not None:
            stmt = stmt.where(Investigation.status == status)
        stmt = stmt.order_by(Investigation.created_at.desc(), Investigation.id.desc())
        result = await self.session.execute(stmt.limit(limit).offset(offset))
        return result.scalars().all()

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
