"""Unit tests for the investigation agent (deterministic: simulated tools, stub LLM)."""

from __future__ import annotations

import asyncio
import copy
import json
from datetime import timedelta
from pathlib import Path

import pytest

from app.agents import evidence as ev
from app.agents import reasoning
from app.agents.graph import InvestigationAgent
from app.agents.llm import LLMUnavailable, build_llm, extract_service
from app.agents.models import Observation, RetrievedEvidence
from app.agents.simulation import NOW, ScenarioRetriever, ScenarioToolClient
from app.agents.tools import McpToolClient, ToolNotAllowed
from app.config import Settings

CASES = json.loads(
    (Path(__file__).resolve().parents[4] / "tests/evaluation/cases.json").read_text(
        encoding="utf-8"
    )
)
CASE = {c["id"]: c for c in CASES["cases"]}
KNOWLEDGE = CASES["knowledge_sets"]


def settings(**overrides) -> Settings:
    return Settings(_env_file=None, **{"llm_provider": "none", **overrides})


def agent_for(case_id: str, *, llm=None, telemetry_patch=None, **cfg):
    case = copy.deepcopy(CASE[case_id])
    if telemetry_patch:
        case["telemetry"].update(telemetry_patch)
    tools = ScenarioToolClient(case["telemetry"])
    retriever = ScenarioRetriever(KNOWLEDGE.get(case["knowledge"], case["knowledge"]))
    agent = InvestigationAgent(tools, retriever, settings(**cfg), llm=llm, now=lambda: NOW)
    return agent, tools, case


# ---------------------------------------------------------------------------
# Graph transitions and bounds
# ---------------------------------------------------------------------------


async def test_happy_path_visits_each_node_once():
    agent, _, case = agent_for("deploy-db-regression")
    report = await agent.run(case["question"])
    assert [t.node for t in report.trace] == [
        "planner",
        "rag",
        "mcp",
        "hypothesis",
        "validator",
        "synthesizer",
    ]
    assert report.iterations == 1
    assert report.root_cause == "deployment_db_regression"


async def test_insufficient_evidence_triggers_one_bounded_extra_round():
    # Metrics are down, so round one cannot reach the confidence threshold.
    agent, tools, case = agent_for("prometheus-down-logs-only")
    report = await agent.run(case["question"])
    nodes = [t.node for t in report.trace]
    assert nodes.count("mcp") == 2 and nodes.count("validator") == 2
    assert nodes[-1] == "synthesizer"
    # The follow-up round widened the look back for releases and errors.
    assert ("get_recent_deployments", {"service": "checkout", "lookback_hours": 6}) in tools.calls
    assert report.conclusion.startswith("Tentative root cause")


async def test_follow_up_checks_dependency_health():
    agent, _, _ = agent_for("payments-dependency-errors")
    calls = agent._follow_up_calls(
        {
            "service": "checkout",
            "window_minutes": 60,
            "dependencies": ["payments", "users"],
            "tool_results": {},
        }
    )
    assert {"tool": "get_service_health", "arguments": {"service": "payments"}} in calls


async def test_max_iterations_is_respected():
    agent, _, case = agent_for("prometheus-down-logs-only", agent_max_iterations=1)
    report = await agent.run(case["question"])
    assert [t.node for t in report.trace].count("mcp") == 1


async def test_tool_budget_is_enforced():
    agent, tools, case = agent_for("deploy-db-regression", agent_max_tool_calls=3)
    report = await agent.run(case["question"])
    planned_calls = [c for c in tools.calls if c[1].get("query") != "count by (service) (app_info)"]
    assert len(planned_calls) <= 3
    assert any("tool budget exhausted" in m for m in report.missing_evidence)


async def test_wall_clock_timeout():
    class SlowTools(ScenarioToolClient):
        async def call(self, tool, arguments):
            await asyncio.sleep(10)

    agent = InvestigationAgent(
        SlowTools({}), ScenarioRetriever([]), settings(agent_timeout_seconds=5)
    )
    agent.settings.agent_timeout_seconds = 0.2  # below the config floor, for test speed
    with pytest.raises(TimeoutError):
        await agent.run("why is checkout slow")


# ---------------------------------------------------------------------------
# Planner
# ---------------------------------------------------------------------------


async def test_planner_identifies_service_symptoms_and_plan():
    agent, _, _ = agent_for("deploy-db-regression")
    update, _ = await agent.planner(
        {"query": "Why is CHECKOUT latency up?", "window_minutes": 30, "llm": {}, "missing": []}
    )
    assert update["service"] == "checkout"
    assert update["symptoms"] == ["latency"]
    tools = [c["tool"] for c in update["plan"]]
    assert {"get_service_health", "get_recent_deployments", "get_recent_logs"} <= set(tools)
    db_query = [c for c in update["plan"] if "db_query_seconds" in c["arguments"].get("query", "")]
    assert db_query, "latency questions also look at database latency"


async def test_planner_error_questions_plan_error_metrics():
    agent, _, _ = agent_for("users-app-errors-no-release")
    update, _ = await agent.planner(
        {"query": "users is returning 500 errors", "window_minutes": 60, "llm": {}, "missing": []}
    )
    assert update["symptoms"] == ["errors"]
    assert any("http_errors" in c["arguments"].get("query", "") for c in update["plan"])


async def test_explicit_service_overrides_query_matching():
    agent, _, _ = agent_for("deploy-db-regression")
    report = await agent.run("something is wrong", service="checkout")
    assert report.service == "checkout"


async def test_unknown_service_stops_without_calling_tools():
    agent, tools, case = agent_for("unknown-service")
    report = await agent.run(case["question"])
    assert report.service is None and report.root_cause is None
    assert [name for name, _ in tools.calls] == ["query_metrics"]  # only the service list
    assert any("could not identify" in m for m in report.missing_evidence)


# ---------------------------------------------------------------------------
# Evidence aggregation
# ---------------------------------------------------------------------------


def series(values: list[float]) -> list[dict]:
    return [
        {"timestamp": (NOW - timedelta(minutes=len(values) - i)).isoformat(), "value": v}
        for i, v in enumerate(values)
    ]


def test_step_change_detects_latest_sustained_step():
    step = ev.step_change(series([0.2] * 10 + [2.0] * 5), 2.0, 0.5)
    assert step["baseline"] == 0.2 and step["current"] == 2.0
    assert step["start"] == ev.parse_ts(series([0.2] * 10 + [2.0] * 5)[10]["timestamp"])


def test_step_change_ignores_recovered_blip_and_flat_series():
    assert ev.step_change(series([0.2] * 5 + [2.0] * 3 + [0.2] * 5), 2.0, 0.5) is None
    assert ev.step_change(series([0.2] * 12), 2.0, 0.5) is None
    assert ev.step_change(series([2.0] * 12), 2.0, 0.5) is None  # no baseline to compare


def test_step_change_uses_most_recent_incident():
    values = [0.2] * 5 + [2.0] * 3 + [0.2] * 5 + [2.5] * 4
    step = ev.step_change(series(values), 2.0, 0.5)
    assert step["current"] == 2.5
    assert step["start"] == ev.parse_ts(series(values)[13]["timestamp"])


def test_log_extraction_counts_and_thresholds():
    facts = ev.Facts()
    entries = [
        {"message": "slow_query_detected", "metadata": {"operation": "q", "query_time_ms": 900}}
    ] * 5
    entries += [
        {"message": "dependency_error", "metadata": {"target": "payments"}}
    ] * 2  # below threshold
    ev.extract_logs(facts, "checkout", {"status": "ok", "entries": entries})
    assert [o.signals for o in facts.observations] == [["db_slow_logs"]]
    assert "5 slow_query_detected" in facts.observations[0].statement


def test_unavailable_results_produce_missing_notes_not_facts():
    facts = ev.Facts()
    result = {"status": "unavailable", "errors": [{"error": "logs_unavailable", "detail": "down"}]}
    ev.extract_logs(facts, "checkout", result)
    assert facts.observations == []
    assert facts.missing == ["get_recent_logs: logs_unavailable (down)"]


def test_duplicate_facts_are_merged():
    facts = ev.Facts()
    facts.add("deployment", "checkout version 2 was first observed at 10:00:00 UTC", "t")
    facts.add("deployment", "checkout version 2 was first observed at 10:00:04 UTC", "t")
    assert len(facts.observations) == 1


# ---------------------------------------------------------------------------
# Validator and confidence
# ---------------------------------------------------------------------------


def obs(i: int, *signals: str, minutes_ago: int | None = None, **data) -> Observation:
    at = NOW - timedelta(minutes=minutes_ago) if minutes_ago is not None else None
    return Observation(
        id=f"F{i}",
        kind="metric",
        statement=f"fact {i}",
        source="t",
        at=at,
        signals=list(signals),
        data=data,
    )


def test_confidence_formula_full_evidence():
    observations = [
        obs(1, "symptom_latency", "latency_step", minutes_ago=10),
        obs(2, "deploy_recent", minutes_ago=12, version="1.8.2"),
        obs(3, "db_latency_rise", minutes_ago=10),
        obs(4, "db_slow_logs"),
    ]
    knowledge = [
        RetrievedEvidence(
            id="K1",
            citation="a#chunk-0",
            title="Postmortem",
            section="Root cause",
            score=0.8,
            excerpt="a slow query regression; roll back",
        )
    ]
    [h] = [
        x
        for x in reasoning.generate_hypotheses(observations, "checkout")
        if x.cause == "deployment_db_regression"
    ]
    v = reasoning.validate(h, observations, knowledge, coverage=1.0)
    b = v.confidence
    assert (b.base, b.temporal, b.metric, b.log, b.deployment, b.knowledge) == (
        0.1,
        0.25,
        0.25,
        0.2,
        0.1,
        0.1,
    )
    assert b.value == reasoning.CEILING  # 1.0 raw, capped: never certainty
    assert v.status == "supported"
    assert v.statement == "Release 1.8.2 of checkout introduced a database query regression"


def test_missing_sources_reduce_confidence():
    observations = [
        obs(1, "symptom_latency", "latency_step", minutes_ago=5),
        obs(2, "db_slow_logs"),
    ]
    [h] = [x for x in reasoning.generate_hypotheses(observations, "checkout")]
    full = reasoning.validate(h, observations, [], coverage=1.0).confidence.value
    half = reasoning.validate(h, observations, [], coverage=0.5).confidence.value
    assert half == pytest.approx(full * 0.8 / 1.0)


def test_release_after_onset_is_a_contradiction():
    observations = [
        obs(1, "symptom_latency", "latency_step", minutes_ago=40),
        obs(2, "deploy_recent", minutes_ago=10, version="1.8.2"),
        obs(3, "db_latency_rise", minutes_ago=40),
    ]
    hyps = {
        h.cause: reasoning.validate(h, observations, [], 1.0)
        for h in reasoning.generate_hypotheses(observations, "checkout")
    }
    deploy = hyps["deployment_db_regression"]
    assert deploy.contradictions and deploy.confidence.contradictions == -0.25
    assert reasoning.rank(list(hyps.values()))[0].cause == "database_degradation"


def test_healthy_dependencies_contradict_dependency_hypothesis():
    observations = [
        obs(1, "symptom_errors"),
        obs(2, "dependency_errors", targets={"payments": 5}),
        obs(3, "dependencies_healthy"),
    ]
    [h] = reasoning.generate_hypotheses(observations, "checkout")
    v = reasoning.validate(h, observations, [], 1.0)
    assert v.contradicting == ["F3"]
    assert v.statement == "Dependency payments of checkout is failing or slow"


def test_flagged_knowledge_never_adds_confidence():
    observations = [obs(1, "symptom_latency"), obs(2, "db_slow_logs")]
    poisoned = [
        RetrievedEvidence(
            id="K1",
            citation="evil#chunk-0",
            title="db slow query",
            section=None,
            score=0.9,
            excerpt="query slow",
            flags=["possible_prompt_injection"],
        )
    ]
    [h] = reasoning.generate_hypotheses(observations, "checkout")
    assert reasoning.validate(h, observations, poisoned, 1.0).confidence.knowledge == 0.0


def test_sufficiency_ignores_subsumed_hypotheses():
    observations = [
        obs(1, "symptom_latency", "latency_step", minutes_ago=10),
        obs(2, "deploy_recent", minutes_ago=12, version="1"),
        obs(3, "db_latency_rise", minutes_ago=10),
        obs(4, "db_slow_logs"),
    ]
    ranked = reasoning.rank(
        [
            reasoning.validate(h, observations, [], 1.0)
            for h in reasoning.generate_hypotheses(observations, "checkout")
        ]
    )
    assert ranked[0].cause == "deployment_db_regression"
    assert reasoning.is_sufficient(ranked)


# ---------------------------------------------------------------------------
# Synthesis, recommendations, safety
# ---------------------------------------------------------------------------


async def test_report_separates_facts_evidence_hypotheses_and_recommendations():
    agent, _, case = agent_for("deploy-db-regression")
    report = await agent.run(case["question"])
    assert report.observations and report.evidence and report.hypotheses
    assert report.conclusion.startswith("Most likely root cause: Release 1.8.2")
    rollback = report.recommendations[0]
    assert rollback.action == "Roll back checkout from 1.8.2 to 1.8.1"
    assert rollback.requires_human_approval
    retrieved = {e.citation for e in report.evidence}
    assert all(ref in retrieved for rec in report.recommendations for ref in rec.references)


async def test_mcp_unavailable_is_reported_as_missing_evidence():
    agent, _, case = agent_for(
        "deploy-db-regression", telemetry_patch={"unavailable": ["prometheus"], "logs": {}}
    )
    report = await agent.run(case["question"], service="checkout")
    assert report.root_cause is None
    assert any("prometheus_unavailable" in m for m in report.missing_evidence)
    assert "No root cause" in report.conclusion


async def test_allow_list_blocks_unknown_tools():
    with pytest.raises(ToolNotAllowed):
        await McpToolClient(None).call("run_shell", {"command": "rm -rf /"})
    unavailable = await McpToolClient(None).call("get_service_health", {"service": "checkout"})
    assert unavailable["status"] == "unavailable"


async def test_poisoned_knowledge_does_not_change_the_diagnosis():
    agent, tools, case = agent_for("poisoned-knowledge")
    report = await agent.run(case["question"])
    assert report.root_cause == "database_degradation"
    assert any("possible_prompt_injection" in e.flags for e in report.evidence)
    assert all(name != "restart_database" for name, _ in tools.calls)


# ---------------------------------------------------------------------------
# Optional LLM (stubbed)
# ---------------------------------------------------------------------------


class StubLLM:
    name = "stub:test"

    def __init__(self, reply: str = "Summary.", fail: bool = False) -> None:
        self.reply, self.fail, self.prompts = reply, fail, []

    async def complete(self, system: str, user: str, max_tokens: int = 400) -> str:
        self.prompts.append((system, user))
        if self.fail:
            raise LLMUnavailable("LLM request failed: ConnectError")
        return self.reply


async def test_llm_summary_is_labelled_and_does_not_change_the_result():
    plain, _, case = agent_for("deploy-db-regression")
    with_llm, _, _ = agent_for(
        "deploy-db-regression", llm=StubLLM("Checkout regressed after 1.8.2.")
    )
    a, b = await plain.run(case["question"]), await with_llm.run(case["question"])
    assert (a.root_cause, a.confidence) == (b.root_cause, b.confidence)
    assert b.llm["summary_label"] == "model-written summary, not evidence"
    assert b.llm["provider"] == "stub:test"


async def test_llm_failure_degrades_gracefully():
    agent, _, case = agent_for("deploy-db-regression", llm=StubLLM(fail=True))
    report = await agent.run(case["question"])
    assert report.root_cause == "deployment_db_regression"
    assert report.llm["status"] == "unavailable"


async def test_llm_service_extraction_only_accepts_known_services():
    assert await extract_service(StubLLM("Checkout."), "q", ["checkout", "users"]) == "checkout"
    assert await extract_service(StubLLM("rm -rf"), "q", ["checkout"]) is None


def test_llm_provider_configuration():
    assert build_llm(settings()) is None
    assert build_llm(settings(llm_provider="openai")) is None  # no key: deterministic mode
    llm = build_llm(settings(llm_provider="anthropic", llm_api_key="k", llm_model="m"))
    assert llm.name == "anthropic:m"
