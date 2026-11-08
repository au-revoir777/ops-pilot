"use client";

import { CircleSlash, FileText, Link2, Wrench } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import type { Observation, RetrievedEvidence } from "@/lib/api/schemas";
import type { EvidenceRef, HypothesisView } from "@/lib/epistemic";
import { formatClock, humanize } from "@/lib/format";
import { cn } from "@/lib/utils";
import { KindBadge } from "./kind";
import { QuotedExcerpt, UntrustedText } from "./untrusted-text";

export type SourceTarget = { tab: "documents" | "tools" | "logs"; id: string };

/** A link from a claim to the item that backs it; clicking highlights it in Sources. */
export function Citation({ evidenceRef, onCite }: { evidenceRef: EvidenceRef; onCite?: (t: SourceTarget) => void }) {
  if (evidenceRef.type === "missing") {
    return (
      <Badge variant="degraded" title="This reference is not in the investigation payload">
        <CircleSlash aria-hidden /> Unsupported: {evidenceRef.id}
      </Badge>
    );
  }
  const isDoc = evidenceRef.type === "evidence";
  const label = isDoc ? evidenceRef.item.citation : `${evidenceRef.item.id} · ${evidenceRef.item.source}`;
  return (
    <button
      type="button"
      onClick={() =>
        onCite?.(
          isDoc
            ? { tab: "documents", id: evidenceRef.item.id }
            : { tab: "tools", id: (evidenceRef.item as Observation).source },
        )
      }
      className="inline-flex max-w-full items-center gap-1 rounded-sm border bg-muted/60 px-1.5 py-0.5 font-mono text-[11px] text-foreground hover:bg-accent"
      aria-label={`Show source ${label}`}
    >
      {isDoc ? <FileText className="size-3 shrink-0" aria-hidden /> : <Wrench className="size-3 shrink-0" aria-hidden />}
      <span className="truncate">{label}</span>
    </button>
  );
}

export function FactItem({ observation, onCite }: { observation: Observation; onCite?: (t: SourceTarget) => void }) {
  return (
    <li className="flex flex-col gap-1 rounded-md px-1 py-1.5 hover:bg-muted/40 sm:flex-row sm:items-start sm:gap-3">
      <KindBadge kind="facts" className="mt-0.5 self-start" />
      <div className="min-w-0 flex-1">
        <p className="text-sm">
          <UntrustedText text={observation.statement} />
        </p>
        <p className="mt-0.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground">
          <span>{humanize(observation.kind)}</span>
          {observation.at ? <span className="font-mono">at {formatClock(observation.at)}</span> : null}
          <button
            type="button"
            className="inline-flex items-center gap-1 font-mono text-foreground underline-offset-2 hover:underline"
            onClick={() => onCite?.({ tab: "tools", id: observation.source })}
            aria-label={`Show tool call ${observation.source} that produced this fact`}
          >
            <Link2 className="size-3" aria-hidden />
            {observation.source}
          </button>
        </p>
      </div>
    </li>
  );
}

export function EvidenceItem({
  evidence,
  highlighted = false,
  compact = false,
  anchor = false,
}: {
  evidence: RetrievedEvidence;
  highlighted?: boolean;
  compact?: boolean;
  /** Only the Sources panel copy is a scroll target. */
  anchor?: boolean;
}) {
  return (
    <article
      id={anchor ? `source-doc-${evidence.id}` : undefined}
      data-highlighted={highlighted || undefined}
      tabIndex={-1}
      className={cn("rounded-md p-2", highlighted ? "bg-accent ring-2 ring-ring" : "hover:bg-muted/40")}
    >
      <div className="mb-1 flex items-start justify-between gap-2">
        <div className="min-w-0">
          <h4 className="text-sm font-medium">
            <UntrustedText text={evidence.title} />
          </h4>
          {evidence.section ? (
            <p className="text-xs text-muted-foreground">
              <UntrustedText text={evidence.section} />
            </p>
          ) : null}
        </div>
        <span className="shrink-0 font-mono text-xs text-muted-foreground" title="Relevance score (cosine similarity)">
          score {evidence.score.toFixed(2)}
        </span>
      </div>
      <QuotedExcerpt
        text={compact && evidence.excerpt.length > 280 ? `${evidence.excerpt.slice(0, 280)}…` : evidence.excerpt}
        source={evidence.citation}
        flags={evidence.flags}
      />
    </article>
  );
}

const HYPOTHESIS_BADGE = {
  supported: "healthy",
  weakened: "degraded",
  rejected: "down",
} as const;

export function HypothesisCard({ hypothesis, onCite }: { hypothesis: HypothesisView; onCite?: (t: SourceTarget) => void }) {
  return (
    <article
      className={cn("rounded-md border p-2.5", hypothesis.leading && "border-kind-diagnosis/70")}
      aria-label={`Hypothesis: ${hypothesis.statement}`}
    >
      <div className="mb-1 flex flex-wrap items-center gap-1.5">
        <KindBadge kind="hypotheses" />
        <Badge variant={HYPOTHESIS_BADGE[hypothesis.label]}>{humanize(hypothesis.label)}</Badge>
        {hypothesis.leading ? <Badge variant="outline">Leading</Badge> : null}
        {hypothesis.confidence ? (
          <span className="ml-auto font-mono text-xs text-muted-foreground">
            est. confidence {Math.round(hypothesis.confidence.value * 100)}%
          </span>
        ) : null}
      </div>
      <p className="text-sm">
        <UntrustedText text={hypothesis.statement} />
      </p>
      <p className="mt-0.5 font-mono text-[11px] text-muted-foreground">{hypothesis.cause}</p>
      {hypothesis.supportingRefs.length > 0 ? (
        <div className="mt-2">
          <p className="mb-1 text-xs font-medium text-muted-foreground">Supported by</p>
          <div className="flex flex-wrap gap-1">
            {hypothesis.supportingRefs.map((r) => (
              <Citation key={`s-${r.id}`} evidenceRef={r} onCite={onCite} />
            ))}
          </div>
        </div>
      ) : (
        <p className="mt-2 text-xs text-muted-foreground">No supporting evidence.</p>
      )}
      {hypothesis.contradictingRefs.length > 0 || hypothesis.contradictions.length > 0 ? (
        <div className="mt-2">
          <p className="mb-1 text-xs font-medium text-muted-foreground">Contradicted by</p>
          <ul className="list-disc space-y-0.5 pl-4 text-xs">
            {hypothesis.contradictions.map((c) => (
              <li key={c}>
                <UntrustedText text={c} />
              </li>
            ))}
          </ul>
          <div className="mt-1 flex flex-wrap gap-1">
            {hypothesis.contradictingRefs.map((r) => (
              <Citation key={`c-${r.id}`} evidenceRef={r} onCite={onCite} />
            ))}
          </div>
        </div>
      ) : null}
    </article>
  );
}
