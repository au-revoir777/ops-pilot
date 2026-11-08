"""Agent evaluation: run every scenario through the real graph and score it.

    python -m app.agents.evaluation [--cases app/agents/scenarios/cases.json] \
        --output ../../tests/evaluation/results/latest.json

Metrics (spec section 24), all computed from actual runs:
  root_cause_accuracy    report.root_cause == expected (null expected = must not claim one)
  service_accuracy       identified service == expected
  evidence_grounding     share of required evidence signals present in the observations
  tool_selection         share of cases where every tool called was acceptable
  unsupported_claim_rate share of claims (ids cited in hypotheses/conclusion and
                         recommendation references) that do not resolve to an
                         observation or a passage actually retrieved
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from app.agents.graph import InvestigationAgent
from app.agents.models import InvestigationReport
from app.agents.simulation import CASES_FILE, NOW, ScenarioRetriever, ScenarioToolClient
from app.config import Settings


@dataclass
class CaseResult:
    id: str
    passed: bool
    expected_root_cause: str | None
    actual_root_cause: str | None
    expected_service: str | None
    actual_service: str | None
    confidence: float
    evidence_grounding: float
    tools_ok: bool
    tools_called: list[str]
    unsupported_claims: list[str]
    total_claims: int
    missing_evidence: list[str] = field(default_factory=list)


@dataclass
class EvaluationSummary:
    cases: int
    root_cause_accuracy: float
    service_accuracy: float
    evidence_grounding: float
    tool_selection: float
    unsupported_claim_rate: float
    results: list[CaseResult]


def claims(report: InvestigationReport) -> tuple[list[str], list[str]]:
    """All claims and those that do not resolve to real evidence."""
    known_ids = {o.id for o in report.observations} | {e.id for e in report.evidence}
    retrieved = {e.citation for e in report.evidence}
    cited = [i for h in report.hypotheses for i in h.supporting + h.contradicting]
    refs = [r for rec in report.recommendations for r in rec.references]
    unsupported = [i for i in cited if i not in known_ids] + [r for r in refs if r not in retrieved]
    return cited + refs, unsupported


def score(case: dict[str, Any], report: InvestigationReport, tools_called: list[str]) -> CaseResult:
    signals = {s for o in report.observations for s in o.signals}
    required = case.get("required_evidence", [])
    grounding = sum(1 for r in required if r in signals) / len(required) if required else 1.0
    tools_ok = all(t in case["acceptable_tools"] for t in tools_called)
    all_claims, unsupported = claims(report)
    root_ok = report.root_cause == case["expected_root_cause"]
    service_ok = report.service == case["expected_service"]
    return CaseResult(
        id=case["id"],
        passed=root_ok and service_ok and tools_ok and not unsupported and grounding == 1.0,
        expected_root_cause=case["expected_root_cause"],
        actual_root_cause=report.root_cause,
        expected_service=case["expected_service"],
        actual_service=report.service,
        confidence=report.confidence,
        evidence_grounding=round(grounding, 3),
        tools_ok=tools_ok,
        tools_called=sorted(set(tools_called)),
        unsupported_claims=unsupported,
        total_claims=len(all_claims),
        missing_evidence=report.missing_evidence,
    )


async def run_case(
    case: dict[str, Any], knowledge_sets: dict[str, Any], settings: Settings
) -> CaseResult:
    tools = ScenarioToolClient(case["telemetry"])
    knowledge = case.get("knowledge")
    retriever = ScenarioRetriever(knowledge_sets.get(knowledge, knowledge))
    agent = InvestigationAgent(tools, retriever, settings, llm=None, now=lambda: NOW)
    report = await agent.run(case["question"], window_minutes=60)
    return score(case, report, [name for name, _ in tools.calls])


async def evaluate(cases_file: Path, settings: Settings | None = None) -> EvaluationSummary:
    data = json.loads(cases_file.read_text(encoding="utf-8"))
    settings = settings or Settings(_env_file=None, llm_provider="none")
    results = [await run_case(c, data.get("knowledge_sets", {}), settings) for c in data["cases"]]
    n = len(results)
    total_claims = sum(r.total_claims for r in results) or 1
    return EvaluationSummary(
        cases=n,
        root_cause_accuracy=round(
            sum(r.actual_root_cause == r.expected_root_cause for r in results) / n, 3
        ),
        service_accuracy=round(sum(r.actual_service == r.expected_service for r in results) / n, 3),
        evidence_grounding=round(sum(r.evidence_grounding for r in results) / n, 3),
        tool_selection=round(sum(r.tools_ok for r in results) / n, 3),
        unsupported_claim_rate=round(
            sum(len(r.unsupported_claims) for r in results) / total_claims, 4
        ),
        results=results,
    )


def main() -> None:
    import structlog

    structlog.configure(logger_factory=structlog.PrintLoggerFactory(sys.stderr))
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("--cases", type=Path, default=CASES_FILE)
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()
    summary = asdict(asyncio.run(evaluate(args.cases)))
    text = json.dumps(summary, indent=2, default=str)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
    print(text)  # noqa: T201 - CLI output


if __name__ == "__main__":
    main()
