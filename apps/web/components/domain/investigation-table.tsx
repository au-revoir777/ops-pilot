"use client";

import Link from "next/link";
import type { InvestigationSummary } from "@/lib/api/schemas";
import { formatAge, formatMs, humanize } from "@/lib/format";
import { ConfidenceBadge } from "./confidence";
import { StatusBadge } from "./status-badge";

export function RecentInvestigations({ items }: { items: InvestigationSummary[] }) {
  return (
    <ul className="divide-y">
      {items.map((i) => (
        <li key={i.id}>
          <Link href={`/investigations/${i.id}`} className="flex flex-wrap items-center gap-x-3 gap-y-1 px-1 py-2 hover:bg-accent/50">
            <StatusBadge status={i.status} label={i.status} />
            <span className="min-w-0 flex-1 truncate text-sm">{i.query ?? "Investigation from an incident"}</span>
            <span className="text-xs text-muted-foreground">{i.root_cause ? humanize(i.root_cause) : i.status === "completed" ? "No root cause" : ""}</span>
            {i.status === "completed" && i.root_cause ? <ConfidenceBadge value={i.confidence} /> : null}
            <span className="w-16 text-right font-mono text-xs text-muted-foreground">{formatMs(i.latency_ms)}</span>
            <span className="w-16 text-right text-xs text-muted-foreground">{formatAge(i.created_at)}</span>
          </Link>
        </li>
      ))}
    </ul>
  );
}
