"""Run the investigation agent for an investigation and persist what it found.

Lifecycle (each step its own transaction, so progress is visible and a crash
mid-run leaves an honest record):

    create (PENDING) -> RUNNING -> agent -> evidence + result + COMPLETED
                                       \\-> FAILED (timeout / unexpected error)

Evidence is stored as typed timeline events (spec "evidence" and "tool_calls"):
  EVIDENCE    one per telemetry fact (source_type=telemetry) and per retrieved
              knowledge passage (source_type=knowledge)
  TOOL_CALL   one per MCP call (arguments, status, latency)
  HYPOTHESIS  one per hypothesis (supporting/contradicting ids, confidence)
  CONCLUSION  the conclusion and recommendations
"""

from __future__ import annotations

import time
import uuid
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from typing import Any, Protocol

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.graph import InvestigationAgent
from app.agents.llm import build_llm
from app.agents.models import InvestigationReport
from app.agents.tools import connect_mcp
from app.config import Settings
from app.db.models.investigation import Investigation, InvestigationEventType, InvestigationStatus
from app.rag.embeddings import get_embedder
from app.rag.retrieval import RetrievalService, RetrievedChunk
from app.services.exceptions import AgentFailed, InvestigationTimeout
from app.services.incident import IncidentService
from app.services.investigation import InvestigationService

logger = structlog.get_logger(__name__)

EventSpec = tuple[InvestigationEventType, str, dict[str, Any]]


class AgentFactory(Protocol):
    def __call__(
        self, session: AsyncSession
    ) -> AbstractAsyncContextManager[InvestigationAgent]: ...


class SessionRetriever:
    """The agent's KnowledgeRetriever on top of the RAG RetrievalService."""

    def __init__(self, service: RetrievalService) -> None:
        self.service = service

    async def retrieve(self, query: str, services: list[str] | None) -> list[RetrievedChunk]:
        return await self.service.retrieve(query, services=services)


def default_agent_factory(settings: Settings) -> AgentFactory:
    """Production wiring: MCP over Streamable HTTP, RAG on the request's session."""

    @asynccontextmanager
    async def factory(session: AsyncSession) -> AsyncIterator[InvestigationAgent]:
        token = settings.mcp_auth_token.get_secret_value() if settings.mcp_auth_token else None
        async with connect_mcp(settings.mcp_server_url, token) as tools:
            retriever = SessionRetriever(RetrievalService(session, get_embedder(), settings))
            yield InvestigationAgent(tools, retriever, settings, llm=build_llm(settings))

    return factory


def report_events(report: InvestigationReport) -> list[EventSpec]:
    events: list[EventSpec] = []
    for obs in report.observations:
        events.append((InvestigationEventType.EVIDENCE, obs.statement, {
            "evidence_id": obs.id, "source_type": "telemetry", "source": obs.source,
            "kind": obs.kind, "signals": obs.signals, "at": obs.at.isoformat() if obs.at else None,
            "data": obs.data,
        }))  # fmt: skip
    for item in report.evidence:
        events.append((InvestigationEventType.EVIDENCE, f"{item.title} > {item.section}", {
            "evidence_id": item.id, "source_type": "knowledge", "source": item.citation,
            "relevance": item.score, "excerpt": item.excerpt, "flags": item.flags,
        }))  # fmt: skip
    for call in report.tool_calls:
        events.append((InvestigationEventType.TOOL_CALL, f"{call.tool} -> {call.status}", {
            "tool_name": call.tool, "arguments": call.arguments, "status": call.status,
            "latency_ms": call.duration_ms, "error": call.error,
        }))  # fmt: skip
    for hyp in report.hypotheses:
        events.append((InvestigationEventType.HYPOTHESIS, hyp.statement, {
            "hypothesis_id": hyp.id, "cause": hyp.cause, "status": hyp.status,
            "supporting": hyp.supporting, "contradicting": hyp.contradicting,
            "contradictions": hyp.contradictions,
            "confidence": hyp.confidence.model_dump() if hyp.confidence else None,
        }))  # fmt: skip
    events.append((InvestigationEventType.CONCLUSION, report.conclusion, {
        "root_cause": report.root_cause, "confidence": report.confidence,
        "recommendations": [r.model_dump() for r in report.recommendations],
        "missing_evidence": report.missing_evidence,
    }))  # fmt: skip
    return events


class InvestigationRunner:
    def __init__(
        self, session: AsyncSession, agent_factory: AgentFactory, settings: Settings
    ) -> None:
        self.session = session
        self.agent_factory = agent_factory
        self.settings = settings
        self.investigations = InvestigationService(session)
        self.incidents = IncidentService(session)

    async def create(
        self,
        *,
        query: str | None,
        incident_id: uuid.UUID | None,
        service: str | None,
    ) -> Investigation:
        """Create the investigation; an ad-hoc question gets its own incident record."""
        if incident_id is None:
            incident = await self.incidents.create_incident(
                title=f"Investigation: {query}"[:255],
                description=query,
                service_name=service,
            )
            incident_id = incident.id
        elif query is None:
            incident = await self.incidents.get_incident(incident_id)
            query = " ".join(filter(None, [incident.title, incident.description]))
            service = service or (incident.workload.name if incident.workload else None)
        return await self.investigations.create_investigation(
            incident_id, query=query, service=service
        )

    async def run(
        self, investigation_id: uuid.UUID, *, window_minutes: int | None = None
    ) -> Investigation:
        """Run the agent for a PENDING investigation and persist the outcome."""
        investigation = await self.investigations.change_status(
            investigation_id, InvestigationStatus.RUNNING
        )
        started = time.perf_counter()
        try:
            async with self.agent_factory(self.session) as agent:
                report = await agent.run(
                    investigation.query or "", service=investigation.service,
                    window_minutes=window_minutes,
                )  # fmt: skip
        except TimeoutError as exc:
            await self._fail(
                investigation_id, f"Agent timed out after {self.settings.agent_timeout_seconds} s"
            )
            raise InvestigationTimeout(
                f"Investigation {investigation_id} timed out; partial results were not stored"
            ) from exc
        except Exception as exc:
            logger.exception("agent_failed", investigation_id=str(investigation_id))
            await self._fail(investigation_id, f"Agent failed ({type(exc).__name__})")
            raise AgentFailed(f"Investigation {investigation_id} failed") from exc

        latency_ms = int((time.perf_counter() - started) * 1000)
        # Retrieval may have left the session's read transaction aborted (e.g. the
        # vector store was down); the agent already recorded that as missing evidence.
        await self.session.rollback()
        return await self.investigations.record_result(
            investigation_id,
            result={
                "service": report.service,
                "root_cause": report.root_cause,
                "diagnosis": report.conclusion,
                "confidence": report.confidence,
                "report": report.model_dump(mode="json"),
            },
            events=report_events(report),
            latency_ms=latency_ms,
        )

    async def _fail(self, investigation_id: uuid.UUID, summary: str) -> None:
        await self.session.rollback()
        await self.investigations.change_status(
            investigation_id, InvestigationStatus.FAILED, summary=summary
        )


SessionFactory = Callable[[], AbstractAsyncContextManager[AsyncSession]]


async def run_in_background(
    session_factory: SessionFactory,
    agent_factory: AgentFactory,
    settings: Settings,
    investigation_id: uuid.UUID,
    window_minutes: int | None,
) -> None:
    """Background execution (POST with wait=false): own session, never raises."""
    async with session_factory() as session:
        try:
            await InvestigationRunner(session, agent_factory, settings).run(
                investigation_id, window_minutes=window_minutes
            )
        except Exception:  # already recorded as FAILED by the runner
            logger.warning(
                "background_investigation_failed", investigation_id=str(investigation_id)
            )
