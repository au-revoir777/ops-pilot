"""Human-readable rendering of an investigation report (Markdown)."""

from __future__ import annotations

from app.agents.models import InvestigationReport


def to_markdown(report: InvestigationReport) -> str:
    lines = [f"# Investigation: {report.query}", ""]
    lines.append(f"**Service:** {report.service or 'unknown'}  ")
    lines.append(f"**Symptoms:** {', '.join(report.symptoms) or 'unspecified'}  ")
    lines.append(f"**Window:** last {report.window_minutes} minutes")
    lines += ["", "## Conclusion", "", report.conclusion]
    if report.confidence_breakdown:
        b = report.confidence_breakdown
        lines += [
            "",
            f"Confidence {report.confidence:.0%} (heuristic, evidence-derived; not a probability): "
            f"base {b.base}, temporal {b.temporal}, metric {b.metric}, log {b.log}, "
            f"deployment {b.deployment}, knowledge {b.knowledge}, "
            f"contradictions {b.contradictions}, "
            f"coverage x{b.coverage_factor}",
        ]
    lines += ["", "## Observed facts (telemetry)", ""]
    lines += [f"- **{o.id}** {o.statement} _(via {o.source})_" for o in report.observations] or [
        "- none"
    ]
    lines += ["", "## Retrieved evidence (knowledge base)", ""]
    lines += [
        f"- **{e.id}** {e.title} > {e.section} `{e.citation}` (score {e.score})"
        + (f" FLAGGED: {', '.join(e.flags)}" if e.flags else "")
        for e in report.evidence
    ] or ["- none"]
    lines += ["", "## Hypotheses and validation", ""]
    for h in report.hypotheses:
        conf = f"{h.confidence.value:.0%}" if h.confidence else "n/a"
        lines.append(f"- **{h.id}** [{h.status}, {conf}] {h.statement}")
        lines.append(f"  - supported by: {', '.join(h.supporting) or 'nothing'}")
        if h.contradictions:
            lines.append(f"  - contradicted by: {'; '.join(h.contradictions)}")
    if not report.hypotheses:
        lines.append("- none")
    lines += ["", "## Recommendations (require human action)", ""]
    for r in report.recommendations:
        approval = " (requires human approval)" if r.requires_human_approval else ""
        refs = f" See: {', '.join(r.references)}" if r.references else ""
        lines.append(f"- {r.action}{approval}. {r.rationale}{refs}")
    if report.missing_evidence:
        lines += ["", "## Missing evidence", ""] + [f"- {m}" for m in report.missing_evidence]
    if report.llm.get("summary"):
        lines += ["", f"## Summary ({report.llm.get('summary_label')})", "", report.llm["summary"]]
    lines += ["", "## Trace", ""]
    lines += [f"- {t.node}: {t.summary} ({t.duration_ms:.0f} ms)" for t in report.trace]
    return "\n".join(lines) + "\n"
