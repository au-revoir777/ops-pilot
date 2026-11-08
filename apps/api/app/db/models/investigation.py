"""Investigation and investigation event models."""

from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Integer, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, CreatedAtMixin, TimestampMixin, UUIDPrimaryKeyMixin, pg_enum
from app.db.models.incident import Incident


class InvestigationStatus(enum.StrEnum):
    """Investigation lifecycle states. Allowed transitions live in the service layer."""

    PENDING = "pending"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"


class InvestigationEventType(enum.StrEnum):
    """Kinds of entries in an investigation's append-only timeline."""

    STATUS_CHANGE = "status_change"
    NOTE = "note"
    TOOL_CALL = "tool_call"
    EVIDENCE = "evidence"
    HYPOTHESIS = "hypothesis"
    CONCLUSION = "conclusion"


class Investigation(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One (agent-driven) investigation of an incident."""

    __tablename__ = "investigations"

    incident_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("incidents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    status: Mapped[InvestigationStatus] = mapped_column(
        pg_enum(InvestigationStatus, "investigation_status"),
        nullable=False,
        default=InvestigationStatus.PENDING,
    )
    summary: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    incident: Mapped[Incident] = relationship(back_populates="investigations")
    events: Mapped[list[InvestigationEvent]] = relationship(
        back_populates="investigation",
        order_by="InvestigationEvent.sequence",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class InvestigationEvent(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    """Append-only timeline entry: status changes, tool calls, evidence, conclusions.

    ``details`` is the one JSONB column in the schema. Tool outputs and evidence
    are genuinely semi-structured (a PromQL result looks nothing like a log
    excerpt), so forcing them into columns would be premature.
    """

    __tablename__ = "investigation_events"
    __table_args__ = (
        # Gives a stable total order per investigation and doubles as the
        # index for "load the timeline for investigation X".
        UniqueConstraint("investigation_id", "sequence"),
    )

    investigation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("investigations.id", ondelete="CASCADE"), nullable=False
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    event_type: Mapped[InvestigationEventType] = mapped_column(
        pg_enum(InvestigationEventType, "investigation_event_type"), nullable=False
    )
    message: Mapped[str] = mapped_column(Text, nullable=False)
    details: Mapped[dict[str, Any] | None] = mapped_column(JSONB)

    investigation: Mapped[Investigation] = relationship(back_populates="events")
