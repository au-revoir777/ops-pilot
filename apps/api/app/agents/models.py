"""Data shapes for the investigation agent.

The report keeps evidence types apart (spec section 11):

  observations   facts read from telemetry, each with its source tool
  evidence       knowledge-base passages actually retrieved (citations)
  hypotheses     candidate causes the agent proposed
  validation     which evidence supports or contradicts each hypothesis
  conclusion     the best-supported hypothesis, its confidence and why
  recommendations  next actions (never executed by the agent)
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

ObservationKind = Literal["health", "metric", "log", "deployment", "alert", "dependency"]
HypothesisStatus = Literal["supported", "weak", "rejected"]


class Observation(BaseModel):
    """A fact read from telemetry. ``signals`` are machine tags used by the rules."""

    id: str
    kind: ObservationKind
    statement: str
    source: str  # MCP tool that produced it
    at: datetime | None = None
    signals: list[str] = Field(default_factory=list)
    data: dict[str, Any] = Field(default_factory=dict)


class RetrievedEvidence(BaseModel):
    id: str
    citation: str  # source#chunk-N
    title: str
    section: str | None
    score: float
    excerpt: str
    flags: list[str] = Field(default_factory=list)


class ToolCall(BaseModel):
    tool: str
    arguments: dict[str, Any]
    status: str  # ok | partial | unavailable | error
    duration_ms: float
    error: str | None = None


class ConfidenceBreakdown(BaseModel):
    """Heuristic, evidence-derived confidence. Not a calibrated probability."""

    base: float
    temporal: float
    metric: float
    log: float
    deployment: float
    knowledge: float
    contradictions: float
    coverage_factor: float
    value: float


class Hypothesis(BaseModel):
    id: str
    cause: str  # rule identifier, e.g. deployment_db_regression
    statement: str
    supporting: list[str] = Field(default_factory=list)  # observation / evidence ids
    contradicting: list[str] = Field(default_factory=list)
    contradictions: list[str] = Field(default_factory=list)  # human-readable
    confidence: ConfidenceBreakdown | None = None
    status: HypothesisStatus = "weak"


class TraceStep(BaseModel):
    node: str
    duration_ms: float
    summary: str


class Recommendation(BaseModel):
    action: str
    rationale: str
    requires_human_approval: bool = True
    references: list[str] = Field(default_factory=list)  # citations actually retrieved


class InvestigationReport(BaseModel):
    query: str
    service: str | None
    symptoms: list[str]
    window_minutes: int
    observations: list[Observation]
    evidence: list[RetrievedEvidence]
    hypotheses: list[Hypothesis]
    conclusion: str
    root_cause: str | None  # cause id of the selected hypothesis
    confidence: float
    confidence_breakdown: ConfidenceBreakdown | None
    recommendations: list[Recommendation]
    missing_evidence: list[str]
    tool_calls: list[ToolCall]
    trace: list[TraceStep]
    iterations: int
    llm: dict[str, Any] = Field(default_factory=dict)  # provider/status/summary (labelled)
    completed: bool = True
