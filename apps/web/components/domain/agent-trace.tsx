"use client";

import { BrainCircuit, CheckCircle2, Database, GitBranch, ListOrdered, Search, Sparkles, Workflow, type LucideIcon } from "lucide-react";
import dynamic from "next/dynamic";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import type { TraceStep } from "@/lib/api/schemas";
import { formatMs } from "@/lib/format";
import { cn } from "@/lib/utils";

// The trace shows only steps the agent actually executed, with their measured
// durations, straight from report.trace. Nothing is animated or inferred.

export const NODE_META: Record<string, { label: string; icon: LucideIcon }> = {
  planner: { label: "Planner", icon: ListOrdered },
  rag: { label: "RAG search", icon: Search },
  mcp: { label: "MCP investigation", icon: Database },
  hypothesis: { label: "Hypothesis", icon: Sparkles },
  validator: { label: "Validator", icon: CheckCircle2 },
  synthesizer: { label: "Synthesizer", icon: BrainCircuit },
};

export function nodeLabel(node: string) {
  return NODE_META[node]?.label ?? node;
}

const TraceGraph = dynamic(() => import("./agent-trace-graph").then((m) => m.AgentTraceGraph), {
  ssr: false,
  loading: () => <Skeleton className="h-96 w-full" />,
});

export type TraceSelection = { index: number; node: string } | null;

export function AgentTrace({
  steps,
  selected,
  onSelect,
}: {
  steps: TraceStep[];
  selected: TraceSelection;
  onSelect: (selection: TraceSelection) => void;
}) {
  const [view, setView] = useState<"steps" | "graph">("steps");
  const total = steps.reduce((sum, s) => sum + s.duration_ms, 0);
  const toggle = (index: number, node: string) =>
    onSelect(selected?.index === index ? null : { index, node });

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between gap-2">
        <p className="text-xs text-muted-foreground">
          {steps.length} steps · {formatMs(total)}
        </p>
        <div className="flex gap-1" role="group" aria-label="Trace view">
          <Button size="sm" variant={view === "steps" ? "secondary" : "ghost"} aria-pressed={view === "steps"} onClick={() => setView("steps")}>
            <Workflow /> Steps
          </Button>
          <Button size="sm" variant={view === "graph" ? "secondary" : "ghost"} aria-pressed={view === "graph"} onClick={() => setView("graph")}>
            <GitBranch /> Graph
          </Button>
        </div>
      </div>
      {view === "graph" ? (
        <TraceGraph steps={steps} selected={selected} onToggle={toggle} />
      ) : (
        <ol className="relative space-y-1" aria-label="Agent steps">
          {steps.map((step, i) => {
            const meta = NODE_META[step.node];
            const Icon = meta?.icon ?? Workflow;
            const loop = step.node === "mcp" && steps.slice(0, i).some((s) => s.node === "mcp");
            const active = selected?.index === i;
            return (
              <li key={`${step.node}-${i}`} className="relative pl-6">
                {i < steps.length - 1 ? (
                  <span aria-hidden className="absolute top-6 bottom-[-0.25rem] left-[0.6875rem] w-px bg-border" />
                ) : null}
                <span aria-hidden className="absolute top-2 left-1 flex size-4 items-center justify-center rounded-full bg-status-healthy text-status-healthy-foreground">
                  <CheckCircle2 className="size-3" />
                </span>
                <button
                  type="button"
                  aria-pressed={active}
                  onClick={() => toggle(i, step.node)}
                  className={cn(
                    "w-full rounded-md border px-2 py-1.5 text-left hover:bg-accent",
                    active ? "border-ring bg-accent" : "border-transparent",
                  )}
                >
                  <span className="flex items-center gap-1.5 text-sm font-medium">
                    <Icon aria-hidden className="size-3.5 text-muted-foreground" />
                    {meta?.label ?? step.node}
                    {loop ? <span className="text-xs font-normal text-muted-foreground">(more tools)</span> : null}
                    <span className="ml-auto font-mono text-xs font-normal text-muted-foreground">{formatMs(step.duration_ms)}</span>
                  </span>
                  <span className="mt-0.5 block text-xs text-muted-foreground">
                    <span className="sr-only">Done. </span>
                    {step.summary}
                  </span>
                </button>
              </li>
            );
          })}
        </ol>
      )}
      {selected ? (
        <p className="text-xs text-muted-foreground">
          Showing what {nodeLabel(selected.node)} produced.{" "}
          <button type="button" className="text-foreground underline underline-offset-2" onClick={() => onSelect(null)}>
            Show all
          </button>
        </p>
      ) : null}
    </div>
  );
}
