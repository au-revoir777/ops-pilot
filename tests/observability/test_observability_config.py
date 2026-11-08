"""Static checks for the observability stack configuration (no containers needed).

Catches the drift that otherwise only shows up as an empty Grafana panel:
dashboards querying metrics nobody emits, scrape targets that don't exist in
Compose, data-source UIDs that don't match, a stale generated dashboard.
"""

from __future__ import annotations

import importlib.util
import json
import re
from pathlib import Path

import pytest
import yaml

pytestmark = pytest.mark.unit

ROOT = Path(__file__).resolve().parents[2]
OBS = ROOT / "observability"
METRIC_SOURCES = [ROOT / "apps/api/app/metrics.py", ROOT / "workloads/opsdemo/observability.py"]
DASHBOARD = OBS / "grafana/dashboards/opspilot-services.json"
# A metric (or recording rule) name immediately followed by a selector or range.
METRIC_REF = re.compile(r"\b([a-zA-Z_][a-zA-Z0-9_]*(?::[a-zA-Z0-9_]+)*)\s*[\{\[]")
BUILTIN_METRICS = {"up"}


def load_yaml(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def compose() -> dict:
    return load_yaml(ROOT / "docker-compose.yml")


@pytest.fixture(scope="module")
def prometheus() -> dict:
    return load_yaml(OBS / "prometheus/prometheus.yml")


@pytest.fixture(scope="module")
def rules() -> list[dict]:
    rules: list[dict] = []
    for path in sorted((OBS / "prometheus/rules").glob("*.yml")):
        for group in load_yaml(path)["groups"]:
            rules.extend(group["rules"])
    return rules


@pytest.fixture(scope="module")
def dashboard() -> dict:
    return json.loads(DASHBOARD.read_text(encoding="utf-8"))


def emitted_metric_names() -> set[str]:
    """Metric names declared in application code, expanded with histogram series."""
    names: set[str] = set()
    pattern = re.compile(r"(Counter|Histogram|Gauge)\(\s*\"([a-z_:]+)\"")
    for source in METRIC_SOURCES:
        for kind, name in pattern.findall(source.read_text(encoding="utf-8")):
            names.add(name)
            if kind == "Histogram":
                names |= {f"{name}_bucket", f"{name}_count", f"{name}_sum"}
    return names


def dashboard_exprs(dashboard: dict) -> list[tuple[str, str]]:
    exprs = []
    for panel in dashboard["panels"]:
        for target in panel.get("targets", []):
            exprs.append((target["datasource"]["type"], target["expr"]))
    return exprs


# ---------------------------------------------------------------------------
# Prometheus
# ---------------------------------------------------------------------------


def test_scrape_targets_exist_in_compose(prometheus, compose):
    services = compose["services"]
    for job in prometheus["scrape_configs"]:
        for static in job["static_configs"]:
            for target in static["targets"]:
                host = target.split(":")[0]
                if host == "localhost":
                    continue
                assert host in services, f"{job['job_name']}: no Compose service '{host}'"


def test_workload_scrape_ports_match_container_commands(prometheus, compose):
    workloads = next(j for j in prometheus["scrape_configs"] if j["job_name"] == "workloads")
    for target in workloads["static_configs"][0]["targets"]:
        host, port = target.split(":")
        assert port in compose["services"][host]["command"], target


def test_rule_files_are_mounted(prometheus, compose):
    mounts = compose["services"]["prometheus"]["volumes"]
    assert any(
        m.startswith("./observability/prometheus/rules:/etc/prometheus/rules") for m in mounts
    )
    assert prometheus["rule_files"] == ["/etc/prometheus/rules/*.yml"]


def test_rules_only_reference_emitted_metrics(rules):
    known = emitted_metric_names() | BUILTIN_METRICS | {r["record"] for r in rules if "record" in r}
    for rule in rules:
        for name in METRIC_REF.findall(rule["expr"]):
            assert name in known, (
                f"{rule.get('record') or rule.get('alert')}: unknown metric {name}"
            )


def test_alerts_have_severity_and_summary(rules):
    alerts = [r for r in rules if "alert" in r]
    assert {a["alert"] for a in alerts} >= {"HighLatencyP95", "HighErrorRate", "TargetDown"}
    for alert in alerts:
        assert alert["labels"]["severity"] in {"warning", "critical"}
        assert alert["annotations"]["summary"]


# ---------------------------------------------------------------------------
# Grafana
# ---------------------------------------------------------------------------


def test_generated_dashboard_is_up_to_date():
    spec = importlib.util.spec_from_file_location(
        "build_dashboards", OBS / "grafana/build_dashboards.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert DASHBOARD.read_text(encoding="utf-8") == module.render(), (
        "Run: python observability/grafana/build_dashboards.py"
    )


def test_dashboard_covers_required_panels(dashboard):
    titles = " | ".join(p["title"] for p in dashboard["panels"]).lower()
    for required in ("request rate", "error rate", "p50", "p95", "p99", "up", "versions", "logs"):
        assert required in titles, required


def test_dashboard_queries_only_emitted_metrics(dashboard, rules):
    known = emitted_metric_names() | BUILTIN_METRICS | {r["record"] for r in rules if "record" in r}
    for kind, expr in dashboard_exprs(dashboard):
        if kind != "prometheus":
            continue
        for name in METRIC_REF.findall(expr):
            assert name in known, f"dashboard queries unknown metric {name}: {expr}"


def test_dashboard_datasources_are_provisioned(dashboard):
    provisioned = load_yaml(OBS / "grafana/provisioning/datasources/datasources.yml")
    uids = {d["uid"]: d["type"] for d in provisioned["datasources"]}
    for panel in dashboard["panels"]:
        for target in panel.get("targets", []):
            ds = target["datasource"]
            assert uids.get(ds["uid"]) == ds["type"], ds


def test_dashboard_panel_ids_unique(dashboard):
    ids = [p["id"] for p in dashboard["panels"]]
    assert len(ids) == len(set(ids))


def test_grafana_admin_password_not_hardcoded(compose):
    env = compose["services"]["grafana"]["environment"]
    assert env["GF_SECURITY_ADMIN_PASSWORD"].startswith("${GRAFANA_ADMIN_PASSWORD")
    assert env["GF_AUTH_ANONYMOUS_ORG_ROLE"] == "Viewer"


# ---------------------------------------------------------------------------
# Logs (Alloy -> Loki)
# ---------------------------------------------------------------------------


def test_alloy_selects_this_compose_project(compose):
    config = (OBS / "alloy/config.alloy").read_text(encoding="utf-8")
    assert f"com.docker.compose.project={compose['name']}" in config
    assert "http://loki:3100/loki/api/v1/push" in config


def test_request_id_is_metadata_not_a_label():
    config = (OBS / "alloy/config.alloy").read_text(encoding="utf-8")
    labels_block = config.split("stage.labels", 1)[1].split("}", 2)[0:2]
    assert "request_id" not in "".join(labels_block)
    assert "stage.structured_metadata" in config


def test_observability_ports_bound_to_localhost(compose):
    for name in ("prometheus", "loki", "grafana"):
        for port in compose["services"][name]["ports"]:
            assert port.startswith("127.0.0.1:"), (name, port)
