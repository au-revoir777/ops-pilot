"""Unit tests for service-layer business rules and transaction handling.

Repositories and the session are mocked here; the same flows run against real
PostgreSQL in tests/integration.
"""

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.exc import IntegrityError

from app.db.models import (
    Incident,
    IncidentSeverity,
    IncidentStatus,
    Investigation,
    InvestigationEventType,
    InvestigationStatus,
    Workload,
)
from app.services.exceptions import (
    DatabaseOperationError,
    IncidentNotFound,
    InvalidIncidentState,
    InvalidInvestigationState,
)
from app.services.incident import (
    INCIDENT_TRANSITIONS,
    IncidentService,
    apply_incident_transition,
    validate_incident_transition,
)
from app.services.investigation import InvestigationService, validate_investigation_transition

S = IncidentStatus
I = InvestigationStatus  # noqa: E741


def mock_session() -> AsyncMock:
    session = AsyncMock()
    session.add = MagicMock()
    return session


# ---------------------------------------------------------------------------
# Incident state machine
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("current", "target"),
    [
        (S.OPEN, S.INVESTIGATING),
        (S.OPEN, S.RESOLVED),
        (S.INVESTIGATING, S.MITIGATED),
        (S.MITIGATED, S.RESOLVED),
        (S.RESOLVED, S.CLOSED),
        (S.RESOLVED, S.INVESTIGATING),
    ],
)
def test_allowed_incident_transitions(current, target):
    validate_incident_transition(current, target)


@pytest.mark.parametrize(
    ("current", "target"),
    [
        (S.CLOSED, S.OPEN),
        (S.CLOSED, S.INVESTIGATING),
        (S.RESOLVED, S.OPEN),
        (S.INVESTIGATING, S.OPEN),
        (S.OPEN, S.CLOSED),
        (S.OPEN, S.OPEN),
    ],
)
def test_rejected_incident_transitions(current, target):
    with pytest.raises(InvalidIncidentState):
        validate_incident_transition(current, target)


def test_every_incident_status_has_transition_rules():
    assert set(INCIDENT_TRANSITIONS) == set(IncidentStatus)


def test_resolving_sets_and_reopening_clears_resolved_at():
    incident = Incident(status=S.MITIGATED)
    apply_incident_transition(incident, S.RESOLVED)
    assert incident.resolved_at is not None
    apply_incident_transition(incident, S.INVESTIGATING)
    assert incident.resolved_at is None


# ---------------------------------------------------------------------------
# IncidentService
# ---------------------------------------------------------------------------


async def test_create_incident_commits_once_and_registers_new_workload():
    session = mock_session()
    incidents, workloads = AsyncMock(), MagicMock()
    workloads.get_by_name = AsyncMock(return_value=None)
    workloads.add = MagicMock(side_effect=lambda w: w)
    incidents.add.side_effect = lambda inc: inc
    service = IncidentService(session, incidents=incidents, workloads=workloads)

    incident = await service.create_incident(
        title="p99 latency", severity=IncidentSeverity.SEV2, service_name="checkout"
    )

    assert incident.status is S.OPEN
    assert incident.workload.name == "checkout"
    workloads.add.assert_called_once()
    session.commit.assert_awaited_once()
    session.rollback.assert_not_awaited()


async def test_create_incident_reuses_existing_workload():
    session = mock_session()
    existing = Workload(name="checkout")
    incidents, workloads = AsyncMock(), MagicMock()
    workloads.get_by_name = AsyncMock(return_value=existing)
    workloads.add = MagicMock()
    incidents.add.side_effect = lambda inc: inc
    service = IncidentService(session, incidents=incidents, workloads=workloads)

    incident = await service.create_incident(title="x", service_name="checkout")

    assert incident.workload is existing
    workloads.add.assert_not_called()


async def test_create_incident_rolls_back_and_wraps_database_errors():
    session = mock_session()
    session.commit.side_effect = IntegrityError("INSERT ...", {}, Exception("dup"))
    incidents = AsyncMock()
    incidents.add.side_effect = lambda inc: inc
    service = IncidentService(session, incidents=incidents, workloads=MagicMock())

    with pytest.raises(DatabaseOperationError) as excinfo:
        await service.create_incident(title="x")

    session.rollback.assert_awaited_once()
    assert "INSERT" not in str(excinfo.value)


async def test_get_missing_incident_raises_not_found():
    incidents = AsyncMock()
    incidents.get.return_value = None
    service = IncidentService(mock_session(), incidents=incidents)
    with pytest.raises(IncidentNotFound):
        await service.get_incident(uuid.uuid4())


async def test_invalid_status_update_rolls_back_without_commit():
    session = mock_session()
    incidents = AsyncMock()
    incidents.get.return_value = Incident(id=uuid.uuid4(), status=S.CLOSED)
    service = IncidentService(session, incidents=incidents)

    with pytest.raises(InvalidIncidentState):
        await service.update_status(uuid.uuid4(), S.OPEN)

    session.commit.assert_not_awaited()
    session.rollback.assert_awaited_once()


async def test_status_update_locks_row():
    session = mock_session()
    incidents = AsyncMock()
    incidents.get.return_value = Incident(id=uuid.uuid4(), status=S.OPEN)
    service = IncidentService(session, incidents=incidents)

    result = await service.update_status(uuid.uuid4(), S.INVESTIGATING)

    assert result.status is S.INVESTIGATING
    assert incidents.get.await_args.kwargs == {"for_update": True}
    session.commit.assert_awaited_once()


# ---------------------------------------------------------------------------
# Investigation state machine and service
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("current", "target", "allowed"),
    [
        (I.PENDING, I.RUNNING, True),
        (I.RUNNING, I.PAUSED, True),
        (I.PAUSED, I.RUNNING, True),
        (I.RUNNING, I.COMPLETED, True),
        (I.PENDING, I.COMPLETED, False),
        (I.COMPLETED, I.RUNNING, False),
        (I.FAILED, I.PENDING, False),
    ],
)
def test_investigation_transitions(current, target, allowed):
    if allowed:
        validate_investigation_transition(current, target)
    else:
        with pytest.raises(InvalidInvestigationState):
            validate_investigation_transition(current, target)


@pytest.mark.parametrize("status", [S.RESOLVED, S.CLOSED])
async def test_cannot_investigate_finished_incident(status):
    session = mock_session()
    incidents, investigations = AsyncMock(), AsyncMock()
    incidents.get.return_value = Incident(id=uuid.uuid4(), status=status)
    service = InvestigationService(session, investigations=investigations, incidents=incidents)

    with pytest.raises(InvalidIncidentState):
        await service.create_investigation(uuid.uuid4())

    investigations.add.assert_not_awaited()
    session.rollback.assert_awaited_once()


async def test_create_investigation_for_missing_incident():
    incidents = AsyncMock()
    incidents.get.return_value = None
    service = InvestigationService(mock_session(), investigations=AsyncMock(), incidents=incidents)
    with pytest.raises(IncidentNotFound):
        await service.create_investigation(uuid.uuid4())


async def test_record_event_rejects_status_change_type():
    service = InvestigationService(
        mock_session(), investigations=AsyncMock(), incidents=AsyncMock()
    )
    with pytest.raises(InvalidInvestigationState):
        await service.record_event(uuid.uuid4(), InvestigationEventType.STATUS_CHANGE, "x")


async def test_record_event_rejects_terminal_investigation():
    session = mock_session()
    investigations = AsyncMock()
    investigations.get.return_value = Investigation(id=uuid.uuid4(), status=I.COMPLETED)
    service = InvestigationService(session, investigations=investigations, incidents=AsyncMock())

    with pytest.raises(InvalidInvestigationState):
        await service.record_event(uuid.uuid4(), InvestigationEventType.EVIDENCE, "late")

    investigations.add_event.assert_not_awaited()
    session.commit.assert_not_awaited()
