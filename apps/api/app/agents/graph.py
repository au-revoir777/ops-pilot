"""The investigation agent: an explicit, bounded LangGraph state machine.

    START -> planner -> rag -> mcp -> hypothesis -> validator --sufficient--> synthesizer -> END
                                ^                       |
                                +---- insufficient -----+   (at most AGENT_MAX_ITERATIONS rounds)

Bounds: a LangGraph recursion limit, a maximum number of evidence rounds, a
maximum number of tool calls, and a wall-clock timeout. There is no open-ended
"keep thinking" loop: every node does one fixed job and the only cycle is the
validator asking for one more, pre-defined round of evidence.
"""

from __future__ import annotations

import asyncio
import math
import re
import time
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol, TypedDict

import structlog
from langgraph.graph import END, START, StateGraph

from app.agents import evidence as ev
from app.agents import reasoning
from app.agents.llm import LLM, SUMMARY_SYSTEM, LLMUnavailable, extract_service
from app.agents.models import (
    Hypothesis,
    InvestigationReport,
    Observation,
    RetrievedEvidence,
    ToolCall,
    TraceStep,
)
from app.agents.tools import ToolClient
from app.config import Settings
from app.metrics import AGENT_EXECUTION_DURATION
from app.rag.retrieval import RetrievedChunk

logger = structlog.get_logger(__name__)

LATENCY_WORDS = re.compile(r"\b(latenc\w*|slow\w*|p9\d|timeouts?|lag\w*|response time)\b", re.I)
ERROR_WORDS = re.compile(r"\b(errors?|5\d\d|fail\w*|exceptions?|crash\w*|outage)\b", re.I)


class KnowledgeRetriever(Protocol):
    async def retrieve(self, query: str, services: list[str] | None) -> list[RetrievedChunk]: ...


class AgentState(TypedDict, total=False):
    query: str
    service: str | None
    symptoms: list[str]
    window_minutes: int
    iteration: int
    plan: list[dict[str, Any]]  # pending tool calls: {"tool": ..., "arguments": {...}}
    tool_results: dict[str, dict[str, Any]]  # keyed by "tool:json-args"
    tool_calls: list[ToolCall]
    retrieved: list[RetrievedEvidence]
    observations: list[Observation]
    missing: list[str]
    dependencies: list[str]
    hypotheses: list[Hypothesis]
    next_action: str
    trace: list[TraceStep]
    report: InvestigationReport
    llm: dict[str, Any]


def _key(call: dict[str, Any]) -> str:
    args = ",".join(f"{k}={call['arguments'][k]}" for k in sorted(call["arguments"]))
    return f"{call['tool']}({args})"


class InvestigationAgent:
    def __init__(
        self,
        tools: ToolClient,
        retriever: KnowledgeRetriever,
        settings: Settings,
        llm: LLM | None = None,
        now: Any = None,
    ) -> None:
        self.tools = tools
        self.retriever = retriever
        self.settings = settings
        self.llm = llm
        self.now = now or (lambda: datetime.now(UTC))
        self.graph = self._build()

    # ------------------------------------------------------------------ graph

    def _build(self):
        graph = StateGraph(AgentState)
        graph.add_node("planner", self._timed("planner", self.planner))
        graph.add_node("rag", self._timed("rag", self.rag))
        graph.add_node("mcp", self._timed("mcp", self.mcp))
        graph.add_node("hypothesis", self._timed("hypothesis", self.hypothesis))
        graph.add_node("validator", self._timed("validator", self.validator))
        graph.add_node("synthesizer", self._timed("synthesizer", self.synthesizer))
        graph.add_edge(START, "planner")
        graph.add_conditional_edges(
            "planner",
            lambda s: s["next_action"],
            {"investigate": "rag", "synthesize": "synthesizer"},
        )
        graph.add_edge("rag", "mcp")
        graph.add_edge("mcp", "hypothesis")
        graph.add_edge("hypothesis", "validator")
        graph.add_conditional_edges(
            "validator",
            lambda s: s["next_action"],
            {"more_evidence": "mcp", "synthesize": "synthesizer"},
        )
        graph.add_edge("synthesizer", END)
        return graph.compile()

    def _timed(self, name: str, fn):
        async def node(state: AgentState) -> dict[str, Any]:
            start = time.perf_counter()
            update, summary = await fn(state)
            step = TraceStep(
                node=name,
                duration_ms=round((time.perf_counter() - start) * 1000, 1),
                summary=summary,
            )
            update["trace"] = [*state.get("trace", []), step]
            if "report" in update:  # the synthesizer's own step belongs in the report too
                update["report"].trace = update["trace"]
            logger.info("agent_step", node=name, summary=summary, duration_ms=step.duration_ms)
            return update

        return node

    async def run(
        self, query: str, service: str | None = None, window_minutes: int | None = None
    ) -> InvestigationReport:
        started = time.perf_counter()
        initial: AgentState = {
            "query": query.strip(),
            "service": service,
            "window_minutes": window_minutes or self.settings.agent_window_minutes,
            "iteration": 0,
            "tool_results": {},
            "tool_calls": [],
            "retrieved": [],
            "observations": [],
            "missing": [],
            "trace": [],
            "llm": {"provider": self.llm.name if self.llm else "none", "status": "not_used"},
        }
        outcome = "error"
        try:
            final = await asyncio.wait_for(
                self.graph.ainvoke(initial, {"recursion_limit": self.settings.agent_max_steps}),
                timeout=self.settings.agent_timeout_seconds,
            )
            report = final["report"]
            outcome = "completed" if report.root_cause else "inconclusive"
            return report
        except TimeoutError:
            outcome = "timeout"
            raise
        finally:
            AGENT_EXECUTION_DURATION.labels(outcome=outcome).observe(time.perf_counter() - started)

    # ------------------------------------------------------------------ nodes

    async def planner(self, state: AgentState) -> tuple[dict[str, Any], str]:
        query = state["query"]
        service = state.get("service")
        update: dict[str, Any] = {}
        if not service:
            known = await self._known_services()
            if not known:
                # Metrics unavailable: fall back to service names attached to
                # knowledge-base documents that match the question.
                known = await self._services_from_knowledge(query)
            service = next(
                (
                    s
                    for s in sorted(known, key=len, reverse=True)
                    if re.search(rf"\b{re.escape(s)}\b", query, re.I)
                ),
                None,
            )
            if service is None and self.llm and known:
                try:
                    service = await extract_service(self.llm, query, known)
                    update["llm"] = {
                        **state["llm"],
                        "status": "used",
                        "service_extraction": service or "none",
                    }
                except LLMUnavailable as exc:
                    update["llm"] = {**state["llm"], "status": "unavailable", "error": str(exc)}
        symptoms = [
            name
            for name, pattern in (("latency", LATENCY_WORDS), ("errors", ERROR_WORDS))
            if pattern.search(query)
        ]
        if service is None:
            missing = [
                *state.get("missing", []),
                "could not identify which service the question is about",
            ]
            return {
                **update,
                "service": None,
                "symptoms": symptoms,
                "missing": missing,
                "next_action": "synthesize",
            }, "no service identified"

        window = state["window_minutes"]
        plan = [
            {"tool": "get_service_health", "arguments": {"service": service}},
            {"tool": "get_incident_events", "arguments": {"service": service, "minutes": window}},
            {
                "tool": "get_recent_deployments",
                "arguments": {
                    "service": service,
                    "lookback_hours": max(1, math.ceil(window / 60) + 1),
                },
            },
            {"tool": "get_service_dependencies", "arguments": {"service": service}},
            {
                "tool": "query_metrics",
                "arguments": {
                    "query": f'max(service:http_latency_seconds:p95_1m{{service="{service}"}})',
                    "start_time": f"now-{window}m",
                },
            },
            {
                "tool": "get_recent_logs",
                "arguments": {
                    "service": service,
                    "minutes": window,
                    "severity": "warning",
                    "limit": 200,
                },
            },
        ]
        if "errors" in symptoms or not symptoms:
            plan.append(
                {
                    "tool": "query_metrics",
                    "arguments": {
                        "query": f'max(service:http_errors:ratio_rate1m{{service="{service}"}})',
                        "start_time": f"now-{window}m",
                    },
                }
            )
        if "latency" in symptoms or not symptoms:
            plan.append(
                {
                    "tool": "query_metrics",
                    "arguments": {
                        "query": "max(service_operation:db_query_seconds:p95_1m"
                        f'{{service="{service}"}})',
                        "start_time": f"now-{window}m",
                    },
                }
            )
        return (
            {
                **update,
                "service": service,
                "symptoms": symptoms,
                "plan": plan,
                "next_action": "investigate",
            },
            f"service={service}, symptoms={symptoms or ['unspecified']}, "
            f"{len(plan)} tool calls planned",
        )

    async def rag(self, state: AgentState) -> tuple[dict[str, Any], str]:
        service = state["service"]
        symptom = " and ".join(state.get("symptoms") or ["problems"])
        queries = [state["query"], f"{service} {symptom} troubleshooting root cause"]
        retrieved: list[RetrievedEvidence] = []
        seen: set[str] = set()
        missing = list(state.get("missing", []))
        for query in queries:
            try:
                chunks = await self.retriever.retrieve(query, [service])
            except Exception as exc:  # RetrievalUnavailable and friends
                missing.append(f"knowledge base: unavailable ({type(exc).__name__})")
                break
            for chunk in chunks:
                if chunk.citation in seen:
                    continue
                seen.add(chunk.citation)
                retrieved.append(
                    RetrievedEvidence(
                        id=f"K{len(retrieved) + 1}",
                        citation=chunk.citation,
                        title=chunk.title,
                        section=chunk.section,
                        score=chunk.score,
                        excerpt=chunk.content[:600],
                        flags=chunk.flags,
                    )
                )
        return {
            "retrieved": retrieved,
            "missing": missing,
        }, f"{len(retrieved)} knowledge passages retrieved"

    async def mcp(self, state: AgentState) -> tuple[dict[str, Any], str]:
        results = dict(state.get("tool_results", {}))
        calls = list(state.get("tool_calls", []))
        budget = self.settings.agent_max_tool_calls - len(calls)
        pending = [c for c in state.get("plan", []) if _key(c) not in results][: max(0, budget)]

        async def run(call: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any], float]:
            start = time.perf_counter()
            result = await self.tools.call(call["tool"], call["arguments"])
            return call, result, (time.perf_counter() - start) * 1000

        for call, result, ms in await asyncio.gather(*(run(c) for c in pending)):
            results[_key(call)] = result
            errors = result.get("errors") or []
            calls.append(
                ToolCall(
                    tool=call["tool"],
                    arguments=call["arguments"],
                    status=result.get("status", "ok"),
                    duration_ms=round(ms, 1),
                    error=errors[0].get("error") if errors else None,
                )
            )

        observations, missing, dependencies = self._extract(state, results)
        skipped = len([c for c in state.get("plan", []) if _key(c) not in results])
        if skipped:
            missing.append(f"tool budget exhausted: {skipped} planned calls skipped")
        return (
            {
                "tool_results": results,
                "tool_calls": calls,
                "observations": observations,
                "missing": [*self._base_missing(state), *missing],
                "dependencies": dependencies,
            },
            f"{len(pending)} tool calls, {len(observations)} observations",
        )

    async def hypothesis(self, state: AgentState) -> tuple[dict[str, Any], str]:
        hypotheses = reasoning.generate_hypotheses(state["observations"], state["service"])
        return {"hypotheses": hypotheses}, f"{len(hypotheses)} hypotheses: " + (
            ", ".join(h.cause for h in hypotheses) or "none"
        )

    async def validator(self, state: AgentState) -> tuple[dict[str, Any], str]:
        coverage = self._coverage(state)
        validated = [
            reasoning.validate(h, state["observations"], state["retrieved"], coverage)
            for h in state["hypotheses"]
        ]
        ranked = reasoning.rank(validated)
        iteration = state.get("iteration", 0) + 1
        sufficient = reasoning.is_sufficient(ranked)
        can_expand = iteration < self.settings.agent_max_iterations
        extra = self._follow_up_calls(state) if not sufficient and can_expand else []
        next_action = "more_evidence" if extra else "synthesize"
        best = ranked[0] if ranked else None
        summary = (
            f"round {iteration}: best={best.cause if best else 'none'} "
            f"({best.confidence.value if best and best.confidence else 0:.2f}), "
            f"{'sufficient' if sufficient else 'insufficient'} -> {next_action}"
        )
        return (
            {
                "hypotheses": ranked,
                "iteration": iteration,
                "next_action": next_action,
                "plan": [*state.get("plan", []), *extra],
            },
            summary,
        )

    async def synthesizer(self, state: AgentState) -> tuple[dict[str, Any], str]:
        service = state.get("service")
        hypotheses = state.get("hypotheses", [])
        observations = state.get("observations", [])
        retrieved = state.get("retrieved", [])
        best = hypotheses[0] if hypotheses else None
        accepted = (
            best
            if best
            and best.confidence
            and best.status != "rejected"
            and best.confidence.value >= reasoning.MIN_REPORTABLE_CONFIDENCE
            else None
        )

        if accepted:
            support = ", ".join(accepted.supporting)
            label = (
                "Most likely root cause"
                if accepted.confidence.value >= reasoning.TENTATIVE_BELOW
                else "Tentative root cause (low confidence; key evidence is missing)"
            )
            conclusion = (
                f"{label}: {accepted.statement} "
                f"(confidence {accepted.confidence.value:.0%}, heuristic). Supported by {support}."
            )
            if accepted.contradictions:
                conclusion += " Contradicting evidence: " + "; ".join(accepted.contradictions) + "."
        elif service is None:
            conclusion = "Could not identify the service to investigate; please name it."
        else:
            conclusion = (
                f"No root cause for {service} could be established from the available evidence."
            )
        llm_info = dict(state.get("llm", {}))
        report = InvestigationReport(
            query=state["query"],
            service=service,
            symptoms=state.get("symptoms", []),
            window_minutes=state["window_minutes"],
            observations=observations,
            evidence=retrieved,
            hypotheses=hypotheses,
            conclusion=conclusion,
            root_cause=accepted.cause if accepted else None,
            confidence=accepted.confidence.value if accepted else 0.0,
            confidence_breakdown=accepted.confidence if accepted else None,
            recommendations=reasoning.recommend(
                accepted, observations, retrieved, service or "the service"
            ),
            missing_evidence=list(dict.fromkeys(state.get("missing", []))),
            tool_calls=state.get("tool_calls", []),
            trace=state.get("trace", []),
            iterations=state.get("iteration", 0),
            llm=llm_info,
        )
        if self.llm and service:
            report.llm = await self._summarise(report, llm_info)
        return {"report": report}, conclusion[:160]

    # ----------------------------------------------------------- internals

    async def _known_services(self) -> list[str]:
        result = await self.tools.call(
            "query_metrics", {"query": "count by (service) (app_info)", "start_time": "now-15m"}
        )
        return sorted({s["metric"].get("service") for s in result.get("series") or []} - {None})

    async def _services_from_knowledge(self, query: str) -> list[str]:
        try:
            chunks = await self.retriever.retrieve(query, None)
        except Exception:  # knowledge base down too: nothing to fall back on
            return []
        return sorted({s for c in chunks for s in c.services})

    def _extract(self, state: AgentState, results: dict[str, dict[str, Any]]):
        service = state["service"]
        facts = ev.Facts()
        window_start = self.now() - timedelta(minutes=state["window_minutes"])
        thresholds = {
            "p95_ms": self.settings.agent_degraded_p95_ms,
            "error_ratio": self.settings.agent_degraded_error_ratio,
        }
        dependencies: list[str] = []
        for key, result in results.items():
            tool = key.split("(", 1)[0]
            if tool == "get_service_health" and f"service={service}" in key:
                ev.extract_health(facts, service, result, thresholds)
            elif tool == "get_service_health":
                dependency = key.split("service=", 1)[1].rstrip(")")
                ev.extract_dependency_health(facts, dependency, result)
            elif tool == "query_metrics" and "http_latency_seconds" in key:
                ev.extract_latency_history(facts, service, result)
            elif tool == "query_metrics" and "db_query_seconds" in key:
                ev.extract_db_history(facts, service, result)
            elif tool == "query_metrics" and "http_errors" in key:
                ev.extract_error_history(facts, service, result)
            elif tool == "get_recent_logs":
                ev.extract_logs(facts, service, result)
            elif tool == "get_recent_deployments":
                ev.extract_deployments(facts, service, result, window_start)
            elif tool == "get_incident_events":
                ev.extract_events(facts, service, result)
            elif tool == "get_service_dependencies":
                dependencies = ev.extract_dependencies(facts, service, result)
        return facts.observations, facts.missing, dependencies

    def _base_missing(self, state: AgentState) -> list[str]:
        return [
            m for m in state.get("missing", []) if m.startswith(("knowledge base", "could not"))
        ]

    def _coverage(self, state: AgentState) -> float:
        results = state.get("tool_results", {})
        if not results:
            return 0.0
        ok = sum(1 for r in results.values() if r.get("status") in {"ok", "partial"})
        knowledge = (
            0 if any(m.startswith("knowledge base") for m in state.get("missing", [])) else 1
        )
        return (ok + knowledge) / (len(results) + 1)

    def _follow_up_calls(self, state: AgentState) -> list[dict[str, Any]]:
        """One pre-defined round of extra evidence: dependencies and a wider look back."""
        service, window = state["service"], state["window_minutes"]
        calls = [
            {"tool": "get_service_health", "arguments": {"service": dep}}
            for dep in state.get("dependencies", [])[:3]
        ]
        calls += [
            {
                "tool": "get_recent_deployments",
                "arguments": {"service": service, "lookback_hours": 6},
            },
            {
                "tool": "get_recent_logs",
                "arguments": {
                    "service": service,
                    "minutes": min(window * 2, 360),
                    "severity": "error",
                    "limit": 200,
                },
            },
        ]
        done = set(state.get("tool_results", {}))
        return [c for c in calls if _key(c) not in done]

    async def _summarise(
        self, report: InvestigationReport, llm_info: dict[str, Any]
    ) -> dict[str, Any]:
        facts = "\n".join(f"{o.id}: {o.statement}" for o in report.observations)
        user = (
            f"Question: {report.query}\nFacts:\n{facts or '(none)'}\n"
            f"Conclusion: {report.conclusion}\n"
            f"Missing evidence: {report.missing_evidence or 'none'}"
        )
        try:
            summary = await self.llm.complete(SUMMARY_SYSTEM, user)
            return {
                **llm_info,
                "status": "used",
                "summary": summary,
                "summary_label": "model-written summary, not evidence",
            }
        except LLMUnavailable as exc:
            return {**llm_info, "status": "unavailable", "error": str(exc)}
