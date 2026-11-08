"""Incident replay: run the real agent against a recorded scenario.

GET  /api/replays            the scenario catalogue (question, expected service/root cause)
POST /api/replays/{case_id}  run the agent on the scenario's recorded telemetry and
                             compare its diagnosis with the expected root cause

Replays use only the telemetry and documents recorded in the scenario (what was
available during the simulated incident). Nothing is written to the database.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel

from app.agents.graph import InvestigationAgent
from app.agents.simulation import NOW, ScenarioRetriever, ScenarioToolClient, load_cases
from app.config import Settings
from app.security import InvestigationSlotDep
from app.services.exceptions import NotFoundError

router = APIRouter()


class ReplayCase(BaseModel):
    id: str
    question: str
    expected_service: str | None
    expected_root_cause: str | None
    unavailable_sources: list[str]


class ReplayResult(BaseModel):
    case: ReplayCase
    match: bool
    service_match: bool
    report: dict[str, Any]


def _case(raw: dict[str, Any]) -> ReplayCase:
    return ReplayCase(
        id=raw["id"],
        question=raw["question"],
        expected_service=raw["expected_service"],
        expected_root_cause=raw["expected_root_cause"],
        unavailable_sources=list(raw.get("telemetry", {}).get("unavailable", []))
        + (["knowledge base"] if raw.get("knowledge") == "unavailable" else []),
    )


@router.get("/replays", response_model=list[ReplayCase])
async def list_replays() -> list[ReplayCase]:
    return [_case(c) for c in load_cases()["cases"]]


@router.post("/replays/{case_id}", response_model=ReplayResult)
async def run_replay(case_id: str, _slot: InvestigationSlotDep) -> ReplayResult:
    data = load_cases()
    raw = next((c for c in data["cases"] if c["id"] == case_id), None)
    if raw is None:
        raise NotFoundError(f"Replay scenario '{case_id}' not found")
    knowledge = data.get("knowledge_sets", {}).get(raw["knowledge"], raw["knowledge"])
    # Deterministic and offline: no LLM, simulated tools, the scenario's clock.
    agent = InvestigationAgent(
        ScenarioToolClient(raw["telemetry"]),
        ScenarioRetriever(knowledge),
        Settings(_env_file=None, llm_provider="none"),
        now=lambda: NOW,
    )
    report = await agent.run(raw["question"], window_minutes=60)
    return ReplayResult(
        case=_case(raw),
        match=report.root_cause == raw["expected_root_cause"],
        service_match=report.service == raw["expected_service"],
        report=report.model_dump(mode="json"),
    )
