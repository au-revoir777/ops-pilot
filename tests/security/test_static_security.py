"""Security properties checked from the source tree (no services needed).

These turn the threat model's mitigations into tests, so a later change that
weakens one fails the build instead of silently drifting:

- no shell, eval or unsafe deserialisation in any service code;
- every image runs as a non-root user with a health check;
- every published port is bound to 127.0.0.1 and the database is on its own network;
- OpsPilot's containers drop all capabilities and forbid privilege escalation;
- secrets are SecretStr settings, never plain strings, and no .env is tracked;
- the agent can only reach read-only MCP tools;
- the repository passes the secret scan.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest
import yaml

import secret_scan
from app.agents.tools import ALLOWED_TOOLS
from app.config import Settings

pytestmark = pytest.mark.unit

ROOT = Path(__file__).resolve().parents[2]
SERVICE_CODE = [ROOT / "apps/api/app", ROOT / "mcp/opsmcp", ROOT / "workloads/opsdemo"]
DANGEROUS = re.compile(
    r"\bsubprocess\b|\bos\.system\(|\bos\.popen\(|\beval\(|\bexec\(|\bpickle\b|"
    r"shell\s*=\s*True|yaml\.load\((?![^)]*SafeLoader)|__import__\("
)
OUR_SERVICES = ["migrate", "api", "mcp", "checkout", "payments", "users", "web"]


@pytest.fixture(scope="module")
def compose() -> dict:
    return yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))


def test_no_shell_eval_or_unsafe_deserialisation_in_service_code():
    hits = []
    for root in SERVICE_CODE:
        for path in root.rglob("*.py"):
            for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                if DANGEROUS.search(line.split("#", 1)[0]):
                    hits.append(f"{path.relative_to(ROOT)}:{lineno}: {line.strip()}")
    assert hits == []


@pytest.mark.parametrize(
    "dockerfile",
    ["apps/api/Dockerfile", "mcp/Dockerfile", "workloads/Dockerfile", "apps/web/Dockerfile"],
)
def test_images_run_as_non_root_with_a_health_check(dockerfile):
    text = (ROOT / dockerfile).read_text(encoding="utf-8")
    users = re.findall(r"^USER\s+(\S+)", text, re.M)
    assert users, f"{dockerfile} never switches user"
    assert users[-1] not in {"root", "0"}, f"{dockerfile} runs as root"
    assert re.search(r"^HEALTHCHECK\s", text, re.M), f"{dockerfile} has no HEALTHCHECK"


def test_published_ports_are_bound_to_localhost(compose):
    for name, service in compose["services"].items():
        for port in service.get("ports", []):
            assert str(port).startswith("127.0.0.1:"), f"{name} publishes {port} on all interfaces"


def test_database_is_only_on_the_backend_network(compose):
    assert compose["services"]["postgres"]["networks"] == ["backend"]
    on_backend = {n for n, s in compose["services"].items() if "backend" in s.get("networks", [])}
    assert on_backend == {"postgres", "migrate", "api"}


@pytest.mark.parametrize("name", OUR_SERVICES)
def test_containers_drop_capabilities_and_privilege_escalation(compose, name):
    service = compose["services"][name]
    assert service.get("cap_drop") == ["ALL"], name
    assert "no-new-privileges:true" in service.get("security_opt", []), name


def test_secrets_are_secret_settings():
    secret_fields = [
        "database_url",
        "llm_api_key",
        "embedding_api_key",
        "mcp_auth_token",
        "failure_admin_token",
        "api_key",
    ]
    fields = Settings.model_fields
    for name in secret_fields:
        assert "SecretStr" in str(fields[name].annotation), f"{name} is not a SecretStr"


def test_no_env_file_is_tracked():
    tracked = subprocess.run(
        ["git", "ls-files"],  # noqa: S607
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.splitlines()
    assert not [f for f in tracked if Path(f).name == ".env"]


def test_agent_tools_are_read_only():
    assert {
        "get_service_health",
        "query_metrics",
        "get_recent_logs",
        "get_recent_deployments",
        "get_service_dependencies",
        "get_incident_events",
    } == ALLOWED_TOOLS


def test_repository_passes_the_secret_scan():
    assert secret_scan.scan(secret_scan.tracked_files()) == []
