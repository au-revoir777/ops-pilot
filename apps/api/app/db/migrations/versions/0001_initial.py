"""Initial schema: pgvector, workloads, incidents, investigations, investigation_events.

Revision ID: 0001
Revises:
Create Date: 2026-10-02 14:14:14.000000

"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

# create_type=False: types are created/dropped explicitly below so that
# upgrade and downgrade are symmetric and deterministic.
incident_status = postgresql.ENUM(
    "open", "investigating", "mitigated", "resolved", "closed",
    name="incident_status", create_type=False,
)  # fmt: skip
incident_severity = postgresql.ENUM(
    "SEV1", "SEV2", "SEV3", "SEV4", name="incident_severity", create_type=False
)
investigation_status = postgresql.ENUM(
    "pending", "running", "paused", "completed", "failed",
    name="investigation_status", create_type=False,
)  # fmt: skip
investigation_event_type = postgresql.ENUM(
    "status_change", "note", "tool_call", "evidence", "hypothesis", "conclusion",
    name="investigation_event_type", create_type=False,
)  # fmt: skip

ENUMS = (incident_status, incident_severity, investigation_status, investigation_event_type)


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    ]


def upgrade() -> None:
    # pgvector is enabled now so Phase 4 (RAG) only has to add tables, not
    # extensions. No vector columns yet: the dimension depends on the embedding
    # model, which is chosen in Phase 4 (see DECISIONS.md D-016).
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    bind = op.get_bind()
    for enum_type in ENUMS:
        enum_type.create(bind, checkfirst=False)

    op.create_table(
        "workloads",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_workloads")),
        sa.UniqueConstraint("name", name=op.f("uq_workloads_name")),
    )

    op.create_table(
        "incidents",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("status", incident_status, nullable=False),
        sa.Column("severity", incident_severity, nullable=False),
        sa.Column("workload_id", sa.Uuid(), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(
            ["workload_id"],
            ["workloads.id"],
            name=op.f("fk_incidents_workload_id_workloads"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_incidents")),
    )
    op.create_index("ix_incidents_created_at", "incidents", ["created_at"])
    op.create_index("ix_incidents_status_created_at", "incidents", ["status", "created_at"])
    op.create_index(op.f("ix_incidents_workload_id"), "incidents", ["workload_id"])

    op.create_table(
        "investigations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("incident_id", sa.Uuid(), nullable=False),
        sa.Column("status", investigation_status, nullable=False),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(
            ["incident_id"],
            ["incidents.id"],
            name=op.f("fk_investigations_incident_id_incidents"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_investigations")),
    )
    op.create_index(op.f("ix_investigations_incident_id"), "investigations", ["incident_id"])

    op.create_table(
        "investigation_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("investigation_id", sa.Uuid(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("event_type", investigation_event_type, nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("details", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["investigation_id"],
            ["investigations.id"],
            name=op.f("fk_investigation_events_investigation_id_investigations"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_investigation_events")),
        sa.UniqueConstraint(
            "investigation_id",
            "sequence",
            name=op.f("uq_investigation_events_investigation_id_sequence"),
        ),
    )


def downgrade() -> None:
    op.drop_table("investigation_events")
    op.drop_index(op.f("ix_investigations_incident_id"), table_name="investigations")
    op.drop_table("investigations")
    op.drop_index(op.f("ix_incidents_workload_id"), table_name="incidents")
    op.drop_index("ix_incidents_status_created_at", table_name="incidents")
    op.drop_index("ix_incidents_created_at", table_name="incidents")
    op.drop_table("incidents")
    op.drop_table("workloads")

    bind = op.get_bind()
    for enum_type in reversed(ENUMS):
        enum_type.drop(bind, checkfirst=False)

    op.execute("DROP EXTENSION IF EXISTS vector")
