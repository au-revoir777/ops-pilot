"""Agent evaluation suite (marker: evaluation).

    pytest -m evaluation tests/evaluation/test_agent_evaluation.py

Runs every scenario in app/agents/scenarios/cases.json through the real agent graph (simulated
MCP/RAG results, no LLM) and writes machine-readable results to
tests/evaluation/results/latest.json.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

import pytest

from app.agents.evaluation import evaluate
from app.agents.simulation import CASES_FILE

pytestmark = pytest.mark.evaluation

HERE = Path(__file__).parent


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
