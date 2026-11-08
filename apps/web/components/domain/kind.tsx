import {
  BookOpen,
  ClipboardCheck,
  Gauge,
  Lightbulb,
  ListChecks,
  SearchX,
  Stethoscope,
  type LucideIcon,
} from "lucide-react";
import type * as React from "react";
import { SECTION_META, type SectionKind } from "@/lib/epistemic";
import { cn } from "@/lib/utils";

// Epistemic kinds: each section has its own icon, word and border color from
// the --kind-* tokens. Colors are only used for borders and icons; text stays
// in foreground colors so contrast holds in every palette.

export const KIND_ICON: Record<SectionKind, LucideIcon> = {
  facts: Gauge,
  retrieved: BookOpen,
  hypotheses: Lightbulb,
  gaps: SearchX,
  validation: ListChecks,
  diagnosis: Stethoscope,
  recommendation: ClipboardCheck,
};

const BORDER: Record<SectionKind, string> = {
  facts: "border-l-kind-fact",
  retrieved: "border-l-kind-retrieved",
  hypotheses: "border-l-kind-hypothesis",
  gaps: "border-l-kind-gap",
  validation: "border-l-kind-validation",
  diagnosis: "border-l-kind-diagnosis",
  recommendation: "border-l-kind-recommendation",
};

const ICON_COLOR: Record<SectionKind, string> = {
  facts: "text-kind-fact",
  retrieved: "text-kind-retrieved",
  hypotheses: "text-kind-hypothesis",
  gaps: "text-kind-gap",
  validation: "text-kind-validation",
  diagnosis: "text-kind-diagnosis",
  recommendation: "text-kind-recommendation",
};

const BADGE_WORD: Record<SectionKind, string> = {
  facts: "Fact",
  retrieved: "Retrieved",
  hypotheses: "Hypothesis",
  gaps: "Gap",
  validation: "Validation",
  diagnosis: "Most likely cause",
  recommendation: "Recommendation",
};

export function KindBadge({ kind, className }: { kind: SectionKind; className?: string }) {
  const Icon = KIND_ICON[kind];
  return (
    <span
      data-kind={kind}
      className={cn(
        "inline-flex items-center gap-1 rounded-sm border border-current/0 bg-muted px-1.5 py-0.5 text-[11px] leading-none font-medium text-foreground",
        className,
      )}
    >
      <Icon aria-hidden className={cn("size-3", ICON_COLOR[kind])} />
      {BADGE_WORD[kind]}
    </span>
  );
}

export function KindSection({
  kind,
  count,
  children,
  dimmed = false,
  id,
}: {
  kind: SectionKind;
  count?: number;
  children: React.ReactNode;
  dimmed?: boolean;
  id?: string;
}) {
  const meta = SECTION_META[kind];
  const Icon = KIND_ICON[kind];
  const headingId = `section-${kind}`;
  return (
    <section
      id={id}
      aria-labelledby={headingId}
      data-section={kind}
      className={cn("rounded-md border border-l-4 bg-card", BORDER[kind], dimmed && "opacity-45")}
    >
      <header className="flex items-start gap-2 px-3 pt-2.5 pb-1.5">
        <Icon aria-hidden className={cn("mt-0.5 size-4 shrink-0", ICON_COLOR[kind])} />
        <div className="min-w-0 flex-1">
          <h3 id={headingId} className="flex items-center gap-2 text-sm font-semibold">
            {meta.title}
            {count != null ? <span className="font-mono text-xs font-normal text-muted-foreground">{count}</span> : null}
          </h3>
          <p className="text-xs text-muted-foreground">{meta.description}</p>
        </div>
      </header>
      <div className="px-3 pb-3">{children}</div>
    </section>
  );
}
