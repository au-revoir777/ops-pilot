"""Investigation application service: lifecycle, timeline events, transactions."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.incident import IncidentStatus
from app.db.models.investigation import (
    Investigation,
    InvestigationEvent,
    InvestigationEventType,
    InvestigationStatus,
)
from app.db.repositories.incident import IncidentRepository
from app.db.repositories.investigation import InvestigationRepository
from app.metrics import (
    INCIDENT_STATUS_CHANGES,
    INVESTIGATION_DURATION,
    INVESTIGATIONS_CREATED,
    INVESTIGATIONS_FINISHED,
)
from app.services.exceptions import (
    IncidentNotFound,
    InvalidIncidentState,
    InvalidInvestigationState,
    InvestigationNotFound,
)
from app.services.incident import apply_incident_transition
from app.services.transactions import transaction

logger = structlog.get_logger(__name__)

INVESTIGATION_TRANSITIONS: dict[InvestigationStatus, frozenset[InvestigationStatus]] = {
    InvestigationStatus.PENDING: frozenset(
        {InvestigationStatus.RUNNING, InvestigationStatus.FAILED}
    ),
    InvestigationStatus.RUNNING: frozenset(
        {InvestigationStatus.PAUSED, InvestigationStatus.COMPLETED, InvestigationStatus.FAILED}
    ),
    InvestigationStatus.PAUSED: frozenset(
        {InvestigationStatus.RUNNING, InvestigationStatus.FAILED}
    ),
    InvestigationStatus.COMPLETED: frozenset(),
    InvestigationStatus.FAILED: frozenset(),
}

TERMINAL_INVESTIGATION_STATES = frozenset(
    {InvestigationStatus.COMPLETED, InvestigationStatus.FAILED}
)

# An investigation can only be opened against an incident that is still live.
INVESTIGABLE_INCIDENT_STATES = frozenset(
    {IncidentStatus.OPEN, IncidentStatus.INVESTIGATING, IncidentStatus.MITIGATED}
)


def validate_investigation_transition(
    current: InvestigationStatus, target: InvestigationStatus
) -> None:
    if target not in INVESTIGATION_TRANSITIONS[current]:
        raise InvalidInvestigationState(
            f"Cannot move investigation from '{current.value}' to '{target.value}'"
        )


class InvestigationService:
    def __init__(
        self,
        session: AsyncSession,
        investigations: InvestigationRepository | None = None,
        incidents: IncidentRepository | None = None,
    ) -> None:
        self.session = session
        self.investigations = investigations or InvestigationRepository(session)
        self.incidents = incidents or IncidentRepository(session)

    async def get_investigation(self, investigation_id: uuid.UUID) -> Investigation:
        investigation = await self.investigations.get(investigation_id, with_events=True)
        if investigation is None:
            raise InvestigationNotFound(f"Investigation {investigation_id} not found")
        return investigation

    async def list_for_incident(self, incident_id: uuid.UUID) -> Sequence[Investigation]:
        if await self.incidents.get(incident_id) is None:
            raise IncidentNotFound(f"Incident {incident_id} not found")
        return await self.investigations.list_for_incident(incident_id)

    async def create_investigation(self, incident_id: uuid.UUID) -> Investigation:
        """Open an investigation and move an OPEN incident to INVESTIGATING, atomically."""
        async with transaction(self.session, "create_investigation"):
            incident = await self.incidents.get(incident_id, for_update=True)
            if incident is None:
                raise IncidentNotFound(f"Incident {incident_id} not found")
            if incident.status not in INVESTIGABLE_INCIDENT_STATES:
                raise InvalidIncidentState(
                    f"Cannot investigate an incident in state '{incident.status.value}'"
                )
            moved_incident = incident.status is IncidentStatus.OPEN
            if moved_incident:
                apply_incident_transition(incident, IncidentStatus.INVESTIGATING)

            investigation = await self.investigations.add(
                Investigation(incident_id=incident.id, status=InvestigationStatus.PENDING)
            )
            await self.investigations.add_event(
                InvestigationEvent(
                    investigation_id=investigation.id,
                    sequence=1,
                    event_type=InvestigationEventType.STATUS_CHANGE,
                    message="Investigation created",
                    details={"to": InvestigationStatus.PENDING.value},
                )
            )
        # Metrics only after a successful commit, so rolled-back work is never counted.
        INVESTIGATIONS_CREATED.inc()
        if moved_incident:
            INCIDENT_STATUS_CHANGES.labels(from_status="open", to_status="investigating").inc()
        logger.info(
            "investigation_created",
            investigation_id=str(investigation.id),
            incident_id=str(incident_id),
        )
        return await self.get_investigation(investigation.id)

    async def change_status(
        self,
        investigation_id: uuid.UUID,
        target: InvestigationStatus,
        *,
        summary: str | None = None,
    ) -> Investigation:
        """Apply a lifecycle transition and record it on the timeline, atomically."""
        async with transaction(self.session, "change_investigation_status"):
            investigation = await self._get_locked(investigation_id)
            previous = investigation.status
            validate_investigation_transition(previous, target)

            now = datetime.now(UTC)
            investigation.status = target
            if target is InvestigationStatus.RUNNING and investigation.started_at is None:
                investigation.started_at = now
            if target in TERMINAL_INVESTIGATION_STATES:
                investigation.completed_at = now
            if summary is not None:
                investigation.summary = summary

            await self._append_event(
                investigation_id,
                InvestigationEventType.STATUS_CHANGE,
                f"Status changed from {previous.value} to {target.value}",
                {"from": previous.value, "to": target.value},
            )
        if target in TERMINAL_INVESTIGATION_STATES:
            INVESTIGATIONS_FINISHED.labels(outcome=target.value).inc()
            if investigation.started_at is not None:
                INVESTIGATION_DURATION.labels(outcome=target.value).observe(
                    (now - investigation.started_at).total_seconds()
                )
        logger.info(
            "investigation_status_changed",
            investigation_id=str(investigation_id),
            from_status=previous.value,
            to_status=target.value,
        )
        return await self.get_investigation(investigation_id)

    async def record_event(
        self,
        investigation_id: uuid.UUID,
        event_type: InvestigationEventType,
        message: str,
        details: dict[str, Any] | None = None,
    ) -> InvestigationEvent:
        """Append evidence / tool calls / notes to a live investigation."""
        if event_type is InvestigationEventType.STATUS_CHANGE:
            raise InvalidInvestigationState("Status changes must go through change_status()")
        async with transaction(self.session, "record_investigation_event"):
            investigation = await self._get_locked(investigation_id)
            if investigation.status in TERMINAL_INVESTIGATION_STATES:
                raise InvalidInvestigationState(
                    f"Cannot add events to a {investigation.status.value} investigation"
                )
            event = await self._append_event(investigation_id, event_type, message, details)
        return event

    async def _get_locked(self, investigation_id: uuid.UUID) -> Investigation:
        investigation = await self.investigations.get(investigation_id, for_update=True)
        if investigation is None:
            raise InvestigationNotFound(f"Investigation {investigation_id} not found")
        return investigation

    async def _append_event(
        self,
        investigation_id: uuid.UUID,
        event_type: InvestigationEventType,
        message: str,
        details: dict[str, Any] | None,
    ) -> InvestigationEvent:
        sequence = await self.investigations.next_event_sequence(investigation_id)
        return await self.investigations.add_event(
            InvestigationEvent(
                investigation_id=investigation_id,
                sequence=sequence,
                event_type=event_type,
                message=message,
                details=details,
            )
        )
