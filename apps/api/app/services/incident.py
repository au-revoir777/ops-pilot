"""Incident application service: lifecycle rules and transaction coordination."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.incident import Incident, IncidentSeverity, IncidentStatus
from app.db.models.workload import Workload
from app.db.repositories.incident import IncidentRepository
from app.db.repositories.workload import WorkloadRepository
from app.metrics import INCIDENT_STATUS_CHANGES, INCIDENTS_CREATED
from app.services.exceptions import IncidentNotFound, InvalidIncidentState
from app.services.transactions import transaction

logger = structlog.get_logger(__name__)

# Allowed incident lifecycle transitions. CLOSED is terminal; RESOLVED may be
# reopened into INVESTIGATING if the problem recurs.
INCIDENT_TRANSITIONS: dict[IncidentStatus, frozenset[IncidentStatus]] = {
    IncidentStatus.OPEN: frozenset(
        {IncidentStatus.INVESTIGATING, IncidentStatus.MITIGATED, IncidentStatus.RESOLVED}
    ),
    IncidentStatus.INVESTIGATING: frozenset({IncidentStatus.MITIGATED, IncidentStatus.RESOLVED}),
    IncidentStatus.MITIGATED: frozenset({IncidentStatus.INVESTIGATING, IncidentStatus.RESOLVED}),
    IncidentStatus.RESOLVED: frozenset({IncidentStatus.INVESTIGATING, IncidentStatus.CLOSED}),
    IncidentStatus.CLOSED: frozenset(),
}


def validate_incident_transition(current: IncidentStatus, target: IncidentStatus) -> None:
    """Raise InvalidIncidentState unless current -> target is an allowed transition."""
    if target not in INCIDENT_TRANSITIONS[current]:
        raise InvalidIncidentState(
            f"Cannot move incident from '{current.value}' to '{target.value}'"
        )


class IncidentService:
    def __init__(
        self,
        session: AsyncSession,
        incidents: IncidentRepository | None = None,
        workloads: WorkloadRepository | None = None,
    ) -> None:
        self.session = session
        self.incidents = incidents or IncidentRepository(session)
        self.workloads = workloads or WorkloadRepository(session)

    async def get_incident(self, incident_id: uuid.UUID) -> Incident:
        incident = await self.incidents.get(incident_id)
        if incident is None:
            raise IncidentNotFound(f"Incident {incident_id} not found")
        return incident

    async def list_incidents(
        self,
        *,
        status: IncidentStatus | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> Sequence[Incident]:
        return await self.incidents.list_recent(status=status, limit=limit, offset=offset)

    async def create_incident(
        self,
        *,
        title: str,
        description: str | None = None,
        severity: IncidentSeverity = IncidentSeverity.SEV3,
        service_name: str | None = None,
    ) -> Incident:
        """Create an incident, registering its workload on first sight, atomically."""
        async with transaction(self.session, "create_incident"):
            workload = None
            if service_name:
                workload = await self.workloads.get_by_name(service_name)
                if workload is None:
                    workload = self.workloads.add(Workload(name=service_name))
            incident = await self.incidents.add(
                Incident(
                    title=title,
                    description=description,
                    severity=severity,
                    status=IncidentStatus.OPEN,
                    workload=workload,
                )
            )
        INCIDENTS_CREATED.labels(severity=severity.value).inc()
        logger.info("incident_created", incident_id=str(incident.id), severity=severity.value)
        return incident

    async def update_status(self, incident_id: uuid.UUID, target: IncidentStatus) -> Incident:
        async with transaction(self.session, "update_incident_status"):
            incident = await self.incidents.get(incident_id, for_update=True)
            if incident is None:
                raise IncidentNotFound(f"Incident {incident_id} not found")
            previous = incident.status
            apply_incident_transition(incident, target)
            await self.session.flush()
            await self.session.refresh(incident, attribute_names=["updated_at"])
        INCIDENT_STATUS_CHANGES.labels(from_status=previous.value, to_status=target.value).inc()
        logger.info(
            "incident_status_changed",
            incident_id=str(incident_id),
            from_status=previous.value,
            to_status=target.value,
        )
        return incident


def apply_incident_transition(incident: Incident, target: IncidentStatus) -> None:
    """Validate and apply a status change, maintaining resolved_at."""
    validate_incident_transition(incident.status, target)
    incident.status = target
    if target is IncidentStatus.RESOLVED:
        incident.resolved_at = datetime.now(UTC)
    elif target is IncidentStatus.INVESTIGATING:
        incident.resolved_at = None
