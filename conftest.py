"""Repository-wide test rules: every test belongs to exactly one tier of the pyramid.

    unit         no network, no database, no containers; milliseconds each
    integration  real PostgreSQL (postgres-test) or in-process servers
    system       the running Docker Compose stack
    evaluation   agent and retrieval quality over recorded scenarios

`make test-<tier>` selects by marker, so a test without a tier (or with two)
would silently run in the wrong place or not at all. Collection fails instead.
"""

from __future__ import annotations

import pytest

TIERS = ("unit", "integration", "system", "evaluation")


@pytest.hookimpl(trylast=True)  # after per-directory conftests have added their markers
def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    problems = []
    for item in items:
        tiers = [t for t in TIERS if item.get_closest_marker(t)]
        if len(tiers) != 1:
            problems.append(f"{item.nodeid}: {tiers or 'no tier'}")
    if problems:
        raise pytest.UsageError(
            "Every test needs exactly one tier marker (unit, integration, system, "
            "evaluation):\n  " + "\n  ".join(problems)
        )
