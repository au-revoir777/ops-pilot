"""Export real API payloads as frontend test fixtures.

Runs the replay endpoint (the real agent over recorded scenarios, offline) for a
few cases and writes the JSON responses to tests/fixtures/. The zod contract
tests parse these, so a backend shape change that breaks the UI fails a test.

    cd apps/api && PYTHONPATH=. ../../.venv/Scripts/python ../web/scripts/export_fixtures.py
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

from httpx import ASGITransport, AsyncClient

from app.main import create_app

CASES = [
    "deploy-db-regression",
    "prometheus-down-logs-only",
    "poisoned-knowledge",
    "unknown-service",
]
OUT = Path(__file__).resolve().parents[1] / "tests" / "fixtures"


async def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    transport = ASGITransport(app=create_app())
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        cases = (await client.get("/api/replays")).json()
        (OUT / "replays.json").write_text(json.dumps(cases, indent=2) + "\n", encoding="utf-8")
        available = {c["id"] for c in cases}
        for case_id in CASES:
            if case_id not in available:
                sys.stdout.write(f"skip {case_id}: not a scenario\n")
                continue
            response = await client.post(f"/api/replays/{case_id}")
            response.raise_for_status()
            path = OUT / f"replay-{case_id}.json"
            path.write_text(json.dumps(response.json(), indent=2) + "\n", encoding="utf-8")
            sys.stdout.write(f"wrote {path.name}\n")


if __name__ == "__main__":
    asyncio.run(main())
