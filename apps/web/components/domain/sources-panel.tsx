"use client";

import { ChevronRight } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import type { Report, ToolCall } from "@/lib/api/schemas";
import { formatClock, formatMs } from "@/lib/format";
import { cn } from "@/lib/utils";
import { EvidenceItem, type SourceTarget } from "./evidence";
import { JsonView } from "./json-view";
import { StatusBadge } from "./status-badge";
import { EmptyState } from "./states";
import { UntrustedText } from "./untrusted-text";

type LogEntry = { timestamp?: string; level?: string; message?: string; service?: string };

export function ToolCallRow({ call, index, highlighted }: { call: ToolCall; index: number; highlighted: boolean }) {
  const [open, setOpen] = useState(false);
  useEffect(() => {
    if (highlighted) setOpen(true);
  }, [highlighted]);
  const panelId = `tool-call-${index}-raw`;
  return (
    <li
      id={`source-tool-${index}`}
      data-tool={call.tool}
      data-highlighted={highlighted || undefined}
      tabIndex={-1}
      className={cn("rounded-md border", highlighted && "bg-accent ring-2 ring-ring")}
    >
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        aria-controls={panelId}
        className="flex w-full items-start gap-2 p-2 text-left"
      >
        <ChevronRight aria-hidden className={cn("mt-0.5 size-4 shrink-0 transition-transform", open && "rotate-90")} />
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <span className="font-mono text-xs font-medium">{call.tool}</span>
            <StatusBadge status={call.status} label={call.status} />
            <span className="ml-auto font-mono text-xs text-muted-foreground">{formatMs(call.duration_ms)}</span>
          </div>
          <p className="mt-0.5 truncate font-mono text-[11px] text-muted-foreground">
            {Object.entries(call.arguments)
              .map(([k, v]) => `${k}=${typeof v === "string" ? v : JSON.stringify(v)}`)
              .join(" ")}
          </p>
          {call.result_summary ? <p className="mt-0.5 text-xs">{call.result_summary}</p> : null}
          {call.error ? (
            <p className="mt-0.5 text-xs text-status-down-text">
              <UntrustedText text={call.error} />
            </p>
          ) : null}
        </div>
      </button>
      {open ? (
        <div id={panelId} className="space-y-2 border-t p-2">
          <p className="text-xs font-medium text-muted-foreground">Arguments</p>
          <JsonView value={call.arguments} label={`${call.tool} arguments`} />
          <p className="text-xs font-medium text-muted-foreground">Result (trimmed)</p>
          {call.result ? (
            <JsonView value={call.result} label={`${call.tool} raw result`} />
          ) : (
            <p className="text-xs text-muted-foreground">No raw result was recorded.</p>
          )}
        </div>
      ) : null}
    </li>
  );
}

export function logsFrom(calls: ToolCall[]): LogEntry[] {
  return calls
    .filter((c) => c.tool === "get_recent_logs" && c.result)
    .flatMap((c) => {
      const entries = (c.result as Record<string, unknown>)["entries"] ?? (c.result as Record<string, unknown>)["logs"];
      return Array.isArray(entries) ? (entries as LogEntry[]) : [];
    });
}

export function SourcesPanel({ report, target }: { report: Report; target: SourceTarget | null }) {
  const [tab, setTab] = useState<SourceTarget["tab"]>("documents");
  const logs = useMemo(() => logsFrom(report.tool_calls), [report.tool_calls]);
  const highlightedTool = target?.tab === "tools" ? report.tool_calls.findIndex((c) => c.tool === target.id) : -1;

  useEffect(() => {
    if (!target) return;
    setTab(target.tab);
    const id = target.tab === "documents" ? `source-doc-${target.id}` : `source-tool-${highlightedTool}`;
    // Wait for the tab content to mount before scrolling to and focusing the item.
    const handle = window.setTimeout(() => {
      const el = document.getElementById(id);
      el?.scrollIntoView({ block: "nearest", behavior: "smooth" });
      el?.focus({ preventScroll: true });
    }, 50);
    return () => window.clearTimeout(handle);
  }, [target, highlightedTool]);

  return (
    <Tabs value={tab} onValueChange={(v) => setTab(v as SourceTarget["tab"])}>
      <TabsList aria-label="Sources">
        <TabsTrigger value="documents">Documents ({report.evidence.length})</TabsTrigger>
        <TabsTrigger value="tools">Tool calls ({report.tool_calls.length})</TabsTrigger>
        <TabsTrigger value="logs">Logs ({logs.length})</TabsTrigger>
      </TabsList>
      <TabsContent value="documents" className="space-y-1">
        {report.evidence.length ? (
          report.evidence.map((e) => (
            <EvidenceItem key={e.id} evidence={e} anchor highlighted={target?.tab === "documents" && target.id === e.id} />
          ))
        ) : (
          <EmptyState title="No documents retrieved">
            The knowledge base returned nothing for this question, or it was unavailable.
          </EmptyState>
        )}
      </TabsContent>
      <TabsContent value="tools">
        {report.tool_calls.length ? (
          <ul className="space-y-1.5">
            {report.tool_calls.map((c, i) => (
              <ToolCallRow key={`${c.tool}-${i}`} call={c} index={i} highlighted={i === highlightedTool} />
            ))}
          </ul>
        ) : (
          <EmptyState title="No tool calls">The agent did not call any operational tools.</EmptyState>
        )}
      </TabsContent>
      <TabsContent value="logs">
        {logs.length ? (
          <ol className="max-h-[32rem] space-y-1 overflow-auto font-mono text-[11px]" aria-label="Log excerpts">
            {logs.map((l, i) => (
              <li key={i} className="rounded-sm border-l-2 border-l-border bg-muted/40 px-2 py-1">
                <span className="text-muted-foreground">{l.timestamp ? formatClock(l.timestamp) : "—"}</span>{" "}
                <span className={cn("font-semibold", l.level === "error" && "text-status-down-text")}>{l.level ?? ""}</span>{" "}
                <UntrustedText text={l.message ?? JSON.stringify(l)} />
              </li>
            ))}
          </ol>
        ) : (
          <EmptyState title="No log excerpts">
            The agent did not fetch logs for this investigation, or Loki was unavailable.
          </EmptyState>
        )}
      </TabsContent>
    </Tabs>
  );
}
