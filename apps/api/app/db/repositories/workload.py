"""Workload repository."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.workload import Workload


class WorkloadRepository:
    """Data access for workloads. Never commits; the service owns the transaction."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_name(self, name: str) -> Workload | None:
        result = await self.session.execute(select(Workload).where(Workload.name == name))
        return result.scalar_one_or_none()

    def add(self, workload: Workload) -> Workload:
        self.session.add(workload)
        return workload
