"use client";

import { ExternalLink, Pause, Play, Search } from "lucide-react";
import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { ConfidenceBadge } from "@/components/domain/confidence";
import { MetricChart } from "@/components/domain/metric-chart";
import { ServiceCard, ServiceCardSkeleton } from "@/components/domain/service-card";
import { DegradedBanner, EmptyState, ErrorState, LoadingRows } from "@/components/domain/states";
import { StatusBadge } from "@/components/domain/status-badge";
import { PageHeader } from "@/components/layout/page-header";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Label, NativeSelect } from "@/components/ui/input";
import {
  DASHBOARD_REFRESH_MS,
  useConfig,
  useDependencyHealth,
  useDeployments,
  useIncidents,
  useInvestigations,
  useMetrics,
  useServices,
} from "@/hooks/use-api";
import type { MetricRange, ServiceInfo } from "@/lib/api/schemas";
import { formatAge, formatClock, formatMs, formatPercent, formatRate } from "@/lib/format";
import { investigateHref } from "@/lib/links";

const RANGES: MetricRange[] = ["15m", "1h", "6h"];
const ACTIVE = new Set(["open", "investigating", "mitigated"]);

function ServiceCardContainer({ service, interval }: { service: ServiceInfo; interval: number | false }) {
  const metrics = useMetrics(service.name, "30m", { refetchInterval: interval });
  const deployments = useDeployments(service.name, 6, { refetchInterval: interval });
  const latest = deployments.data?.deployments.find((d) => d.status === "active") ?? deployments.data?.deployments.at(-1);
  return (
    <ServiceCard
      service={service}
      p95Trend={metrics.data?.series["p95_latency_s"] ?? (metrics.isError ? [] : undefined)}
      latestDeployment={deployments.data ? (latest ?? null) : undefined}
      deploymentsUnavailable={deployments.isError || deployments.data?.status === "unavailable"}
    />
  );
}

function TimeSeriesPanel({ services, interval, loading }: { services: string[]; interval: number | false; loading: boolean }) {
  const [service, setService] = useState<string | null>(null);
  const [range, setRange] = useState<MetricRange>("1h");
  const selected = service ?? services[0] ?? null;
  const metrics = useMetrics(selected, range, { refetchInterval: interval });
  const deployments = useDeployments(selected, range === "6h" ? 7 : 2, { refetchInterval: interval });
  const series = metrics.data?.series ?? {};
  const deploys = deployments.data?.deployments ?? [];

  return (
    <Card>
      <CardHeader className="flex-wrap">
        <div>
          <CardTitle>Service metrics</CardTitle>
          <CardDescription>Recording rules in Prometheus, read through the MCP server. Dashed lines mark deployments.</CardDescription>
        </div>
        <div className="flex items-end gap-2">
          <div className="space-y-0.5">
            <Label htmlFor="ts-service">Service</Label>
            <NativeSelect id="ts-service" value={selected ?? ""} onChange={(e) => setService(e.target.value)} className="w-36" disabled={!services.length}>
              {services.map((s) => (
                <option key={s} value={s}>
                  {s}
                </option>
              ))}
            </NativeSelect>
          </div>
          <div role="group" aria-label="Time range" className="flex rounded-md border p-0.5">
            {RANGES.map((r) => (
              <Button key={r} size="sm" variant={range === r ? "secondary" : "ghost"} className="h-6" aria-pressed={range === r} onClick={() => setRange(r)}>
                {r}
              </Button>
            ))}
          </div>
        </div>
      </CardHeader>
      <CardContent className="space-y-3">
        {loading ? (
          <LoadingRows rows={4} label="Loading services" />
        ) : !selected ? (
          <EmptyState title="No services found">OpsPilot has not seen any service in Prometheus yet. Check the scrape targets.</EmptyState>
        ) : metrics.isPending ? (
          <LoadingRows rows={4} label="Loading metrics" />
        ) : metrics.isError ? (
          <ErrorState error={metrics.error} onRetry={() => void metrics.refetch()} />
        ) : (
          <>
            {metrics.data.status !== "ok" ? (
              <DegradedBanner sources={["metrics_unavailable"]}>{metrics.data.errors.join("; ")}</DegradedBanner>
            ) : null}
            <div className="grid gap-4 lg:grid-cols-3">
              <MetricChart
                title="Request rate"
                series={[{ key: "rps", label: "req/s", points: series["request_rate"] ?? [], color: "var(--chart-1)" }]}
                format={(v) => formatRate(v)}
                deployments={deploys}
              />
              <MetricChart
                title="Error rate (5xx)"
                series={[{ key: "err", label: "errors", points: series["error_rate"] ?? [], color: "var(--chart-5)" }]}
                format={(v) => formatPercent(v)}
                deployments={deploys}
              />
              <MetricChart
                title="Latency"
                series={[
                  { key: "p50", label: "p50", points: series["p50_latency_s"] ?? [], color: "var(--chart-3)" },
                  { key: "p95", label: "p95", points: series["p95_latency_s"] ?? [], color: "var(--chart-1)" },
                  { key: "p99", label: "p99", points: series["p99_latency_s"] ?? [], color: "var(--chart-4)" },
                ]}
                format={(v) => formatMs(v * 1000)}
                deployments={deploys}
              />
            </div>
          </>
        )}
      </CardContent>
    </Card>
  );
}

function ActiveIncidents({ interval }: { interval: number | false }) {
  const incidents = useIncidents({ refetchInterval: interval });
  const active = (incidents.data ?? []).filter((i) => ACTIVE.has(i.status));
  return (
    <Card>
      <CardHeader>
        <div>
          <CardTitle>Active incidents</CardTitle>
          <CardDescription>Open, investigating or mitigated.</CardDescription>
        </div>
        <Button asChild variant="ghost" size="sm">
          <Link href="/history">All history</Link>
        </Button>
      </CardHeader>
      <CardContent>
        {incidents.isPending ? (
          <LoadingRows rows={3} label="Loading incidents" />
        ) : incidents.isError ? (
          <ErrorState error={incidents.error} onRetry={() => void incidents.refetch()} compact />
        ) : active.length === 0 ? (
          <EmptyState title="No active incidents">Incidents appear here when one is opened, or when you start an investigation from a question.</EmptyState>
        ) : (
          <ul className="divide-y">
            {active.slice(0, 8).map((i) => (
              <li key={i.id} className="flex flex-wrap items-center gap-2 py-2">
                <Badge variant={i.severity === "SEV1" ? "down" : i.severity === "SEV2" ? "degraded" : "outline"}>{i.severity}</Badge>
                <div className="min-w-0 flex-1">
                  <Link href={`/history/incidents/${i.id}`} className="block truncate text-sm font-medium hover:underline">
                    {i.title}
                  </Link>
                  <p className="text-xs text-muted-foreground">
                    {i.service_name ?? "no service"} · {i.status} · opened {formatAge(i.created_at)}
                  </p>
                </div>
                <Button asChild size="sm" variant="outline">
                  <Link href={investigateHref(i)}>
                    <Search /> Investigate
                  </Link>
                </Button>
              </li>
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}

function LastInvestigation({ interval }: { interval: number | false }) {
  const list = useInvestigations({ limit: 1 }, { refetchInterval: interval });
  const last = list.data?.items[0];
  return (
    <Card>
      <CardHeader>
        <div>
          <CardTitle>Last investigation</CardTitle>
          <CardDescription>The most recent agent run.</CardDescription>
        </div>
      </CardHeader>
      <CardContent>
        {list.isPending ? (
          <LoadingRows rows={2} label="Loading last investigation" />
        ) : list.isError ? (
          <ErrorState error={list.error} onRetry={() => void list.refetch()} compact />
        ) : !last ? (
          <EmptyState
            title="No investigations yet"
            action={
              <Button asChild size="sm">
                <Link href="/investigations?new=1">Start one</Link>
              </Button>
            }
          />
        ) : (
          <Link href={`/investigations/${last.id}`} className="block space-y-1.5 rounded-md p-1 hover:bg-accent/50">
            <div className="flex flex-wrap items-center gap-2">
              <StatusBadge status={last.status} label={last.status} />
              {last.status === "completed" ? <ConfidenceBadge value={last.confidence} /> : null}
              <span className="ml-auto text-xs text-muted-foreground">{formatAge(last.created_at)}</span>
            </div>
            <p className="text-sm">{last.query ?? "Investigation from an incident"}</p>
            <p className="text-sm font-medium">{last.diagnosis ?? last.summary ?? "No diagnosis yet."}</p>
            <p className="font-mono text-xs text-muted-foreground">
              {last.service ?? "unknown service"} · {formatMs(last.latency_ms)}
            </p>
          </Link>
        )}
      </CardContent>
    </Card>
  );
}

export default function DashboardPage() {
  const [paused, setPaused] = useState(false);
  const interval = paused ? false : DASHBOARD_REFRESH_MS;
  const config = useConfig();
  const services = useServices({ refetchInterval: interval });
  const health = useDependencyHealth({ refetchInterval: interval });
  const [, tick] = useState(0);

  useEffect(() => {
    const id = window.setInterval(() => tick((n) => n + 1), 5000);
    return () => window.clearInterval(id);
  }, []);

  const monitored = useMemo(
    () => (services.data?.services ?? []).filter((s) => s.sources.includes("telemetry")),
    [services.data],
  );
  const degraded = [
    ...(services.data?.telemetry_status === "unavailable" ? ["metrics_unavailable"] : []),
    ...Object.entries(health.data?.checks ?? {})
      .filter(([name, v]) => v !== "ok" && !(name === "llm" && v === "disabled"))
      .map(([name, v]) => `${name}: ${v}`),
  ];
  const updatedAt = services.dataUpdatedAt ? new Date(services.dataUpdatedAt) : null;

  return (
    <>
      <PageHeader
        title="Dashboard"
        description="The current state of every service OpsPilot monitors."
        actions={
          <>
            <span className="text-xs text-muted-foreground" aria-live="polite">
              {paused ? "Auto-refresh paused" : "Refreshes every 15 s"}
              {updatedAt ? ` · updated ${formatClock(updatedAt)}` : ""}
            </span>
            <Button variant="outline" size="sm" onClick={() => setPaused((p) => !p)} aria-pressed={paused}>
              {paused ? <Play /> : <Pause />} {paused ? "Resume" : "Pause"}
            </Button>
            {config.data?.grafana_url ? (
              <Button asChild variant="outline" size="sm">
                <a href={config.data.grafana_url} target="_blank" rel="noreferrer noopener">
                  Grafana <ExternalLink />
                </a>
              </Button>
            ) : null}
          </>
        }
      />
      <div className="space-y-4">
        <DegradedBanner sources={degraded}>Panels that do not depend on these sources keep working.</DegradedBanner>
        <section aria-label="Services">
          {services.isPending ? (
            <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
              <ServiceCardSkeleton />
              <ServiceCardSkeleton />
              <ServiceCardSkeleton />
            </div>
          ) : services.isError ? (
            <ErrorState error={services.error} onRetry={() => void services.refetch()} />
          ) : monitored.length === 0 ? (
            <EmptyState title="No services are reporting telemetry">
              OpsPilot discovers services from Prometheus (<code>app_info</code>). Add your project&apos;s scrape target,
              or start the demo services, and they will appear here.
            </EmptyState>
          ) : (
            <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
              {monitored.map((s) => (
                <ServiceCardContainer key={s.name} service={s} interval={interval} />
              ))}
            </div>
          )}
        </section>
        <TimeSeriesPanel services={monitored.map((s) => s.name)} interval={interval} loading={services.isPending} />
        <div className="grid gap-4 lg:grid-cols-2">
          <ActiveIncidents interval={interval} />
          <LastInvestigation interval={interval} />
        </div>
      </div>
    </>
  );
}
