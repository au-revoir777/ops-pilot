import { Info, TriangleAlert } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Tooltip } from "@/components/ui/tooltip";
import type { ConfidenceBreakdown as Breakdown } from "@/lib/api/schemas";
import { CONFIDENCE_FORMULA, LOW_CONFIDENCE_THRESHOLD } from "@/lib/epistemic";
import { formatConfidence } from "@/lib/format";
import { cn } from "@/lib/utils";

// Confidence is a documented heuristic, never "accuracy" or "probability"
// (UI prompt 7.1). Low values get a caution state instead of a reassuring one.

export function ConfidenceBadge({
  value,
  modelEstimated = false,
  className,
}: {
  value: number | null | undefined;
  modelEstimated?: boolean;
  className?: string;
}) {
  if (value == null) {
    return (
      <Badge variant="unknown" className={className}>
        No confidence
      </Badge>
    );
  }
  const low = value < LOW_CONFIDENCE_THRESHOLD;
  return (
    <Badge
      variant={low ? "degraded" : "outline"}
      className={cn("font-mono", className)}
      data-low={low || undefined}
      aria-label={`Estimated confidence ${formatConfidence(value)}${low ? ", low" : ""}${modelEstimated ? ", model-estimated" : ""}`}
    >
      {low ? <TriangleAlert aria-hidden /> : null}
      {formatConfidence(value)} est. confidence
      {modelEstimated ? <span className="font-sans">· Model-estimated</span> : null}
    </Badge>
  );
}

const ROWS: { key: keyof Breakdown; label: string; max: number }[] = [
  { key: "base", label: "Symptom confirmed", max: 0.1 },
  { key: "temporal", label: "Temporal correlation", max: 0.25 },
  { key: "metric", label: "Metric correlation", max: 0.25 },
  { key: "log", label: "Log correlation", max: 0.2 },
  { key: "deployment", label: "Deployment correlation", max: 0.1 },
  { key: "knowledge", label: "RAG support", max: 0.1 },
];

export function ConfidenceBreakdown({
  breakdown,
  modelEstimated = false,
}: {
  breakdown: Breakdown | null | undefined;
  modelEstimated?: boolean;
}) {
  if (!breakdown) {
    return <p className="text-xs text-muted-foreground">No confidence breakdown: no hypothesis was selected.</p>;
  }
  const raw = ROWS.reduce((sum, r) => sum + breakdown[r.key], 0) + breakdown.contradictions;
  return (
    <div className="space-y-2" data-testid="confidence-breakdown">
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <span className="text-sm font-semibold">Estimated confidence</span>
          <ConfidenceBadge value={breakdown.value} modelEstimated={modelEstimated} />
        </div>
        <Tooltip content={CONFIDENCE_FORMULA} side="left">
          <button type="button" className="inline-flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground">
            <Info className="size-3.5" aria-hidden /> How it&apos;s computed
          </button>
        </Tooltip>
      </div>
      <table className="w-full text-xs">
        <caption className="sr-only">Confidence components</caption>
        <thead className="sr-only">
          <tr>
            <th scope="col">Component</th>
            <th scope="col">Bar</th>
            <th scope="col">Contribution</th>
          </tr>
        </thead>
        <tbody>
          {ROWS.map((r) => {
            const v = breakdown[r.key];
            return (
              <tr key={r.key} className="h-6">
                <th scope="row" className="w-44 pr-2 text-left font-normal text-muted-foreground">
                  {r.label}
                </th>
                <td className="pr-2">
                  <div className="h-1.5 w-full rounded-full bg-muted">
                    <div
                      className={cn("h-1.5 rounded-full", v > 0 ? "bg-primary" : "bg-transparent")}
                      style={{ width: `${(v / r.max) * 100}%` }}
                    />
                  </div>
                </td>
                <td className="w-24 text-right font-mono tabular">
                  {v > 0 ? `+${v.toFixed(2)}` : "0.00"}
                  <span className="text-muted-foreground"> / {r.max.toFixed(2)}</span>
                </td>
              </tr>
            );
          })}
          <tr className="h-6">
            <th scope="row" className="pr-2 text-left font-normal text-muted-foreground">
              Contradictions
            </th>
            <td className="pr-2 text-muted-foreground">−0.25 each</td>
            <td className={cn("text-right font-mono tabular", breakdown.contradictions < 0 && "font-semibold text-status-down-text")}>
              {breakdown.contradictions.toFixed(2)}
            </td>
          </tr>
          <tr className="h-6 border-t">
            <th scope="row" className="pr-2 text-left font-normal text-muted-foreground">
              Evidence coverage factor
            </th>
            <td className="pr-2 text-muted-foreground">0.6 + 0.4 × sources answered</td>
            <td className="text-right font-mono tabular">× {breakdown.coverage_factor.toFixed(2)}</td>
          </tr>
          <tr className="h-6">
            <th scope="row" className="pr-2 text-left font-medium">
              Result
            </th>
            <td className="pr-2 text-muted-foreground">
              min({raw.toFixed(2)}, 0.95) × {breakdown.coverage_factor.toFixed(2)}
            </td>
            <td className="text-right font-mono font-semibold tabular">{breakdown.value.toFixed(2)}</td>
          </tr>
        </tbody>
      </table>
      <p className="text-[11px] text-muted-foreground">
        A rule-based heuristic over the evidence, not a probability.
        {modelEstimated ? " Parts of this value were estimated by a language model." : ""}
      </p>
    </div>
  );
}
