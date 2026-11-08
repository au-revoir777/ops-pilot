"""Transaction boundary helper used by the service layer.

Repositories only stage changes (add / flush). A service method that changes
state wraps its whole unit of work in ``transaction(session)``: everything
inside commits together, or everything rolls back. Driver errors are logged and
converted into DatabaseOperationError so no internals reach the API.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import structlog
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.exceptions import DatabaseOperationError

logger = structlog.get_logger(__name__)


@asynccontextmanager
async def transaction(session: AsyncSession, operation: str) -> AsyncIterator[None]:
    """Commit on success; roll back on any exception (domain or database)."""
    try:
        yield
        await session.commit()
    except SQLAlchemyError as exc:
        await session.rollback()
        # exc.__class__.__name__ only: str(exc) can include SQL and parameters.
        logger.error("db_transaction_failed", operation=operation, error_type=type(exc).__name__)
        raise DatabaseOperationError(f"Database operation failed: {operation}") from exc
    except BaseException:
        await session.rollback()
        raise
