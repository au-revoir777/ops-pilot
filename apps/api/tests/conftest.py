"""Shared test configuration.

Tests are marked by directory so ``pytest -m unit`` / ``pytest -m integration``
select exactly what lives under ``tests/unit`` / ``tests/integration``.
Unit tests never need PostgreSQL; integration fixtures live in
``tests/integration/conftest.py``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

_TESTS_DIR = Path(__file__).parent
_DIRECTORY_MARKERS = {"unit": pytest.mark.unit, "integration": pytest.mark.integration}


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    for item in items:
        try:
            relative = Path(item.fspath).relative_to(_TESTS_DIR)
        except ValueError:
            continue
        marker = _DIRECTORY_MARKERS.get(relative.parts[0])
        if marker is not None:
            item.add_marker(marker)
