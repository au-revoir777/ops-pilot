"use client";

import { Rocket } from "lucide-react";
import { Card } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import type { Deployment, Point, ServiceInfo } from "@/lib/api/schemas";
import { formatAge, formatMs, formatPercent, formatRate, MISSING } from "@/lib/format";
import { Sparkline } from "./metric-chart";
import { StatusBadge, StatusDot } from "./status-badge";

export function ServiceCard({
  service,
  p95Trend,
  latestDeployment,
  deploymentsUnavailable = false,
}: {
  service: ServiceInfo;
  p95Trend?: Point[];
  latestDeployment?: Deployment | null;
  deploymentsUnavailable?: boolean;
}) {
  const reasons = service.reasons ?? [];
  return (
    <Card className="flex flex-col gap-2 p-3" aria-label={`${service.name} service`}>
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <h3 className="truncate text-sm font-semibold">{service.name}</h3>
          <p className="font-mono text-[11px] text-muted-foreground">
            {service.version ? `v${service.version}` : "version unknown"}
            {service.project ? ` · ${service.project}` : ""}
          </p>
        </div>
        <StatusBadge status={service.health ?? "unknown"} />
      </div>
      {reasons.length ? <p className="text-xs text-muted-foreground">{reasons.join("; ")}</p> : null}
      <dl className="grid grid-cols-3 gap-2 text-xs">
        <div>
          <dt className="text-muted-foreground">p95</dt>
          <dd className="font-mono font-medium tabular">{formatMs(service.p95_latency_ms)}</dd>
        </div>
        <div>
          <dt className="text-muted-foreground">Errors</dt>
          <dd className="font-mono font-medium tabular">{formatPercent(service.error_rate)}</dd>
        </div>
        <div>
          <dt className="text-muted-foreground">Traffic</dt>
          <dd className="font-mono font-medium tabular">{formatRate(service.request_rate)}</dd>
        </div>
      </dl>
      <div>
        <p className="text-[11px] text-muted-foreground">p95 latency, last 30 min</p>
        {p95Trend ? <Sparkline points={p95Trend} label={`${service.name} p95 latency`} format={(v) => formatMs(v * 1000)} /> : <Skeleton className="h-7 w-full" />}
      </div>
      <div className="flex flex-wrap items-center justify-between gap-2 border-t pt-2 text-[11px] text-muted-foreground">
        <span className="flex items-center gap-1">
          <Rocket className="size-3" aria-hidden />
          {deploymentsUnavailable
            ? "Deployments unavailable"
            : latestDeployment
              ? latestDeployment.deployed_before_window
                ? `v${latestDeployment.version}, deployed over 6h ago`
                : `v${latestDeployment.version} deployed ${formatAge(latestDeployment.deployment_time)}`
              : latestDeployment === null
                ? "No deployment in 6h"
                : MISSING}
        </span>
        {service.dependency_status.length ? (
          <span className="flex items-center gap-2" aria-label="Dependencies">
            {service.dependency_status.map((d) => (
              <span key={d.service} className="flex items-center gap-1" title={`${d.service}: ${d.status}`}>
                <StatusDot status={d.status} />
                {d.service}
                <span className="sr-only">{d.status}</span>
              </span>
            ))}
          </span>
        ) : null}
      </div>
    </Card>
  );
}

export function ServiceCardSkeleton() {
  return (
    <Card className="space-y-3 p-3">
      <div className="flex justify-between">
        <Skeleton className="h-4 w-24" />
        <Skeleton className="h-4 w-16" />
      </div>
      <Skeleton className="h-8 w-full" />
      <Skeleton className="h-7 w-full" />
      <Skeleton className="h-3 w-40" />
    </Card>
  );
}
