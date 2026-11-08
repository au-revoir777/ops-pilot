"""Workload (monitored service) model."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.db.models.incident import Incident


class Workload(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A monitored service (e.g. checkout, payments, users) that incidents affect."""

    __tablename__ = "workloads"

    # Stable identifier matching the service label used in metrics and logs.
    name: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    description: Mapped[str | None] = mapped_column(Text)

    incidents: Mapped[list[Incident]] = relationship(back_populates="workload")
