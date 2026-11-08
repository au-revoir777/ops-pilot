"use client";

import { useQuery } from "@tanstack/react-query";
import { ExternalLink } from "lucide-react";
import dynamic from "next/dynamic";
import { useMemo } from "react";
import type { MapComponent, MapLink } from "@/components/domain/service-map";
import { ErrorState, LoadingRows } from "@/components/domain/states";
import { StatusBadge } from "@/components/domain/status-badge";
import { PageHeader } from "@/components/layout/page-header";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { DASHBOARD_REFRESH_MS, useConfig, useInvestigations, useServices } from "@/hooks/use-api";
import { api } from "@/lib/api/client";
import { formatClock, formatMs, formatPercent } from "@/lib/format";

const ServiceMap = dynamic(() => import("@/components/domain/service-map").then((m) => m.ServiceMap), {
  ssr: false,
  loading: () => <Skeleton className="h-[30rem] w-full" />,
});

/** The dependency health check, timed in the browser (round trip through the web proxy). */
function useTimedHealth() {
  return useQuery({
    queryKey: ["health", "timed"],
    queryFn: async ({ signal }) => {
      const started = performance.now();
      const data = await api.health(signal);
      return { data, latencyMs: performance.now() - started, checkedAt: new Date() };
    },
    refetchInterval: DASHBOARD_REFRESH_MS,
  });
}

function percentile(values: number[], p: number): number | null {
  if (!values.length) return null;
  const sorted = [...values].sort((a, b) => a - b);
  return sorted[Math.min(sorted.length - 1, Math.floor((p / 100) * sorted.length))] ?? null;
}

type Row = { id: string; label: string; status: string; version: string; detail: string };

export default function SystemPage() {
  const config = useConfig();
  const health = useTimedHealth();
  const services = useServices();
  const recent = useInvestigations({ limit: 100 }, { refetchInterval: 60_000 });

  const checks = health.data?.data.checks ?? {};
  const apiStatus = health.isError ? "down" : health.data ? "healthy" : "unknown";
  const mcpStatus = health.data ? (checks["mcp"] === "ok" ? "healthy" : "down") : "unknown";
  const promStatus = mcpStatus !== "healthy" ? "unknown" : services.data?.telemetry_status === "ok" ? "healthy" : services.data ? "down" : "unknown";
  const workloads = (services.data?.services ?? []).filter((s) => s.sources.includes("telemetry"));

  const rows: Row[] = [
    { id: "web", label: "Web UI", status: "healthy", version: config.data?.version ?? "—", detail: "Serving this page" },
    { id: "api", label: "OpsPilot API", status: apiStatus, version: config.data?.version ?? "—", detail: health.isError ? "Unreachable" : "Answering /api/health" },
    { id: "agent", label: "Agent", status: apiStatus, version: config.data?.version ?? "—", detail: "Runs inside the API process" },
    { id: "db", label: "PostgreSQL", status: health.data ? (checks["database"] === "ok" ? "healthy" : "down") : "unknown", version: "16 + pgvector", detail: `database: ${checks["database"] ?? "unknown"}` },
    { id: "rag", label: "Knowledge base (RAG)", status: health.data ? (checks["knowledge_base"] === "ok" ? "healthy" : checks["knowledge_base"] === "empty" ? "degraded" : "down") : "unknown", version: "bge-small-en-v1.5", detail: `knowledge_base: ${checks["knowledge_base"] ?? "unknown"}` },
    { id: "mcp", label: "MCP server", status: mcpStatus, version: "—", detail: `mcp: ${checks["mcp"] ?? "unknown"}` },
    { id: "prometheus", label: "Prometheus", status: promStatus, version: "—", detail: promStatus === "unknown" ? "Checked through MCP" : `telemetry: ${services.data?.telemetry_status}` },
    { id: "loki", label: "Loki", status: "unknown", version: "—", detail: "Not probed by the API; failures show in investigations" },
    { id: "grafana", label: "Grafana", status: "unknown", version: "—", detail: config.data?.grafana_url ? "Not probed; open it to check" : "No public URL configured" },
    { id: "llm", label: "LLM provider", status: checks["llm"] === "configured" ? "healthy" : "unknown", version: config.data?.llm_model ?? "—", detail: checks["llm"] === "disabled" ? "Disabled (rule-based only)" : `llm: ${checks["llm"] ?? "unknown"}` },
    ...workloads.map((w) => ({
      id: `svc-${w.name}`,
      label: w.name,
      status: w.health ?? "unknown",
      version: w.version ?? "—",
      detail: `p95 ${formatMs(w.p95_latency_ms)} · errors ${formatPercent(w.error_rate)}`,
    })),
  ];

  const { components, links } = useMemo(() => {
    const at = (id: string, x: number, y: number): MapComponent => {
      const row = rows.find((r) => r.id === id)!;
      return { id, label: row.label, status: row.status, detail: row.detail, x, y };
    };
    const components: MapComponent[] = [
      { id: "browser", label: "Browser", status: "healthy", detail: "You are here", x: 0, y: 160 },
      at("web", 220, 160),
      at("api", 440, 160),
      at("agent", 660, 60),
      at("db", 660, 260),
      at("rag", 880, 300),
      at("llm", 880, 0),
      at("mcp", 880, 140),
      at("prometheus", 1100, 80),
      at("loki", 1100, 200),
      at("grafana", 1100, 330),
      ...workloads.map((w, i) => at(`svc-${w.name}`, 1320, i * 90 + 40)),
    ];
    const links: MapLink[] = [
      { from: "browser", to: "web" },
      { from: "web", to: "api", label: "/api proxy" },
      { from: "api", to: "agent" },
      { from: "api", to: "db" },
      { from: "agent", to: "mcp", label: "read-only tools" },
      { from: "agent", to: "rag" },
      { from: "db", to: "rag" },
      ...(config.data?.llm_provider && config.data.llm_provider !== "none" ? [{ from: "agent", to: "llm" }] : []),
      { from: "mcp", to: "prometheus" },
      { from: "mcp", to: "loki" },
      { from: "grafana", to: "prometheus" },
      ...workloads.map((w) => ({ from: "prometheus", to: `svc-${w.name}`, label: "scrapes" })),
    ];
    return { components, links };
    // rows is derived from the queries below; recompute when they change
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [health.data, health.isError, services.data, config.data]);

  const items = recent.data?.items ?? [];
  const latencies = items.map((i) => i.latency_ms).filter((v): v is number => v != null);
  const failed = items.filter((i) => i.status === "failed").length;

  return (
    <>
      <PageHeader
        title="System Status"
        description="OpsPilot's own components, how they connect, and their health."
        actions={
          config.data?.grafana_url ? (
            <Button asChild variant="outline" size="sm">
              <a href={config.data.grafana_url} target="_blank" rel="noreferrer noopener">
                Grafana <ExternalLink />
              </a>
            </Button>
          ) : null
        }
      />
      <div className="space-y-4">
        {health.isError ? <ErrorState error={health.error} onRetry={() => void health.refetch()} /> : null}
        <Card>
          <CardHeader>
            <div>
              <CardTitle>Service map</CardTitle>
              <CardDescription>Node badges come from live checks. Unknown means nothing checks that component directly.</CardDescription>
            </div>
          </CardHeader>
          <CardContent>
            <ServiceMap components={components} links={links} />
          </CardContent>
        </Card>
        <div className="grid gap-4 xl:grid-cols-[minmax(0,1.6fr)_minmax(0,1fr)]">
          <Card>
            <CardHeader>
              <div>
                <CardTitle>Components</CardTitle>
                <CardDescription>
                  Last check {health.data ? formatClock(health.data.checkedAt) : "—"}, round trip {health.data ? formatMs(health.data.latencyMs) : "—"} (browser to API to dependencies).
                </CardDescription>
              </div>
            </CardHeader>
            <CardContent>
              {health.isPending ? (
                <LoadingRows rows={8} />
              ) : (
                <div className="overflow-x-auto">
                  <table className="w-full text-xs">
                    <caption className="sr-only">Component status</caption>
                    <thead className="text-left text-muted-foreground">
                      <tr>
                        <th scope="col" className="py-1 pr-2 font-medium">Component</th>
                        <th scope="col" className="py-1 pr-2 font-medium">Status</th>
                        <th scope="col" className="py-1 pr-2 font-medium">Version</th>
                        <th scope="col" className="py-1 font-medium">Detail</th>
                      </tr>
                    </thead>
                    <tbody>
                      {rows.map((r) => (
                        <tr key={r.id} className="border-t">
                          <td className="py-1.5 pr-2 font-medium">{r.label}</td>
                          <td className="py-1.5 pr-2">
                            <StatusBadge status={r.status} />
                          </td>
                          <td className="py-1.5 pr-2 font-mono">{r.version}</td>
                          <td className="py-1.5 text-muted-foreground">{r.detail}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </CardContent>
          </Card>
          <div className="space-y-4">
            <Card>
              <CardHeader>
                <div>
                  <CardTitle>Self-observability</CardTitle>
                  <CardDescription>From the last {items.length} stored investigations.</CardDescription>
                </div>
              </CardHeader>
              <CardContent>
                {recent.isPending ? (
                  <LoadingRows rows={3} />
                ) : recent.isError ? (
                  <ErrorState error={recent.error} compact />
                ) : (
                  <dl className="grid grid-cols-2 gap-3 text-xs">
                    <div>
                      <dt className="text-muted-foreground">Investigation latency p50</dt>
                      <dd className="font-mono text-base">{formatMs(percentile(latencies, 50))}</dd>
                    </div>
                    <div>
                      <dt className="text-muted-foreground">Investigation latency p95</dt>
                      <dd className="font-mono text-base">{formatMs(percentile(latencies, 95))}</dd>
                    </div>
                    <div>
                      <dt className="text-muted-foreground">Failed investigations</dt>
                      <dd className="font-mono text-base">
                        {failed} / {items.length}
                      </dd>
                    </div>
                    <div>
                      <dt className="text-muted-foreground">RAG latency, MCP calls, LLM errors</dt>
                      <dd>Exported as Prometheus metrics by the API and MCP server; see Grafana.</dd>
                    </div>
                  </dl>
                )}
              </CardContent>
            </Card>
            <Card>
              <CardHeader>
                <div>
                  <CardTitle>Active configuration</CardTitle>
                  <CardDescription>Only values that are safe to show. Secrets and connection strings never leave the API.</CardDescription>
                </div>
              </CardHeader>
              <CardContent>
                {config.isPending ? (
                  <LoadingRows rows={4} />
                ) : config.isError ? (
                  <ErrorState error={config.error} compact />
                ) : (
                  <dl className="grid grid-cols-[10rem_1fr] gap-y-1.5 text-xs">
                    <dt className="text-muted-foreground">Environment</dt>
                    <dd className="font-mono">{config.data.environment}</dd>
                    <dt className="text-muted-foreground">Version</dt>
                    <dd className="font-mono">{config.data.version}</dd>
                    <dt className="text-muted-foreground">Mode</dt>
                    <dd>{config.data.read_only ? "Read-only (no remediation endpoints)" : "Actions enabled"}</dd>
                    <dt className="text-muted-foreground">Model provider</dt>
                    <dd className="font-mono">{config.data.llm_provider}</dd>
                    <dt className="text-muted-foreground">Model</dt>
                    <dd className="font-mono">{config.data.llm_model ?? "none (rule-based)"}</dd>
                    <dt className="text-muted-foreground">Incident lab</dt>
                    <dd>{config.data.incident_lab_enabled ? "Enabled (demo services only)" : "Disabled"}</dd>
                  </dl>
                )}
              </CardContent>
            </Card>
          </div>
        </div>
      </div>
    </>
  );
}
