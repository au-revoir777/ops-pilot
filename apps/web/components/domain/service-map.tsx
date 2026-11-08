"use client";

// Lazy-loaded with next/dynamic from the System Status page.
import { Background, Handle, Position, ReactFlow, type Edge, type Node, type NodeProps } from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { useMemo } from "react";
import { StatusBadge } from "./status-badge";

export type MapComponent = { id: string; label: string; status: string; detail: string; x: number; y: number };
export type MapLink = { from: string; to: string; label?: string };

type MapNode = Node<{ component: MapComponent }, "component">;

function ComponentNode({ data }: NodeProps<MapNode>) {
  const c = data.component;
  return (
    <div
      tabIndex={0}
      role="group"
      aria-label={`${c.label}: ${c.status}. ${c.detail}`}
      className="w-44 rounded-md border bg-card px-2.5 py-1.5 text-card-foreground shadow-sm"
    >
      <Handle type="target" position={Position.Left} className="!bg-border" isConnectable={false} />
      <div className="flex items-center justify-between gap-1">
        <span className="truncate text-xs font-medium">{c.label}</span>
        <StatusBadge status={c.status} className="px-1 text-[10px]" />
      </div>
      <p className="mt-0.5 truncate text-[11px] text-muted-foreground">{c.detail}</p>
      <Handle type="source" position={Position.Right} className="!bg-border" isConnectable={false} />
    </div>
  );
}

const nodeTypes = { component: ComponentNode };

export function ServiceMap({ components, links }: { components: MapComponent[]; links: MapLink[] }) {
  const { nodes, edges } = useMemo(() => {
    const nodes: MapNode[] = components.map((c) => ({
      id: c.id,
      type: "component",
      position: { x: c.x, y: c.y },
      data: { component: c },
      draggable: false,
      connectable: false,
    }));
    const edges: Edge[] = links.map((l) => ({
      id: `${l.from}-${l.to}`,
      source: l.from,
      target: l.to,
      label: l.label,
      style: { stroke: "var(--muted-foreground)" },
      labelStyle: { fill: "var(--foreground)", fontSize: 10 },
      labelBgStyle: { fill: "var(--card)" },
    }));
    return { nodes, edges };
  }, [components, links]);

  return (
    <div className="h-[30rem] rounded-md border bg-muted/30" aria-label="Service map">
      <ReactFlow
        nodes={nodes}
        edges={edges}
        nodeTypes={nodeTypes}
        fitView
        fitViewOptions={{ padding: 0.1 }}
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
