"""Unit tests for the external-project onboarding script."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
import yaml

pytestmark = pytest.mark.unit

SCRIPT = Path(__file__).resolve().parents[2] / "observability/scripts/add_monitored_project.py"
_spec = importlib.util.spec_from_file_location("add_monitored_project", SCRIPT)
onboarding = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(onboarding)


def test_writes_a_file_sd_target_file(tmp_path):
    code = onboarding.main(
        ["--project", "my-shop", "--target", "shop.internal:8000", "--target", "10.0.0.5:9100"],
        targets_dir=tmp_path,
    )
    assert code == 0
    groups = yaml.safe_load((tmp_path / "my-shop.yml").read_text(encoding="utf-8"))
    assert groups == [
        {
            "targets": ["shop.internal:8000", "10.0.0.5:9100"],
            "labels": {"project": "my-shop", "environment": "production"},
        }
    ]


def test_refuses_to_overwrite_without_force(tmp_path):
    args = ["--project", "my-shop", "--target", "shop.internal:8000"]
    assert onboarding.main(args, targets_dir=tmp_path) == 0
    assert onboarding.main(args, targets_dir=tmp_path) == 1
    assert onboarding.main([*args, "--force"], targets_dir=tmp_path) == 0


@pytest.mark.parametrize(
    "args",
    [
        ["--project", "opsdemo", "--target", "a:1"],  # reserved for the demo workloads
        ["--project", "Bad Name", "--target", "a:1"],
        ["--project", "ok", "--target", "no-port"],
        ["--project", "ok", "--target", "a:99999"],
        ["--project", "ok", "--target", "a:1", "--environment", "Prod!"],
    ],
)
def test_rejects_invalid_input(tmp_path, args):
    assert onboarding.main(args, targets_dir=tmp_path) == 2
    assert list(tmp_path.iterdir()) == []
