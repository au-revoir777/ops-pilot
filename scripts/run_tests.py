"""Run one tier of the test pyramid, Python and frontend together.

    python scripts/run_tests.py all           # unit + integration (what CI gates on)
    python scripts/run_tests.py unit          # pytest -m unit, Vitest, contrast check
    python scripts/run_tests.py integration   # pytest -m integration (needs postgres-test)
    python scripts/run_tests.py system        # pytest -m system, Playwright (needs the stack)
    python scripts/run_tests.py evaluation    # agent + retrieval quality
    python scripts/run_tests.py coverage      # unit + integration with a coverage report

The `make test*` targets call this script, so both give the same result; it also
works where `make` is not installed (for example on Windows).
Pass --no-web to skip the frontend steps (no Node.js needed).
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "apps" / "web"
PYTEST = [sys.executable, "-m", "pytest"]


def npm(*args: str) -> list[str]:
    exe = shutil.which("npm") or shutil.which("npm.cmd")
    if exe is None:
        raise SystemExit("npm not found: install Node.js 20+ or pass --no-web")
    return [exe, *args]


def npx(*args: str) -> list[str]:
    exe = shutil.which("npx") or shutil.which("npx.cmd")
    if exe is None:
        raise SystemExit("npx not found: install Node.js 20+ or pass --no-web")
    return [exe, *args]


def steps(tier: str, web: bool) -> list[tuple[str, list[str], Path]]:
    py = {
        "all": [("pytest unit + integration", PYTEST, ROOT)],
        "unit": [("pytest -m unit", [*PYTEST, "-m", "unit"], ROOT)],
        "integration": [("pytest -m integration", [*PYTEST, "-m", "integration"], ROOT)],
        "system": [("pytest -m system", [*PYTEST, "-m", "system"], ROOT)],
        "evaluation": [("pytest -m evaluation", [*PYTEST, "-m", "evaluation"], ROOT)],
        "coverage": [
            (
                "pytest unit + integration with coverage",
                [*PYTEST, "--cov", "--cov-report=term:skip-covered", "--cov-report=xml"],
                ROOT,
            )
        ],
    }[tier]
    if not web:
        return py
    frontend = {
        "all": [
            ("typecheck", npm("run", "typecheck"), WEB),
            ("vitest", npm("test"), WEB),
            ("contrast", npm("run", "contrast"), WEB),
        ],
        "unit": [
            ("typecheck", npm("run", "typecheck"), WEB),
            ("vitest", npm("test"), WEB),
            ("contrast", npm("run", "contrast"), WEB),
        ],
        "system": [("playwright", npx("playwright", "test"), WEB)],
    }.get(tier, [])
    return py + frontend


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "tier", choices=["all", "unit", "integration", "system", "evaluation", "coverage"]
    )
    parser.add_argument("--no-web", action="store_true", help="skip the frontend steps")
    args = parser.parse_args(argv)

    failed = []
    for name, command, cwd in steps(args.tier, web=not args.no_web):
        sys.stdout.write(f"\n=== {name} ===\n")
        sys.stdout.flush()
        # Fixed command lists built above; nothing comes from user input.
        if subprocess.run(command, cwd=cwd).returncode != 0:  # noqa: S603
            failed.append(name)
    verdict = f"FAILED ({', '.join(failed)})" if failed else "all steps passed"
    sys.stdout.write(f"\n{args.tier}: {verdict}\n")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
