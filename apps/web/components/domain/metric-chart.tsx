"use client";

import { memo, useId, useMemo, useState } from "react";
import { CartesianGrid, Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { Button } from "@/components/ui/button";
import type { Deployment, Point } from "@/lib/api/schemas";
import { formatClock, MISSING } from "@/lib/format";

// Charts come with a text alternative: a summary sentence for screen readers and
// a data-table toggle (UI prompt section 11). Deployments are drawn as vertical
// lines so deploy-versus-latency correlation is visible.

export type ChartSeries = { key: string; label: string; points: Point[]; color: string };

type Row = { t: number } & Record<string, number | null>;

function merge(series: ChartSeries[]): Row[] {
  const rows = new Map<number, Row>();
  for (const s of series) {
    for (const p of s.points) {
      const t = new Date(p.timestamp).getTime();
      const row = rows.get(t) ?? ({ t } as Row);
      row[s.key] = p.value;
      rows.set(t, row);
    }
  }
  return [...rows.values()].sort((a, b) => a.t - b.t);
}

function summarize(series: ChartSeries[], format: (v: number) => string): string {
  return series
    .map((s) => {
      const values = s.points.map((p) => p.value).filter((v): v is number => v != null);
      if (!values.length) return `${s.label}: no data`;
      const last = values[values.length - 1]!;
      return `${s.label}: latest ${format(last)}, min ${format(Math.min(...values))}, max ${format(Math.max(...values))}`;
    })
    .join("; ");
}

function MetricChartInner({
  title,
  series,
  format,
  deployments = [],
  height = 180,
}: {
  title: string;
  series: ChartSeries[];
  format: (v: number) => string;
  deployments?: Deployment[];
  height?: number;
}) {
  const [showTable, setShowTable] = useState(false);
  const rows = useMemo(() => merge(series), [series]);
  const summaryId = useId();
  const hasData = rows.some((r) => series.some((s) => r[s.key] != null));
  const [start, end] = [rows[0]?.t ?? 0, rows[rows.length - 1]?.t ?? 0];
  const deployLines = deployments
    .filter((d) => !d.deployed_before_window)
    .map((d) => ({ t: new Date(d.deployment_time).getTime(), version: d.version }))
    .filter((d) => d.t >= start && d.t <= end);

  return (
    <figure className="space-y-1" aria-describedby={summaryId}>
      <div className="flex items-center justify-between gap-2">
        <figcaption className="text-xs font-medium">{title}</figcaption>
        <Button variant="ghost" size="sm" className="h-6 text-[11px]" onClick={() => setShowTable((v) => !v)} aria-pressed={showTable}>
          {showTable ? "Chart" : "Data table"}
        </Button>
      </div>
      <p id={summaryId} className="sr-only">
        {title}. {hasData ? summarize(series, format) : "No data in this range."}
        {deployLines.length ? ` Deployments: ${deployLines.map((d) => `${d.version} at ${formatClock(new Date(d.t))}`).join(", ")}.` : ""}
      </p>
      {!hasData ? (
        <div className="flex items-center justify-center rounded-md border border-dashed text-xs text-muted-foreground" style={{ height }}>
          No data points in this range. Is the service receiving traffic?
        </div>
      ) : showTable ? (
        <div className="overflow-auto rounded-md border" style={{ maxHeight: height }}>
          <table className="w-full text-xs">
            <thead className="sticky top-0 bg-muted">
              <tr>
                <th scope="col" className="px-2 py-1 text-left font-medium">Time</th>
                {series.map((s) => (
                  <th key={s.key} scope="col" className="px-2 py-1 text-right font-medium">
                    {s.label}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody className="font-mono tabular">
              {rows.map((r) => (
                <tr key={r.t} className="border-t">
                  <td className="px-2 py-0.5">{formatClock(new Date(r.t))}</td>
                  {series.map((s) => (
                    <td key={s.key} className="px-2 py-0.5 text-right">
                      {r[s.key] != null ? format(r[s.key] as number) : MISSING}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <div style={{ height }} aria-hidden>
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={rows} margin={{ top: 4, right: 8, bottom: 0, left: 0 }} accessibilityLayer={false}>
              <CartesianGrid stroke="var(--border)" strokeDasharray="3 3" vertical={false} />
              <XAxis
                dataKey="t"
                type="number"
                scale="time"
                domain={["dataMin", "dataMax"]}
                tickFormatter={(t: number) => new Date(t).toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" })}
                tick={{ fill: "var(--muted-foreground)", fontSize: 11 }}
                stroke="var(--border)"
                minTickGap={40}
              />
              <YAxis
                width={56}
                tickFormatter={(v: number) => format(v)}
                tick={{ fill: "var(--muted-foreground)", fontSize: 11 }}
                stroke="var(--border)"
              />
              <Tooltip
                labelFormatter={(t) => formatClock(new Date(Number(t)))}
                formatter={(value, name) => [value == null ? MISSING : format(Number(value)), series.find((s) => s.key === name)?.label ?? name]}
                contentStyle={{ background: "var(--popover)", border: "1px solid var(--border)", borderRadius: 6, fontSize: 12, color: "var(--popover-foreground)" }}
              />
              {deployLines.map((d) => (
                <ReferenceLine
                  key={`${d.version}-${d.t}`}
                  x={d.t}
                  stroke="var(--kind-hypothesis)"
                  strokeDasharray="4 3"
                  label={{ value: `deploy ${d.version}`, position: "insideTopLeft", fill: "var(--foreground)", fontSize: 10 }}
                />
              ))}
              {series.map((s) => (
                <Line key={s.key} type="monotone" dataKey={s.key} stroke={s.color} strokeWidth={1.75} dot={false} connectNulls isAnimationActive={false} />
              ))}
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}
      {series.length > 1 ? (
        <ul className="flex flex-wrap gap-3 text-[11px] text-muted-foreground" aria-hidden>
          {series.map((s) => (
            <li key={s.key} className="flex items-center gap-1">
              <span className="inline-block h-0.5 w-3" style={{ background: s.color }} />
              {s.label}
            </li>
          ))}
        </ul>
      ) : null}
    </figure>
  );
}

// Polls return structurally shared data, so memo skips re-rendering unchanged charts.
export const MetricChart = memo(MetricChartInner);

export function Sparkline({ points, label, format }: { points: Point[]; label: string; format: (v: number) => string }) {
  const values = points.map((p) => p.value).filter((v): v is number => v != null);
  if (values.length < 2) return <span className="text-[11px] text-muted-foreground">No trend data</span>;
  const max = Math.max(...values);
  const min = Math.min(...values);
  const span = max - min || 1;
  const step = 100 / (points.length - 1);
  const path = points
    .map((p, i) => (p.value == null ? null : `${i * step},${28 - ((p.value - min) / span) * 26}`))
    .filter(Boolean)
    .join(" ");
  return (
    <svg viewBox="0 0 100 30" preserveAspectRatio="none" className="h-7 w-full" role="img" aria-label={`${label} trend, ${format(values[0]!)} to ${format(values[values.length - 1]!)}`}>
      <polyline points={path} fill="none" stroke="var(--chart-1)" strokeWidth="1.5" vectorEffect="non-scaling-stroke" />
    </svg>
  );
}
