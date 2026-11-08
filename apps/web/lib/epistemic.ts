// Turns an agent report into the seven epistemic sections of the Findings panel
// (UI prompt section 7). Pure functions: no React, fully unit-tested.
//
// The rules that matter:
//  - facts, retrieved evidence and hypotheses are never merged;
//  - every diagnosis/recommendation claim resolves its references against the
//    payload, and a claim with nothing behind it is flagged "unsupported";
//  - missing telemetry is listed as a gap, never silently dropped.
import type {
  ConfidenceBreakdown,
  Hypothesis,
  Observation,
  Recommendation,
  Report,
  RetrievedEvidence,
  ToolCall,
} from "./api/schemas";

export const SECTION_ORDER = [
  "facts",
  "retrieved",
  "hypotheses",
  "gaps",
  "validation",
  "diagnosis",
  "recommendation",
] as const;
export type SectionKind = (typeof SECTION_ORDER)[number];

export const SECTION_META: Record<SectionKind, { title: string; description: string; token: string }> =
  {
    facts: {
      title: "Observed facts",
      description: "Measured by OpsPilot's read-only tools against live telemetry.",
      token: "fact",
    },
    retrieved: {
      title: "Retrieved evidence",
      description: "Passages the agent actually retrieved from runbooks and postmortems.",
      token: "retrieved",
    },
    hypotheses: {
      title: "Hypotheses",
      description: "Candidate explanations. Not facts until validated.",
      token: "hypothesis",
    },
    gaps: {
      title: "Contradictions and gaps",
      description: "Evidence against the leading hypothesis, and anything that could not be checked.",
      token: "gap",
    },
    validation: {
      title: "Validation",
      description: "How the leading hypothesis was checked against the evidence.",
      token: "validation",
    },
    diagnosis: {
      title: "Diagnosis",
      description: "The most likely root cause given the evidence. Not a certainty.",
      token: "diagnosis",
    },
    recommendation: {
      title: "Recommendation",
      description: "Proposed next steps. OpsPilot never executes them.",
      token: "recommendation",
    },
  };

export type EvidenceRef =
  | { type: "observation"; id: string; item: Observation }
  | { type: "evidence"; id: string; item: RetrievedEvidence }
  | { type: "missing"; id: string };

export type HypothesisView = Hypothesis & {
  label: "supported" | "weakened" | "rejected";
  supportingRefs: EvidenceRef[];
  contradictingRefs: EvidenceRef[];
  leading: boolean;
};

export type Gap = { kind: "contradiction" | "missing" | "unavailable"; text: string; tool?: string };

export type ValidationCheck = {
  key: keyof ConfidenceBreakdown;
  label: string;
  question: string;
  weight: number;
  contribution: number;
  result: "passed" | "not_found" | "penalty" | "clear";
};

export type Claim = { text: string; refs: EvidenceRef[]; unsupported: boolean };

export type RecommendationView = Recommendation & {
  refs: EvidenceRef[];
  unknownReferences: string[];
  unsupported: boolean;
};

export type Findings = {
  facts: Observation[];
  retrieved: RetrievedEvidence[];
  hypotheses: HypothesisView[];
  gaps: Gap[];
  validation: ValidationCheck[];
  diagnosis: Claim | null;
  recommendations: RecommendationView[];
  documentationOnly: boolean;
};

// Weights from apps/api/app/agents/reasoning.py (documented heuristic).
export const CONFIDENCE_WEIGHTS = {
  base: 0.1,
  temporal: 0.25,
  metric: 0.25,
  log: 0.2,
  deployment: 0.1,
  knowledge: 0.1,
  contradiction: -0.25,
  ceiling: 0.95,
} as const;

export const CONFIDENCE_FORMULA =
  "confidence = clamp(base + temporal + metric + log + deployment + knowledge − 0.25 × contradictions, 0, 0.95) × (0.6 + 0.4 × coverage). " +
  "Coverage is the share of planned evidence sources that answered. It is a documented heuristic, not a probability.";

export const LOW_CONFIDENCE_THRESHOLD = Number(process.env.NEXT_PUBLIC_LOW_CONFIDENCE ?? 0.5);

const CHECKS: { key: keyof ConfidenceBreakdown; label: string; question: string; weight: number }[] =
  [
    { key: "base", label: "Symptom confirmed", question: "Is the reported symptom visible in telemetry?", weight: CONFIDENCE_WEIGHTS.base },
    { key: "temporal", label: "Temporal correlation", question: "Did the cause start 0–30 min before the symptom?", weight: CONFIDENCE_WEIGHTS.temporal },
    { key: "metric", label: "Metric correlation", question: "Did a metric move the way this cause predicts?", weight: CONFIDENCE_WEIGHTS.metric },
    { key: "log", label: "Log correlation", question: "Do logs show the mechanism?", weight: CONFIDENCE_WEIGHTS.log },
    { key: "deployment", label: "Deployment correlation", question: "Is a release visible in the window?", weight: CONFIDENCE_WEIGHTS.deployment },
    { key: "knowledge", label: "Knowledge-base support", question: "Does a retrieved runbook or postmortem describe this cause?", weight: CONFIDENCE_WEIGHTS.knowledge },
  ];

export function hypothesisLabel(status: Hypothesis["status"]): HypothesisView["label"] {
  return status === "weak" ? "weakened" : status;
}

export function resolveRef(report: Pick<Report, "observations" | "evidence">, id: string): EvidenceRef {
  const observation = report.observations.find((o) => o.id === id);
  if (observation) return { type: "observation", id, item: observation };
  const evidence = report.evidence.find((e) => e.id === id || e.citation === id);
  if (evidence) return { type: "evidence", id: evidence.id, item: evidence };
  return { type: "missing", id };
}

/** The tool call that produced an observation (observations name their source tool). */
export function toolCallFor(observation: Observation, calls: ToolCall[]): number {
  return calls.findIndex((c) => c.tool === observation.source);
}

export function leadingHypothesis(report: Report): Hypothesis | null {
  if (report.root_cause) {
    const match = report.hypotheses.find((h) => h.cause === report.root_cause);
    if (match) return match;
  }
  return null;
}

export function validationChecks(breakdown: ConfidenceBreakdown | null | undefined): ValidationCheck[] {
  if (!breakdown) return [];
  const checks: ValidationCheck[] = CHECKS.map((c) => ({
    ...c,
    contribution: breakdown[c.key],
    result: breakdown[c.key] > 0 ? "passed" : "not_found",
  }));
  checks.push({
    key: "contradictions",
    label: "Contradictions",
    question: "Does any evidence argue against this cause? (−0.25 each)",
    weight: CONFIDENCE_WEIGHTS.contradiction,
    contribution: breakdown.contradictions,
    result: breakdown.contradictions < 0 ? "penalty" : "clear",
  });
  return checks;
}

export function buildFindings(report: Report): Findings {
  const lead = leadingHypothesis(report);

  const hypotheses: HypothesisView[] = report.hypotheses.map((h) => ({
    ...h,
    label: hypothesisLabel(h.status),
    supportingRefs: h.supporting.map((id) => resolveRef(report, id)),
    contradictingRefs: h.contradicting.map((id) => resolveRef(report, id)),
    leading: lead?.id === h.id,
  }));

  const failedCalls = report.tool_calls.filter((c) => c.status === "unavailable" || c.status === "error");
  const gaps: Gap[] = [
    ...(lead?.contradictions ?? []).map((text) => ({ kind: "contradiction" as const, text })),
    ...report.missing_evidence.map((text) => ({ kind: "missing" as const, text })),
    ...failedCalls.map((c) => ({
      kind: "unavailable" as const,
      text: `${c.tool} returned ${c.status}${c.error ? `: ${c.error}` : ""}`,
      tool: c.tool,
    })),
  ];

  const telemetryCalls = report.tool_calls.length;
  const documentationOnly =
    report.observations.length === 0 &&
    report.evidence.length > 0 &&
    (telemetryCalls === 0 || failedCalls.length === telemetryCalls);

  let diagnosis: Claim | null = null;
  if (report.conclusion) {
    const refs = lead ? lead.supporting.map((id) => resolveRef(report, id)) : [];
    const resolved = refs.filter((r) => r.type !== "missing");
    diagnosis = {
      text: report.conclusion,
      refs,
      // A root cause with nothing behind it in the payload is flagged, not hidden.
      unsupported: report.root_cause != null && resolved.length === 0,
    };
  }

  const recommendations: RecommendationView[] = report.recommendations.map((r) => {
    const refs = r.references.map((ref) => resolveRef(report, ref));
    const unknownReferences = refs.filter((x) => x.type === "missing").map((x) => x.id);
    return {
      ...r,
      refs,
      unknownReferences,
      unsupported: unknownReferences.length > 0,
    };
  });

  return {
    facts: report.observations,
    retrieved: report.evidence,
    hypotheses,
    gaps,
    validation: validationChecks(lead?.confidence ?? report.confidence_breakdown),
    diagnosis,
    recommendations,
    documentationOnly,
  };
}

export function isModelEstimated(report: Pick<Report, "llm">): boolean {
  // Confidence is always rule-based in this backend; only a summary or a service
  // extraction can come from a model, and those are labelled where shown.
  return report.llm?.["confidence_source"] === "model";
}

export function reportToMarkdown(report: Report, meta: { id?: string; requestId?: string; url?: string }): string {
  const f = buildFindings(report);
  const lines: string[] = [
    `# OpsPilot investigation${meta.id ? ` ${meta.id}` : ""}`,
    "",
    `**Question:** ${report.query}`,
    `**Service:** ${report.service ?? "unknown"}`,
    `**Estimated confidence:** ${Math.round(report.confidence * 100)}% (heuristic, not a probability)`,
  ];
  if (meta.url) lines.push(`**Link:** ${meta.url}`);
  if (meta.requestId) lines.push(`**Correlation ID:** ${meta.requestId}`);
  lines.push("", "## Diagnosis (most likely root cause)", "", report.conclusion || "No conclusion.");
  lines.push("", "## Observed facts", "", ...f.facts.map((o) => `- ${o.statement} _(via ${o.source})_`));
  lines.push("", "## Retrieved evidence", "", ...f.retrieved.map((e) => `- ${e.title} — \`${e.citation}\` (score ${e.score.toFixed(2)})`));
  lines.push("", "## Hypotheses", "", ...f.hypotheses.map((h) => `- [${h.label}] ${h.statement}`));
  if (f.gaps.length) lines.push("", "## Contradictions and gaps", "", ...f.gaps.map((g) => `- ${g.text}`));
  lines.push(
    "",
    "## Recommendations (manual; require human approval)",
    "",
    ...f.recommendations.map((r) => `- ${r.action} — ${r.rationale}`),
  );
  return lines.join("\n");
}
