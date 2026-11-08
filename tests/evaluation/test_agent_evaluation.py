"""Agent evaluation suite (marker: evaluation).

    pytest -m evaluation tests/evaluation/test_agent_evaluation.py

Every scenario in app/agents/scenarios/cases.json runs through the real agent
graph (simulated MCP/RAG results on a fixed clock, no LLM), so results are
deterministic. Each scenario is its own test, so a regression names the
incident type it broke; the suite test then checks the aggregate thresholds and
writes machine-readable results to tests/evaluation/results/latest.json.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

import pytest

from app.agents.evaluation import evaluate, run_case
from app.agents.simulation import CASES_FILE, load_cases
from app.config import Settings

pytestmark = pytest.mark.evaluation

HERE = Path(__file__).parent
DATA = load_cases()
SETTINGS = Settings(_env_file=None, llm_provider="none")


@pytest.mark.parametrize("case", DATA["cases"], ids=[c["id"] for c in DATA["cases"]])
async def test_scenario(case):
    result = await run_case(case, DATA["knowledge_sets"], SETTINGS)
    assert result.actual_root_cause == case["expected_root_cause"], result.missing_evidence
    assert result.actual_service == case["expected_service"]
    assert result.tools_ok, result.tools_called
    assert result.unsupported_claims == []
    assert result.evidence_grounding == 1.0


async def test_scenarios_are_deterministic():
    """Same scenario twice -> the same diagnosis, confidence and evidence."""
    case = next(c for c in DATA["cases"] if c["id"] == "deploy-db-regression")
    first = await run_case(case, DATA["knowledge_sets"], SETTINGS)
    second = await run_case(case, DATA["knowledge_sets"], SETTINGS)
    assert asdict(first) == asdict(second)


async def test_agent_evaluation_suite():
    summary = await evaluate(CASES_FILE)
    out = HERE / "results" / "latest.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(asdict(summary), indent=2, default=str), encoding="utf-8")

    assert summary.cases >= 10
    failures = [r.id for r in summary.results if not r.passed]
    assert summary.root_cause_accuracy >= 0.9, failures
    assert summary.service_accuracy >= 0.9, failures
    assert summary.evidence_grounding >= 0.9, failures
    assert summary.tool_selection == 1.0, failures
    assert summary.unsupported_claim_rate == 0.0, failures
