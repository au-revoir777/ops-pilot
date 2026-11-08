"""Domain / application exceptions.

Each exception carries a stable machine-readable ``code`` and the HTTP status
the API maps it to. Messages must never contain SQL, connection strings or
driver errors; those stay in server-side logs.
"""

from __future__ import annotations


class OpsPilotError(Exception):
    """Base class for all application errors."""

    code = "INTERNAL_ERROR"
    status_code = 500


class NotFoundError(OpsPilotError):
    code = "NOT_FOUND"
    status_code = 404


class InvalidStateError(OpsPilotError):
    code = "INVALID_STATE"
    status_code = 409


class DatabaseOperationError(OpsPilotError):
    code = "DATABASE_ERROR"
    status_code = 503


class IncidentNotFound(NotFoundError):
    code = "INCIDENT_NOT_FOUND"


class InvestigationNotFound(NotFoundError):
    code = "INVESTIGATION_NOT_FOUND"


class InvalidIncidentState(InvalidStateError):
    code = "INVALID_INCIDENT_STATE"


class InvalidInvestigationState(InvalidStateError):
    code = "INVALID_INVESTIGATION_STATE"


class KnowledgeUnavailable(OpsPilotError):
    """Embedding model or vector store unavailable; evidence is missing, not empty."""

    code = "KNOWLEDGE_UNAVAILABLE"
    status_code = 503
