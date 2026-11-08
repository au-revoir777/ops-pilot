"""Incident repository."""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.db.models.incident import Incident, IncidentStatus


class IncidentRepository:
    """Data access for incidents. Never commits; the service owns the transaction.

    The workload is always eager-loaded (one JOIN) because every API response
    includes the service name. That avoids N+1 queries on list endpoints and
    async lazy-load errors.
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, incident_id: uuid.UUID, *, for_update: bool = False) -> Incident | None:
        stmt = (
            select(Incident)
            .options(joinedload(Incident.workload))
            .where(Incident.id == incident_id)
        )
        if for_update:
            # Serialises concurrent state transitions on the same incident.
            stmt = stmt.with_for_update(of=Incident)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_recent(
        self,
        *,
        status: IncidentStatus | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> Sequence[Incident]:
        stmt = select(Incident).options(joinedload(Incident.workload))
        if status is not None:
            stmt = stmt.where(Incident.status == status)
        stmt = (
            stmt.order_by(Incident.created_at.desc(), Incident.id.desc())
            .limit(limit)
            .offset(offset)
        )
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def add(self, incident: Incident) -> Incident:
        """Stage a new incident and flush so DB defaults (timestamps) are populated."""
        self.session.add(incident)
        await self.session.flush()
        await self.session.refresh(incident, attribute_names=["created_at", "updated_at"])
        return incident
