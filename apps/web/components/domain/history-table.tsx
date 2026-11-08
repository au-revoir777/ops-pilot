"use client";

import {
  flexRender,
  getCoreRowModel,
  useReactTable,
  type ColumnDef,
  type SortingState,
} from "@tanstack/react-table";
import { ArrowDown, ArrowUp, ArrowUpDown, ChevronLeft, ChevronRight } from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input, Label, NativeSelect } from "@/components/ui/input";
import { useInvestigations, useServices } from "@/hooks/use-api";
import type { InvestigationQuery } from "@/lib/api/client";
import type { InvestigationListItem, Severity } from "@/lib/api/schemas";
import { formatConfidence, formatMs, formatTimestamp, humanize } from "@/lib/format";
import { cn } from "@/lib/utils";
import { StatusBadge } from "./status-badge";
import { EmptyState, ErrorState, LoadingRows } from "./states";

// Sorting, filtering and pagination all happen in the API (GET /api/investigations
// with service/severity/q/since/until/sort/order/limit/offset); the table only renders a page.

const PAGE_SIZES = [10, 25, 50];
const SORTABLE = new Set(["created_at", "latency_ms", "confidence"]);

function useDebounced<T>(value: T, ms = 300) {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const id = window.setTimeout(() => setDebounced(value), ms);
    return () => window.clearTimeout(id);
  }, [value, ms]);
  return debounced;
}

export function HistoryTable() {
  const router = useRouter();
  const [sorting, setSorting] = useState<SortingState>([{ id: "created_at", desc: true }]);
  const [pageIndex, setPageIndex] = useState(0);
  const [pageSize, setPageSize] = useState(25);
  const [service, setService] = useState("");
  const [severity, setSeverity] = useState<Severity | "">("");
  const [status, setStatus] = useState("");
  const [text, setText] = useState("");
  const [since, setSince] = useState("");
  const [until, setUntil] = useState("");
  const q = useDebounced(text);
  const services = useServices({ refetchInterval: false });

  const params: InvestigationQuery = {
    limit: pageSize,
    offset: pageIndex * pageSize,
    sort: (sorting[0]?.id as InvestigationQuery["sort"]) ?? "created_at",
    order: sorting[0]?.desc === false ? "asc" : "desc",
    service: service || undefined,
    severity: severity || undefined,
    status: (status || undefined) as InvestigationQuery["status"],
    q: q || undefined,
    since: since ? new Date(`${since}T00:00:00`).toISOString() : undefined,
    until: until ? new Date(`${until}T23:59:59`).toISOString() : undefined,
  };
  const list = useInvestigations(params);

  // Any filter change returns to the first page.
  useEffect(() => setPageIndex(0), [service, severity, status, q, since, until, pageSize]);

  const columns = useMemo<ColumnDef<InvestigationListItem>[]>(
    () => [
      { id: "created_at", header: "Time", cell: ({ row }) => <span className="font-mono whitespace-nowrap">{formatTimestamp(row.original.created_at)}</span> },
      { id: "service", header: "Service", cell: ({ row }) => <span className="font-mono">{row.original.service ?? "—"}</span> },
      {
        id: "severity",
        header: "Severity",
        cell: ({ row }) =>
          row.original.severity ? (
            <Badge variant={row.original.severity === "SEV1" ? "down" : row.original.severity === "SEV2" ? "degraded" : "outline"}>{row.original.severity}</Badge>
          ) : (
            "—"
          ),
      },
      { id: "query", header: "Query", cell: ({ row }) => <span className="line-clamp-2 min-w-48">{row.original.query ?? "From an incident"}</span> },
      {
        id: "diagnosis",
        header: "Diagnosis",
        cell: ({ row }) => <span className="line-clamp-2 min-w-40">{row.original.root_cause ? humanize(row.original.root_cause) : row.original.status === "completed" ? "No root cause" : "—"}</span>,
      },
      { id: "confidence", header: "Est. confidence", cell: ({ row }) => <span className="font-mono">{row.original.root_cause ? formatConfidence(row.original.confidence) : "—"}</span> },
      { id: "latency_ms", header: "Latency", cell: ({ row }) => <span className="font-mono">{formatMs(row.original.latency_ms)}</span> },
      { id: "status", header: "Status", cell: ({ row }) => <StatusBadge status={row.original.status} label={row.original.status} /> },
    ],
    [],
  );

  const total = list.data?.total ?? 0;
  const table = useReactTable({
    data: list.data?.items ?? [],
    columns,
    getCoreRowModel: getCoreRowModel(),
    manualSorting: true,
    manualPagination: true,
    manualFiltering: true,
    rowCount: total,
    state: { sorting, pagination: { pageIndex, pageSize } },
    onSortingChange: (updater) => {
      setSorting(updater);
      setPageIndex(0);
    },
    enableSortingRemoval: false,
  });
  const pages = Math.max(1, Math.ceil(total / pageSize));

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-end gap-2" role="search" aria-label="Filter investigations">
        <div className="min-w-48 flex-1 space-y-1">
          <Label htmlFor="h-search">Search</Label>
          <Input id="h-search" type="search" placeholder="Query, diagnosis or root cause" value={text} onChange={(e) => setText(e.target.value)} />
        </div>
        <div className="space-y-1">
          <Label htmlFor="h-service">Service</Label>
          <NativeSelect id="h-service" value={service} onChange={(e) => setService(e.target.value)} className="w-36">
            <option value="">All</option>
            {(services.data?.services ?? []).map((s) => (
              <option key={s.name} value={s.name}>
                {s.name}
              </option>
            ))}
          </NativeSelect>
        </div>
        <div className="space-y-1">
          <Label htmlFor="h-severity">Severity</Label>
          <NativeSelect id="h-severity" value={severity} onChange={(e) => setSeverity(e.target.value as Severity | "")} className="w-28">
            <option value="">All</option>
            {["SEV1", "SEV2", "SEV3", "SEV4"].map((s) => (
              <option key={s}>{s}</option>
            ))}
          </NativeSelect>
        </div>
        <div className="space-y-1">
          <Label htmlFor="h-status">Status</Label>
          <NativeSelect id="h-status" value={status} onChange={(e) => setStatus(e.target.value)} className="w-32">
            <option value="">All</option>
            {["completed", "failed", "running", "pending"].map((s) => (
              <option key={s}>{s}</option>
            ))}
          </NativeSelect>
        </div>
        <div className="space-y-1">
          <Label htmlFor="h-since">From</Label>
          <Input id="h-since" type="date" value={since} onChange={(e) => setSince(e.target.value)} className="w-36" />
        </div>
        <div className="space-y-1">
          <Label htmlFor="h-until">To</Label>
          <Input id="h-until" type="date" value={until} onChange={(e) => setUntil(e.target.value)} className="w-36" />
        </div>
      </div>

      {list.isPending ? (
        <LoadingRows rows={8} label="Loading history" />
      ) : list.isError ? (
        <ErrorState error={list.error} onRetry={() => void list.refetch()} />
      ) : total === 0 ? (
        <EmptyState title="No investigations match">Clear a filter, or start an investigation to build up history.</EmptyState>
      ) : (
        <div className="overflow-x-auto rounded-md border">
          <table className={cn("w-full text-xs", list.isPlaceholderData && "opacity-60")} aria-busy={list.isFetching}>
            <caption className="sr-only">Investigation history, page {pageIndex + 1} of {pages}. Activate a row to open it.</caption>
            <thead className="bg-muted/60">
              {table.getHeaderGroups().map((group) => (
                <tr key={group.id}>
                  {group.headers.map((header) => {
                    const sortable = SORTABLE.has(header.column.id);
                    const dir = sorting[0]?.id === header.column.id ? (sorting[0]?.desc ? "descending" : "ascending") : "none";
                    return (
                      <th key={header.id} scope="col" aria-sort={sortable ? dir : undefined} className="px-2 py-1.5 text-left font-medium whitespace-nowrap">
                        {sortable ? (
                          <button type="button" onClick={header.column.getToggleSortingHandler()} className="inline-flex items-center gap-1 hover:text-foreground">
                            {flexRender(header.column.columnDef.header, header.getContext())}
                            {dir === "ascending" ? <ArrowUp className="size-3" aria-hidden /> : dir === "descending" ? <ArrowDown className="size-3" aria-hidden /> : <ArrowUpDown className="size-3 text-muted-foreground" aria-hidden />}
                          </button>
                        ) : (
                          flexRender(header.column.columnDef.header, header.getContext())
                        )}
                      </th>
                    );
                  })}
                </tr>
              ))}
            </thead>
            <tbody>
              {table.getRowModel().rows.map((row) => (
                <tr
                  key={row.id}
                  tabIndex={0}
                  onClick={() => router.push(`/investigations/${row.original.id}`)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" || e.key === " ") {
                      e.preventDefault();
                      router.push(`/investigations/${row.original.id}`);
                    }
                  }}
                  aria-label={`Open investigation: ${row.original.query ?? row.original.id}`}
                  className="cursor-pointer border-t align-top hover:bg-accent/50 focus-visible:bg-accent/50"
                >
                  {row.getVisibleCells().map((cell) => (
                    <td key={cell.id} className="px-2 py-1.5">
                      {flexRender(cell.column.columnDef.cell, cell.getContext())}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {total > 0 ? (
        <div className="flex flex-wrap items-center justify-between gap-2 text-xs">
          <span className="text-muted-foreground">
            {pageIndex * pageSize + 1}–{Math.min(total, (pageIndex + 1) * pageSize)} of {total}
          </span>
          <div className="flex items-center gap-2">
            <Label htmlFor="h-size" className="font-normal">
              Rows
            </Label>
            <NativeSelect id="h-size" value={pageSize} onChange={(e) => setPageSize(Number(e.target.value))} className="h-7 w-16 text-xs">
              {PAGE_SIZES.map((n) => (
                <option key={n}>{n}</option>
              ))}
            </NativeSelect>
            <Button variant="outline" size="icon" className="size-7" onClick={() => setPageIndex((p) => p - 1)} disabled={pageIndex === 0} aria-label="Previous page">
              <ChevronLeft />
            </Button>
            <span>
              Page {pageIndex + 1} of {pages}
            </span>
            <Button variant="outline" size="icon" className="size-7" onClick={() => setPageIndex((p) => p + 1)} disabled={pageIndex + 1 >= pages} aria-label="Next page">
              <ChevronRight />
            </Button>
          </div>
        </div>
      ) : null}
    </div>
  );
}
