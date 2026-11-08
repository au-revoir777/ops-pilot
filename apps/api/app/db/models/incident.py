"""Incident model."""

from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin, pg_enum

if TYPE_CHECKING:
    from app.db.models.investigation import Investigation
    from app.db.models.workload import Workload


class IncidentStatus(enum.StrEnum):
    """Incident lifecycle states. Allowed transitions live in the service layer."""

    OPEN = "open"
    INVESTIGATING = "investigating"
    MITIGATED = "mitigated"
    RESOLVED = "resolved"
    CLOSED = "closed"


class IncidentSeverity(enum.StrEnum):
    SEV1 = "SEV1"  # Critical, business stopping
    SEV2 = "SEV2"  # Major impact
    SEV3 = "SEV3"  # Minor impact
    SEV4 = "SEV4"  # Trivial / informational


class Incident(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A production incident affecting (optionally) a single workload."""

    __tablename__ = "incidents"
    __table_args__ = (
        # GET /incidents filters by status and orders by newest first.
        Index("ix_incidents_status_created_at", "status", "created_at"),
        Index("ix_incidents_created_at", "created_at"),
    )

    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    status: Mapped[IncidentStatus] = mapped_column(
        pg_enum(IncidentStatus, "incident_status"),
        nullable=False,
        default=IncidentStatus.OPEN,
    )
    severity: Mapped[IncidentSeverity] = mapped_column(
        pg_enum(IncidentSeverity, "incident_severity"),
        nullable=False,
        default=IncidentSeverity.SEV3,
    )
    workload_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("workloads.id", ondelete="RESTRICT"), index=True
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    workload: Mapped[Workload | None] = relationship(back_populates="incidents")
    investigations: Mapped[list[Investigation]] = relationship(
        back_populates="incident",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
