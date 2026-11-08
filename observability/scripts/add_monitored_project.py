"""Connect an external project to OpsPilot monitoring (the custom option).

    python observability/scripts/add_monitored_project.py \
        --project my-shop --target shop-api.internal:8000 --target shop-worker.internal:9100 \
        --environment production

Writes observability/prometheus/targets/<project>.yml. Prometheus re-reads the
target files every 30 s, so the project appears without code changes or a
restart. Remove the file to stop monitoring it. The demo workloads
(demo-workloads.yml) are only a rough evaluation test bed and stay separate
through the `project` label.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

TARGETS_DIR = Path(__file__).resolve().parents[1] / "prometheus" / "targets"
RESERVED = {"opspilot", "opsdemo"}
_PROJECT = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")
_TARGET = re.compile(r"^[A-Za-z0-9.-]+:\d{1,5}$")


def render(project: str, environment: str, targets: list[str]) -> str:
    quoted = ", ".join(f'"{t}"' for t in targets)
    return (
        f"# External project '{project}', added with add_monitored_project.py.\n"
        "# OpsPilot only reads metrics from these targets.\n"
        f"- targets: [{quoted}]\n"
        "  labels:\n"
        f"    project: {project}\n"
        f"    environment: {environment}\n"
    )


def validate(project: str, environment: str, targets: list[str]) -> list[str]:
    errors = []
    if not _PROJECT.match(project):
        errors.append("project must be lowercase letters, digits and dashes")
    if project in RESERVED:
        errors.append(f"'{project}' is reserved for OpsPilot itself / the demo workloads")
    if not _PROJECT.match(environment):
        errors.append("environment must be lowercase letters, digits and dashes")
    for target in targets:
        if not _TARGET.match(target) or not 0 < int(target.rsplit(":", 1)[1]) < 65536:
            errors.append(f"invalid target '{target}' (expected host:port)")
    return errors


def main(argv: list[str] | None = None, targets_dir: Path = TARGETS_DIR) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("--project", required=True)
    parser.add_argument(
        "--target", action="append", required=True, help="host:port serving /metrics"
    )
    parser.add_argument("--environment", default="production")
    parser.add_argument("--force", action="store_true", help="overwrite an existing target file")
    args = parser.parse_args(argv)

    errors = validate(args.project, args.environment, args.target)
    if errors:
        for error in errors:
            print(f"error: {error}", file=sys.stderr)  # noqa: T201
        return 2

    path = targets_dir / f"{args.project}.yml"
    if path.exists() and not args.force:
        print(f"error: {path.name} already exists (use --force to replace it)", file=sys.stderr)  # noqa: T201
        return 1
    path.write_text(render(args.project, args.environment, args.target), encoding="utf-8")
    print(f"wrote {path}; Prometheus picks it up within 30 s")  # noqa: T201
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
