"use client";

import { CircleCheck, CircleDashed, CircleMinus, CircleSlash, TriangleAlert } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import type { Report } from "@/lib/api/schemas";
import { buildFindings, SECTION_ORDER, type SectionKind } from "@/lib/epistemic";
import { cn } from "@/lib/utils";
import { ApprovalDialog } from "./approval-dialog";
import { ConfidenceBreakdown } from "./confidence";
import { Citation, EvidenceItem, FactItem, HypothesisCard, type SourceTarget } from "./evidence";
import { KindSection } from "./kind";
import { UntrustedText } from "./untrusted-text";

// The Findings panel: seven sections, always in this order, never merged
// (UI prompt section 7). `focus` dims sections a selected trace step did not produce.

export const STEP_SECTIONS: Record<string, SectionKind[]> = {
  planner: [],
  rag: ["retrieved"],
  mcp: ["facts", "gaps"],
  hypothesis: ["hypotheses"],
  validator: ["validation", "gaps"],
  synthesizer: ["diagnosis", "recommendation"],
};

const CHECK_ICON = {
  passed: { icon: CircleCheck, word: "Found", className: "text-status-healthy" },
  not_found: { icon: CircleDashed, word: "Not found", className: "text-muted-foreground" },
  penalty: { icon: TriangleAlert, word: "Penalty", className: "text-status-down-text" },
  clear: { icon: CircleMinus, word: "None", className: "text-muted-foreground" },
} as const;

export function FindingsPanel({
  report,
  focus,
  onCite,
  modelEstimated = false,
}: {
  report: Report;
  focus?: string | null;
  onCite?: (t: SourceTarget) => void;
  modelEstimated?: boolean;
}) {
  const f = buildFindings(report);
  const focused = focus ? STEP_SECTIONS[focus] ?? [] : null;
  const dim = (kind: SectionKind) => focused != null && !focused.includes(kind);
  const llmSummary = typeof report.llm?.["summary"] === "string" ? (report.llm["summary"] as string) : null;

  const sections: Record<SectionKind, React.ReactNode> = {
    facts: (
      <KindSection kind="facts" count={f.facts.length} dimmed={dim("facts")}>
        {f.facts.length ? (
          <ul className="space-y-0.5">
            {f.facts.map((o) => (
              <FactItem key={o.id} observation={o} onCite={onCite} />
            ))}
          </ul>
        ) : (
          <p className="text-xs text-muted-foreground">
            No telemetry facts were collected{f.documentationOnly ? ": operational evidence was unavailable." : "."}
          </p>
        )}
      </KindSection>
    ),
    retrieved: (
      <KindSection kind="retrieved" count={f.retrieved.length} dimmed={dim("retrieved")}>
        {f.retrieved.length ? (
          <div className="space-y-2">
            {f.retrieved.map((e) => (
              <EvidenceItem key={e.id} evidence={e} compact />
            ))}
          </div>
        ) : (
          <p className="text-xs text-muted-foreground">No documents were retrieved.</p>
        )}
      </KindSection>
    ),
    hypotheses: (
      <KindSection kind="hypotheses" count={f.hypotheses.length} dimmed={dim("hypotheses")}>
        {f.hypotheses.length ? (
          <div className="space-y-2">
            {f.hypotheses.map((h) => (
              <HypothesisCard key={h.id} hypothesis={h} onCite={onCite} />
            ))}
          </div>
        ) : (
          <p className="text-xs text-muted-foreground">No rule matched the evidence, so no hypothesis was proposed.</p>
        )}
      </KindSection>
    ),
    gaps: (
      <KindSection kind="gaps" count={f.gaps.length} dimmed={dim("gaps")}>
        {f.gaps.length ? (
          <ul className="space-y-1 text-sm">
            {f.gaps.map((g, i) => (
              <li key={`${g.kind}-${i}`} className="flex items-start gap-2">
                <Badge variant={g.kind === "contradiction" ? "down" : "degraded"} className="mt-0.5">
                  {g.kind === "contradiction" ? "Contradiction" : g.kind === "missing" ? "Missing" : "Unavailable"}
                </Badge>
                <UntrustedText text={g.text} />
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-xs text-muted-foreground">No contradictions, and every planned source answered.</p>
        )}
      </KindSection>
    ),
    validation: (
      <KindSection kind="validation" dimmed={dim("validation")}>
        {f.validation.length ? (
          <div className="space-y-3">
            <ul className="grid gap-1 text-sm sm:grid-cols-2">
              {f.validation.map((c) => {
                const meta = CHECK_ICON[c.result];
                const Icon = meta.icon;
                return (
                  <li key={c.key} className="flex items-start gap-2" title={c.question}>
                    <Icon aria-hidden className={cn("mt-0.5 size-4 shrink-0", meta.className)} />
                    <span>
                      {c.label}: <span className="font-medium">{meta.word}</span>
                    </span>
                  </li>
                );
              })}
            </ul>
            <ConfidenceBreakdown
              breakdown={report.hypotheses.find((h) => h.cause === report.root_cause)?.confidence ?? report.confidence_breakdown}
              modelEstimated={modelEstimated}
            />
          </div>
        ) : (
          <p className="text-xs text-muted-foreground">Nothing to validate: no leading hypothesis.</p>
        )}
      </KindSection>
    ),
    diagnosis: (
      <KindSection kind="diagnosis" dimmed={dim("diagnosis")}>
        {f.diagnosis ? (
          <div className="space-y-2">
            {f.documentationOnly ? (
              <Badge variant="degraded">Based on documentation only: no live telemetry was available</Badge>
            ) : null}
            {f.diagnosis.unsupported ? (
              <Badge variant="degraded">
                <CircleSlash aria-hidden /> Unsupported: no evidence in this report backs this claim
              </Badge>
            ) : null}
            <p className="text-sm font-medium" data-testid="diagnosis-text">
              <UntrustedText text={f.diagnosis.text} />
            </p>
            {f.diagnosis.refs.length ? (
              <div>
                <p className="mb-1 text-xs font-medium text-muted-foreground">Backed by</p>
                <div className="flex flex-wrap gap-1">
                  {f.diagnosis.refs.map((r) => (
                    <Citation key={r.id} evidenceRef={r} onCite={onCite} />
                  ))}
                </div>
              </div>
            ) : null}
            {llmSummary ? (
              <div className="rounded-md border border-dashed p-2 text-xs">
                <p className="mb-1 font-medium">Model-written summary (not evidence)</p>
                <UntrustedText text={llmSummary} />
              </div>
            ) : null}
          </div>
        ) : (
          <p className="text-xs text-muted-foreground">No conclusion.</p>
        )}
      </KindSection>
    ),
    recommendation: (
      <KindSection kind="recommendation" count={f.recommendations.length} dimmed={dim("recommendation")}>
        {f.recommendations.length ? (
          <ul className="space-y-2">
            {f.recommendations.map((r, i) => (
              <li key={i} className="rounded-md border p-2.5">
                <div className="flex flex-wrap items-start justify-between gap-2">
                  <div className="min-w-0 flex-1">
                    <p className="text-sm font-medium">
                      <UntrustedText text={r.action} />
                    </p>
                    <p className="text-xs text-muted-foreground">
                      <UntrustedText text={r.rationale} />
                    </p>
                  </div>
                  <ApprovalDialog recommendation={r} service={report.service} />
                </div>
                <div className="mt-1.5 flex flex-wrap items-center gap-1">
                  {r.requires_human_approval ? <Badge variant="outline">Requires human approval</Badge> : null}
                  {r.refs.map((ref) => (
                    <Citation key={ref.id} evidenceRef={ref} onCite={onCite} />
                  ))}
                </div>
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-xs text-muted-foreground">No recommendation was made.</p>
        )}
      </KindSection>
    ),
  };

  return (
    <div className="space-y-3" data-testid="findings">
      {SECTION_ORDER.map((kind) => (
        <div key={kind}>{sections[kind]}</div>
      ))}
    </div>
  );
}
