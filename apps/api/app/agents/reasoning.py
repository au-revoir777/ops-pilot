"""Hypothesis generation, validation and confidence (deterministic, explainable).

Hypotheses come from explicit rules over observation signals, so every claim
in a conclusion points at the facts that produced it. Confidence is a
documented heuristic over evidence categories (spec section 12), not a
probability:

    raw = base (symptom confirmed, 0.10)
        + temporal    0.25  cause precedes the symptom onset by 0-30 min
        + metric      0.25  a metric moved the way the cause predicts
        + log         0.20  logs show the mechanism (e.g. slow queries)
        + deployment  0.10  a release is visible in the window
        + knowledge   0.10  a retrieved runbook/postmortem describes this cause
        - 0.25 per contradiction
    confidence = clamp(raw, 0, 0.95) * (0.6 + 0.4 * coverage)

``coverage`` is the share of planned evidence sources that answered, so
missing telemetry lowers confidence instead of being ignored. 0.95 is the
ceiling: the agent never claims certainty.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta

from app.agents.models import (
    ConfidenceBreakdown,
    Hypothesis,
    Observation,
    Recommendation,
    RetrievedEvidence,
)

WEIGHTS = {
    "base": 0.10,
    "temporal": 0.25,
    "metric": 0.25,
    "log": 0.20,
    "deployment": 0.10,
    "knowledge": 0.10,
}
CONTRADICTION_PENALTY = 0.25
CEILING = 0.95
TEMPORAL_WINDOW = timedelta(minutes=30)
# Deploy times come from the first scrape that saw the new version and symptom
# onsets from a 1-minute rate window, so both are only accurate to about a
# minute. A release up to 2 minutes "after" the onset counts as coincident.
TIME_RESOLUTION = timedelta(minutes=2)
SUFFICIENT_CONFIDENCE = 0.6
# Below MIN_REPORTABLE_CONFIDENCE no root cause is reported at all; below
# TENTATIVE_BELOW the conclusion is explicitly labelled tentative.
MIN_REPORTABLE_CONFIDENCE = 0.25
TENTATIVE_BELOW = 0.5
SUFFICIENT_MARGIN = 0.15
SYMPTOMS = {"symptom_latency", "symptom_errors", "latency_step", "alert_firing"}


@dataclass(frozen=True)
class CauseRule:
    cause: str
    applies: Callable[[set[str]], bool]
    statement: str  # format fields: service, version, dependency
    metric_signals: frozenset[str]
    log_signals: frozenset[str]
    contradicted_by: frozenset[str]
    uses_deployment: bool
    knowledge_terms: tuple[str, ...]


RULES: list[CauseRule] = [
    CauseRule(
        cause="deployment_db_regression",
        applies=lambda s: "deploy_recent" in s and bool(s & {"db_latency_rise", "db_slow_logs"}),
        statement="Release {version} of {service} introduced a database query regression",
        metric_signals=frozenset({"db_latency_rise"}),
        log_signals=frozenset({"db_slow_logs"}),
        contradicted_by=frozenset({"db_latency_flat"}),
        uses_deployment=True,
        knowledge_terms=("query", "roll back", "rollback", "regression"),
    ),
    CauseRule(
        cause="deployment_regression",
        applies=lambda s: "deploy_recent" in s and bool(s & SYMPTOMS),
        statement="Release {version} of {service} introduced a regression",
        metric_signals=frozenset({"latency_step", "error_step"}),
        log_signals=frozenset({"internal_errors"}),
        contradicted_by=frozenset({"dependency_degraded"}),
        uses_deployment=True,
        knowledge_terms=("roll back", "rollback", "release", "deploy"),
    ),
    CauseRule(
        cause="database_degradation",
        applies=lambda s: bool(s & {"db_latency_rise", "db_slow_logs"}),
        statement="Database queries of {service} became slow",
        metric_signals=frozenset({"db_latency_rise"}),
        log_signals=frozenset({"db_slow_logs"}),
        contradicted_by=frozenset({"db_latency_flat"}),
        uses_deployment=False,
        knowledge_terms=("database", "slow", "query"),
    ),
    CauseRule(
        cause="dependency_failure",
        applies=lambda s: bool(s & {"dependency_degraded", "dependency_errors"}),
        statement="Dependency {dependency} of {service} is failing or slow",
        metric_signals=frozenset({"dependency_degraded"}),
        log_signals=frozenset({"dependency_errors"}),
        contradicted_by=frozenset({"dependencies_healthy"}),
        uses_deployment=False,
        knowledge_terms=("dependency", "502", "depends"),
    ),
    CauseRule(
        # Diagnosis by elimination: slow requests while the database and every
        # dependency are measured healthy. Its metric evidence is those exclusions,
        # not the latency itself, so the symptom never counts as its own cause.
        cause="application_latency",
        applies=lambda s: (
            bool(s & {"latency_step", "symptom_latency"})
            and "db_latency_flat" in s
            and "dependencies_healthy" in s
            and not s
            & {"db_latency_rise", "db_slow_logs", "dependency_degraded", "internal_errors"}
        ),
        statement="{service}'s own request handling became slow "
        "(its database and dependencies are healthy)",
        metric_signals=frozenset({"db_latency_flat", "dependencies_healthy"}),
        log_signals=frozenset({"app_slow_logs"}),
        contradicted_by=frozenset({"db_latency_rise", "db_slow_logs", "dependency_degraded"}),
        uses_deployment=False,
        knowledge_terms=("request_slow", "high latency", "latency"),
    ),
    CauseRule(
        cause="application_errors",
        applies=lambda s: "internal_errors" in s,
        statement="{service} itself is failing requests (errors not caused by dependencies)",
        metric_signals=frozenset({"error_step", "symptom_errors"}),
        log_signals=frozenset({"internal_errors"}),
        contradicted_by=frozenset({"dependency_errors", "dependency_degraded"}),
        uses_deployment=False,
        knowledge_terms=("request_processing_failed", "errors", "5xx"),
    ),
]


def _by_signal(
    observations: list[Observation], signals: frozenset[str] | set[str]
) -> list[Observation]:
    return [o for o in observations if set(o.signals) & set(signals)]


def latest_deploy(observations: list[Observation]) -> Observation | None:
    """The most recent release in the window that is not after the symptom onset."""
    deploys = [o for o in observations if "deploy_recent" in o.signals and o.at]
    onset = symptom_onset(observations)
    if onset:
        before = [o for o in deploys if o.at <= onset + TIME_RESOLUTION]
        deploys = before or deploys
    return max(deploys, key=lambda o: o.at, default=None)


def _context(rule: CauseRule, observations: list[Observation], service: str) -> dict[str, str]:
    deploy = latest_deploy(observations)
    dep_obs = next((o for o in observations if o.data.get("dependency")), None)
    targets = next((o.data.get("targets") for o in observations if o.data.get("targets")), None)
    dependency = (
        dep_obs.data["dependency"]
        if dep_obs
        else (max(targets, key=targets.get) if targets else "a dependency")
    )
    return {
        "service": service,
        "version": deploy.data.get("version", "the latest release") if deploy else "",
        "dependency": dependency,
    }


def symptom_onset(observations: list[Observation]):
    onsets = [
        o.at for o in observations if "latency_step" in o.signals or "error_step" in o.signals
    ]
    return min((t for t in onsets if t), default=None)


def generate_hypotheses(observations: list[Observation], service: str) -> list[Hypothesis]:
    signals = {s for o in observations for s in o.signals}
    hypotheses = []
    for rule in RULES:
        if rule.applies(signals):
            hypotheses.append(
                Hypothesis(
                    id=f"H{len(hypotheses) + 1}",
                    cause=rule.cause,
                    statement=rule.statement.format(**_context(rule, observations, service)),
                )
            )
    return hypotheses


def _knowledge_support(rule: CauseRule, evidence: list[RetrievedEvidence]) -> list[str]:
    hits = []
    for item in evidence:
        text = f"{item.title} {item.section or ''} {item.excerpt}".lower()
        if "possible_prompt_injection" in item.flags:
            continue  # never let flagged content raise confidence
        if any(term in text for term in rule.knowledge_terms):
            hits.append(item.id)
    return hits


def validate(
    hypothesis: Hypothesis,
    observations: list[Observation],
    evidence: list[RetrievedEvidence],
    coverage: float,
) -> Hypothesis:
    """Attach supporting/contradicting evidence and the confidence breakdown."""
    rule = next(r for r in RULES if r.cause == hypothesis.cause)
    supporting: list[str] = []
    contradicting: list[str] = []
    contradictions: list[str] = []

    symptom = _by_signal(observations, SYMPTOMS)
    base = WEIGHTS["base"] if symptom else 0.0
    supporting += [o.id for o in symptom]

    metric_obs = _by_signal(observations, rule.metric_signals)
    log_obs = _by_signal(observations, rule.log_signals)
    supporting += [o.id for o in metric_obs + log_obs]

    latest = latest_deploy(observations) if rule.uses_deployment else None
    deploy_obs = [latest] if latest else []
    supporting += [o.id for o in deploy_obs]

    temporal = 0.0
    onset = symptom_onset(observations)
    cause_times = [o.at for o in (deploy_obs or metric_obs) if o.at]
    if onset and cause_times:
        earliest = min(cause_times)
        lag = onset - earliest
        if -TIME_RESOLUTION <= lag <= TEMPORAL_WINDOW:
            temporal = WEIGHTS["temporal"]
        elif deploy_obs and lag < -TIME_RESOLUTION:
            contradictions.append(
                f"the symptom started at {onset:%H:%M:%S} UTC, "
                f"before the release at {earliest:%H:%M:%S} UTC"
            )
            contradicting += [o.id for o in deploy_obs]

    for obs in _by_signal(observations, rule.contradicted_by):
        contradicting.append(obs.id)
        contradictions.append(obs.statement)

    knowledge_ids = _knowledge_support(rule, evidence)
    supporting += knowledge_ids

    raw = (
        base
        + temporal
        + (WEIGHTS["metric"] if metric_obs else 0.0)
        + (WEIGHTS["log"] if log_obs else 0.0)
        + (WEIGHTS["deployment"] if deploy_obs else 0.0)
        + (WEIGHTS["knowledge"] if knowledge_ids else 0.0)
        - CONTRADICTION_PENALTY * len(contradictions)
    )
    coverage_factor = 0.6 + 0.4 * max(0.0, min(1.0, coverage))
    value = round(max(0.0, min(CEILING, raw)) * coverage_factor, 3)
    breakdown = ConfidenceBreakdown(
        base=base,
        temporal=temporal,
        metric=WEIGHTS["metric"] if metric_obs else 0.0,
        log=WEIGHTS["log"] if log_obs else 0.0,
        deployment=WEIGHTS["deployment"] if deploy_obs else 0.0,
        knowledge=WEIGHTS["knowledge"] if knowledge_ids else 0.0,
        contradictions=-CONTRADICTION_PENALTY * len(contradictions),
        coverage_factor=round(coverage_factor, 3),
        value=value,
    )
    status = (
        "rejected" if contradictions and value < 0.3 else ("supported" if value >= 0.5 else "weak")
    )
    return hypothesis.model_copy(
        update={
            "supporting": list(dict.fromkeys(supporting)),
            "contradicting": list(dict.fromkeys(contradicting)),
            "contradictions": contradictions,
            "confidence": breakdown,
            "status": status,
        }
    )


def rank(hypotheses: list[Hypothesis]) -> list[Hypothesis]:
    # Ties go to the more specific rule (earlier in RULES).
    order = {r.cause: i for i, r in enumerate(RULES)}
    return sorted(
        hypotheses, key=lambda h: (-(h.confidence.value if h.confidence else 0), order[h.cause])
    )


# A composite cause explains its parts; they are not competing explanations.
SUBSUMES = {"deployment_db_regression": {"database_degradation", "deployment_regression"}}


def is_sufficient(ranked: list[Hypothesis]) -> bool:
    """Best hypothesis is confident enough and clearly ahead of real alternatives."""
    if not ranked or ranked[0].confidence is None:
        return False
    best = ranked[0]
    rivals = [h for h in ranked[1:] if h.cause not in SUBSUMES.get(best.cause, set())]
    second = rivals[0].confidence.value if rivals and rivals[0].confidence else 0.0
    return best.confidence.value >= SUFFICIENT_CONFIDENCE and (
        best.confidence.value - second >= SUFFICIENT_MARGIN
    )


def recommend(
    best: Hypothesis | None,
    observations: list[Observation],
    evidence: list[RetrievedEvidence],
    service: str,
) -> list[Recommendation]:
    """Recommendations only; the agent never executes remediation (spec section 17)."""

    def refs(*terms: str) -> list[str]:
        # Flagged (possible prompt injection) passages are never cited as a reference.
        return [
            e.citation
            for e in evidence
            if "possible_prompt_injection" not in e.flags
            and any(t in e.excerpt.lower() or t in e.title.lower() for t in terms)
        ][:3]

    if best is None or best.status == "rejected":
        return [
            Recommendation(
                action=f"Continue manual investigation of {service}: evidence was insufficient",
                rationale="No hypothesis reached the confidence threshold.",
                requires_human_approval=False,
            )
        ]
    deploy = latest_deploy(observations)
    if best.cause in {"deployment_db_regression", "deployment_regression"} and deploy:
        target = deploy.data.get("previous_version") or "the previous version"
        timed = best.confidence is not None and best.confidence.temporal > 0
        rationale = (
            "The symptom started shortly after this release and the evidence points at it."
            if timed
            else "This release is the only change in the window; its timing relative to the "
            "symptom could not be confirmed, so verify before rolling back."
        )
        return [
            Recommendation(
                action=f"Roll back {service} from {deploy.data.get('version')} to {target}",
                rationale=rationale,
                references=refs("roll back", "rollback"),
            ),
            Recommendation(
                action="Capture the slow queries and their plans for the postmortem",
                rationale="Needed to fix the regression before redeploying.",
                requires_human_approval=False,
                references=refs("query"),
            ),
        ]
    if best.cause == "database_degradation":
        return [
            Recommendation(
                action=f"Follow the database troubleshooting guide for {service}",
                rationale="Query latency rose without a release in the window.",
                requires_human_approval=False,
                references=refs("database"),
            )
        ]
    if best.cause == "application_latency":
        return [
            Recommendation(
                action=f"Profile {service}'s request path and check recent config, feature-flag "
                "or resource changes",
                rationale="Requests are slow while the database and dependencies are healthy, "
                "so the time is spent inside the service itself.",
                requires_human_approval=False,
                references=refs("latency", "request_slow"),
            ),
            Recommendation(
                action=f"If users are affected, scale out {service} or shed non-critical load "
                "while the cause is found",
                rationale="Buys headroom without changing code; revert once latency recovers.",
                references=refs("scale", "capacity"),
            ),
        ]
    if best.cause == "dependency_failure":
        return [
            Recommendation(
                action="Investigate the failing dependency first; avoid aggressive retries",
                rationale=best.statement,
                requires_human_approval=False,
                references=refs("dependency", "502"),
            )
        ]
    return [
        Recommendation(
            action=f"Inspect {service} error logs and recent changes",
            rationale=best.statement,
            requires_human_approval=False,
            references=refs("error"),
        )
    ]
