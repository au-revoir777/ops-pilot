"use client";

// Lazy-loaded (next/dynamic) so React Flow only ships when the graph is opened.
import { Background, Handle, Position, ReactFlow, type Edge, type Node, type NodeProps } from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { useMemo } from "react";
import type { TraceStep } from "@/lib/api/schemas";
import { formatMs } from "@/lib/format";
import { cn } from "@/lib/utils";
import { NODE_META, type TraceSelection } from "./agent-trace";

type StepData = { step: TraceStep; index: number; active: boolean; onToggle: (i: number, node: string) => void };
type StepNode = Node<StepData, "step">;

function StepNodeView({ data }: NodeProps<StepNode>) {
  const meta = NODE_META[data.step.node];
  const Icon = meta?.icon;
  return (
    <button
      type="button"
      aria-pressed={data.active}
      aria-label={`${meta?.label ?? data.step.node}, done in ${formatMs(data.step.duration_ms)}: ${data.step.summary}`}
      onClick={() => data.onToggle(data.index, data.step.node)}
      className={cn(
        "w-56 rounded-md border bg-card px-2.5 py-1.5 text-left text-card-foreground shadow-sm",
        data.active ? "border-ring ring-2 ring-ring" : "hover:bg-accent",
      )}
    >
      <Handle type="target" position={Position.Top} className="!bg-border" isConnectable={false} />
      <span className="flex items-center gap-1.5 text-xs font-medium">
        {Icon ? <Icon aria-hidden className="size-3.5 text-muted-foreground" /> : null}
        {meta?.label ?? data.step.node}
        <span className="ml-auto font-mono text-[11px] font-normal text-muted-foreground">{formatMs(data.step.duration_ms)}</span>
      </span>
      <span className="mt-0.5 line-clamp-2 block text-[11px] text-muted-foreground">{data.step.summary}</span>
      <Handle type="source" position={Position.Bottom} className="!bg-border" isConnectable={false} />
    </button>
  );
}

const nodeTypes = { step: StepNodeView };

export function AgentTraceGraph({
  steps,
  selected,
  onToggle,
}: {
  steps: TraceStep[];
  selected: TraceSelection;
  onToggle: (index: number, node: string) => void;
}) {
  const { nodes, edges } = useMemo(() => {
    const nodes: StepNode[] = steps.map((step, index) => ({
      id: String(index),
      type: "step",
      // A follow-up MCP round is drawn to the right, so the loop back reads as a loop.
      position: { x: step.node === "mcp" && steps.slice(0, index).some((s) => s.node === "mcp") ? 260 : 0, y: index * 90 },
      data: { step, index, active: selected?.index === index, onToggle },
      draggable: false,
      connectable: false,
    }));
    const edges: Edge[] = steps.slice(1).map((step, i) => {
      const loop = step.node === "mcp" && steps[i]?.node === "validator";
      return {
        id: `e${i}`,
        source: String(i),
        target: String(i + 1),
        label: loop ? "more tools" : undefined,
        animated: false,
        style: { stroke: "var(--muted-foreground)" },
        labelStyle: { fill: "var(--foreground)", fontSize: 11 },
        labelBgStyle: { fill: "var(--card)" },
      };
    });
    return { nodes, edges };
  }, [steps, selected, onToggle]);

  return (
    <div className="h-[28rem] rounded-md border bg-muted/30" aria-label="Agent trace graph">
      <ReactFlow
        nodes={nodes}
        edges={edges}
        nodeTypes={nodeTypes}
        fitView
        fitViewOptions={{ padding: 0.15 }}
        nodesDraggable={false}
        nodesConnectable={false}
        elementsSelectable={false}
        panOnScroll
        zoomOnScroll={false}
        colorMode="system"
      >
        <Background gap={16} size={1} color="var(--border)" />
      </ReactFlow>
    </div>
  );
}
