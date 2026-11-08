"""Repository, service and constraint tests against real PostgreSQL (no mocks)."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    Incident,
    IncidentSeverity,
    IncidentStatus,
    Investigation,
    InvestigationEvent,
    InvestigationEventType,
    InvestigationStatus,
    Workload,
)
from app.db.repositories import IncidentRepository
from app.services.exceptions import DatabaseOperationError, InvalidInvestigationState
from app.services.incident import IncidentService
from app.services.investigation import InvestigationService


async def count(session: AsyncSession, model) -> int:
    return (await session.execute(select(func.count()).select_from(model))).scalar_one()


# ---------------------------------------------------------------------------
# Connectivity and extensions
# ---------------------------------------------------------------------------


async def test_database_connectivity(db_session: AsyncSession):
    assert (await db_session.execute(text("SELECT 1"))).scalar_one() == 1


async def test_pgvector_extension_available(db_session: AsyncSession):
    result = await db_session.execute(text("SELECT '[1,2,3]'::vector <-> '[1,2,4]'::vector"))
    assert result.scalar_one() == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# Repositories
# ---------------------------------------------------------------------------


async def test_incident_repository_roundtrip_and_db_defaults(db_session: AsyncSession):
    repo = IncidentRepository(db_session)
    incident = await repo.add(Incident(title="Disk full", workload=Workload(name="payments")))
    assert incident.created_at is not None
    assert incident.created_at.tzinfo is not None
    assert incident.status is IncidentStatus.OPEN
    assert incident.severity is IncidentSeverity.SEV3

    db_session.expunge_all()
    loaded = await repo.get(incident.id)
    assert loaded is not None
    assert loaded.workload is not None
    assert loaded.workload.name == "payments"


async def test_list_filters_orders_and_paginates(db_session: AsyncSession):
    repo = IncidentRepository(db_session)
    for i in range(5):
        await repo.add(Incident(title=f"inc-{i}"))
    # now() is constant within a transaction, so give each row a distinct age:
    # inc-0 is newest, inc-4 oldest.
    await db_session.execute(
        text(
            "UPDATE incidents SET created_at = now() - (interval '1 minute' * "
            "CAST(substring(title from 5) AS int))"
        )
    )
    db_session.expunge_all()
    page = await repo.list_recent(limit=2, offset=1)
    assert [i.title for i in page] == ["inc-1", "inc-2"]

    resolved = await repo.add(Incident(title="done", status=IncidentStatus.RESOLVED))
    only_resolved = await repo.list_recent(status=IncidentStatus.RESOLVED)
    assert [i.id for i in only_resolved] == [resolved.id]


async def test_list_does_not_issue_n_plus_one_queries(db_session: AsyncSession, engine):
    repo = IncidentRepository(db_session)
    for i in range(5):
        await repo.add(Incident(title=f"n1-{i}", workload=Workload(name=f"svc-{i}")))
    db_session.expunge_all()

    statements: list[str] = []
    sync_conn = (await db_session.connection()).sync_connection

    from sqlalchemy import event

    def _capture(conn, cursor, statement, *args):
        statements.append(statement)

    event.listen(sync_conn, "before_cursor_execute", _capture)
    try:
        incidents = await repo.list_recent()
        names = {i.workload.name for i in incidents if i.workload}
    finally:
        event.remove(sync_conn, "before_cursor_execute", _capture)

    assert {f"svc-{i}" for i in range(5)} <= names
    assert len(statements) == 1


# ---------------------------------------------------------------------------
# Constraints and foreign keys
# ---------------------------------------------------------------------------


async def test_workload_name_is_unique(db_session: AsyncSession):
    db_session.add(Workload(name="checkout"))
    await db_session.flush()
    db_session.add(Workload(name="checkout"))
    with pytest.raises(IntegrityError, match="uq_workloads_name"):
        await db_session.flush()


async def test_investigation_requires_existing_incident(db_session: AsyncSession):
    db_session.add(Investigation(incident_id=uuid.uuid4()))
    with pytest.raises(IntegrityError, match="fk_investigations_incident_id_incidents"):
        await db_session.flush()


async def test_event_sequence_unique_per_investigation(db_session: AsyncSession):
    incident = Incident(title="x")
    investigation = Investigation(incident=incident)
    db_session.add(investigation)
    await db_session.flush()
    for _ in range(2):
        db_session.add(
            InvestigationEvent(
                investigation_id=investigation.id,
                sequence=1,
                event_type=InvestigationEventType.NOTE,
                message="dup",
            )
        )
    with pytest.raises(IntegrityError, match="uq_investigation_events_investigation_id_sequence"):
        await db_session.flush()


async def test_deleting_incident_cascades_in_database(db_session: AsyncSession):
    service = InvestigationService(db_session)
    incident = await IncidentService(db_session).create_incident(title="cascade")
    await service.create_investigation(incident.id)

    # Raw SQL delete: proves ON DELETE CASCADE is enforced by PostgreSQL itself.
    await db_session.execute(text("DELETE FROM incidents WHERE id = :id"), {"id": incident.id})
    assert await count(db_session, Investigation) == 0
    assert await count(db_session, InvestigationEvent) == 0


async def test_workload_in_use_cannot_be_deleted(db_session: AsyncSession):
    incident = await IncidentService(db_session).create_incident(title="x", service_name="users")
    with pytest.raises(IntegrityError, match="fk_incidents_workload_id_workloads"):
        await db_session.execute(
            text("DELETE FROM workloads WHERE id = :id"), {"id": incident.workload_id}
        )


async def test_invalid_enum_value_rejected_by_database(db_session: AsyncSession):
    with pytest.raises(Exception, match="invalid input value for enum incident_status"):
        await db_session.execute(
            text(
                "INSERT INTO incidents (id, title, status, severity) "
                "VALUES (gen_random_uuid(), 't', 'exploded', 'SEV1')"
            )
        )


# ---------------------------------------------------------------------------
# Services and transactions
# ---------------------------------------------------------------------------


async def test_create_investigation_moves_incident_and_writes_event(db_session: AsyncSession):
    incident = await IncidentService(db_session).create_incident(
        title="cpu", service_name="checkout"
    )
    investigation = await InvestigationService(db_session).create_investigation(incident.id)

    assert investigation.status is InvestigationStatus.PENDING
    assert [e.sequence for e in investigation.events] == [1]
    assert investigation.events[0].event_type is InvestigationEventType.STATUS_CHANGE

    db_session.expunge_all()
    reloaded = await IncidentRepository(db_session).get(incident.id)
    assert reloaded is not None
    assert reloaded.status is IncidentStatus.INVESTIGATING


async def test_investigation_lifecycle_and_timeline(db_session: AsyncSession):
    incident = await IncidentService(db_session).create_incident(title="latency")
    service = InvestigationService(db_session)
    inv = await service.create_investigation(incident.id)

    await service.change_status(inv.id, InvestigationStatus.RUNNING)
    await service.record_event(
        inv.id,
        InvestigationEventType.EVIDENCE,
        "p99 latency 2.3s on /checkout",
        {"query": "histogram_quantile(0.99, ...)", "value": 2.3},
    )
    done = await service.change_status(inv.id, InvestigationStatus.COMPLETED, summary="DB pool")

    assert done.started_at is not None
    assert done.completed_at is not None
    assert done.summary == "DB pool"
    assert [e.sequence for e in done.events] == [1, 2, 3, 4]
    assert done.events[2].details == {"query": "histogram_quantile(0.99, ...)", "value": 2.3}

    with pytest.raises(InvalidInvestigationState):
        await service.record_event(inv.id, InvestigationEventType.NOTE, "too late")


async def test_failed_transaction_rolls_back_every_change(db_session: AsyncSession):
    """A DB error mid-unit-of-work leaves no partial writes behind."""
    service = IncidentService(db_session)
    await service.create_incident(title="seed", service_name="checkout")
    before = (await count(db_session, Incident), await count(db_session, Workload))

    # Force the incident INSERT to fail *after* the new workload was staged.
    await db_session.execute(
        text("ALTER TABLE incidents ADD CONSTRAINT ck_test_no_boom CHECK (title <> 'boom')")
    )
    with pytest.raises(DatabaseOperationError):
        await service.create_incident(title="boom", service_name="brand-new-service")

    after = (await count(db_session, Incident), await count(db_session, Workload))
    assert after == before
    assert (
        await db_session.scalar(select(Workload).where(Workload.name == "brand-new-service"))
        is None
    )
