"use client";

import { Rocket, Search } from "lucide-react";
import Link from "next/link";
import { use } from "react";
import { RecentInvestigations } from "@/components/domain/investigation-table";
import { EmptyState, ErrorState, LoadingRows } from "@/components/domain/states";
import { UntrustedText } from "@/components/domain/untrusted-text";
import { PageHeader } from "@/components/layout/page-header";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { useDeployments, useIncident, useIncidentInvestigations } from "@/hooks/use-api";
import type { Incident } from "@/lib/api/schemas";
import { formatTimestamp, humanize, shortId } from "@/lib/format";
import { investigateHref } from "@/lib/links";

function Timeline({ incident }: { incident: Incident }) {
  const investigations = useIncidentInvestigations(incident.id);
  const deployments = useDeployments(incident.service_name, 24, { refetchInterval: false });
  type Entry = { at: string; text: string; kind: string };
  const entries: Entry[] = [
    { at: incident.created_at, text: "Incident opened", kind: "incident" },
    ...(incident.resolved_at ? [{ at: incident.resolved_at, text: "Incident resolved", kind: "incident" }] : []),
    ...(investigations.data ?? []).map((i) => ({
      at: i.created_at,
      text: `Investigation ${shortId(i.id)} ${i.status}${i.root_cause ? `: ${humanize(i.root_cause)}` : ""}`,
      kind: "investigation",
    })),
    ...(deployments.data?.deployments ?? [])
      .filter((d) => !d.deployed_before_window)
      .map((d) => ({ at: d.deployment_time, text: `Deployed ${incident.service_name} v${d.version}`, kind: "deployment" })),
  ].sort((a, b) => new Date(a.at).getTime() - new Date(b.at).getTime());

  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <Card>
        <CardHeader>
          <CardTitle>Timeline</CardTitle>
        </CardHeader>
        <CardContent>
          {investigations.isPending ? (
            <LoadingRows rows={4} />
          ) : (
            <ol className="space-y-2 border-l pl-4">
              {entries.map((e, i) => (
                <li key={`${e.at}-${i}`} className="relative">
                  <span aria-hidden className="absolute top-1.5 -left-[1.3rem] size-2 rounded-full bg-muted-foreground" />
                  <p className="text-sm">
                    {e.kind === "deployment" ? <Rocket className="mr-1 inline size-3.5" aria-hidden /> : null}
                    {e.text}
                  </p>
                  <p className="font-mono text-[11px] text-muted-foreground">{formatTimestamp(e.at)}</p>
                </li>
              ))}
            </ol>
          )}
          {deployments.isError || deployments.data?.status === "unavailable" ? (
            <p className="mt-2 text-xs text-muted-foreground">Deployment history is unavailable (metrics_unavailable).</p>
          ) : null}
        </CardContent>
      </Card>
      <Card>
        <CardHeader>
          <CardTitle>Investigations</CardTitle>
        </CardHeader>
        <CardContent>
          {investigations.isPending ? (
            <LoadingRows rows={3} />
          ) : investigations.isError ? (
            <ErrorState error={investigations.error} compact />
          ) : investigations.data.length === 0 ? (
            <EmptyState title="Not investigated yet" />
          ) : (
            <RecentInvestigations items={investigations.data} />
          )}
        </CardContent>
      </Card>
    </div>
  );
}

export default function IncidentPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const incident = useIncident(id);
  return (
    <>
      <PageHeader
        title={incident.data?.title ?? `Incident ${shortId(id)}`}
        crumbs={[{ label: "Incident History", href: "/history" }, { label: shortId(id) }]}
        actions={
          incident.data ? (
            <Button asChild size="sm">
              <Link href={investigateHref(incident.data)}>
                <Search /> Investigate
              </Link>
            </Button>
          ) : null
        }
      />
      {incident.isPending ? (
        <LoadingRows rows={5} label="Loading incident" />
      ) : incident.isError ? (
        <ErrorState error={incident.error} onRetry={() => void incident.refetch()} />
      ) : (
        <div className="space-y-4">
          <Card>
            <CardContent className="space-y-2 pt-3">
              <div className="flex flex-wrap items-center gap-2">
                <Badge variant={incident.data.severity === "SEV1" ? "down" : incident.data.severity === "SEV2" ? "degraded" : "outline"}>{incident.data.severity}</Badge>
                <Badge variant="outline">{humanize(incident.data.status)}</Badge>
                <span className="font-mono text-xs text-muted-foreground">{incident.data.service_name ?? "no service"}</span>
              </div>
              {incident.data.description ? (
                <p className="text-sm">
                  <UntrustedText text={incident.data.description} />
                </p>
              ) : null}
              <p className="text-xs text-muted-foreground">
                Failure modes and expected root causes are only known for recorded scenarios; see Replayable incidents in
                the history.
              </p>
            </CardContent>
          </Card>
          <Timeline incident={incident.data} />
        </div>
      )}
    </>
  );
}
