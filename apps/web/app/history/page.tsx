"use client";

import { Loader2, RotateCcw } from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import { HistoryTable } from "@/components/domain/history-table";
import { ReplayView } from "@/components/domain/replay-result";
import { EmptyState, ErrorState, LoadingRows } from "@/components/domain/states";
import { PageHeader } from "@/components/layout/page-header";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useIncidents, useReplay, useReplays } from "@/hooks/use-api";
import { formatAge, humanize } from "@/lib/format";

function Incidents() {
  const incidents = useIncidents({ refetchInterval: false });
  if (incidents.isPending) return <LoadingRows rows={6} label="Loading incidents" />;
  if (incidents.isError) return <ErrorState error={incidents.error} onRetry={() => void incidents.refetch()} />;
  if (!incidents.data.length) return <EmptyState title="No incidents recorded" />;
  return (
    <div className="overflow-x-auto rounded-md border">
      <table className="w-full text-xs">
        <caption className="sr-only">Incidents</caption>
        <thead className="bg-muted/60 text-left">
          <tr>
            <th scope="col" className="px-2 py-1.5 font-medium">Opened</th>
            <th scope="col" className="px-2 py-1.5 font-medium">Title</th>
            <th scope="col" className="px-2 py-1.5 font-medium">Service</th>
            <th scope="col" className="px-2 py-1.5 font-medium">Severity</th>
            <th scope="col" className="px-2 py-1.5 font-medium">Status</th>
          </tr>
        </thead>
        <tbody>
          {incidents.data.map((i) => (
            <tr key={i.id} className="border-t hover:bg-accent/50">
              <td className="px-2 py-1.5 whitespace-nowrap">{formatAge(i.created_at)}</td>
              <td className="px-2 py-1.5">
                <Link href={`/history/incidents/${i.id}`} className="font-medium hover:underline">
                  {i.title}
                </Link>
              </td>
              <td className="px-2 py-1.5 font-mono">{i.service_name ?? "—"}</td>
              <td className="px-2 py-1.5">
                <Badge variant={i.severity === "SEV1" ? "down" : i.severity === "SEV2" ? "degraded" : "outline"}>{i.severity}</Badge>
              </td>
              <td className="px-2 py-1.5">{humanize(i.status)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Replays() {
  const cases = useReplays();
  const replay = useReplay();
  const [active, setActive] = useState<string | null>(null);
  if (cases.isPending) return <LoadingRows rows={6} label="Loading recorded incidents" />;
  if (cases.isError) return <ErrorState error={cases.error} onRetry={() => void cases.refetch()} />;
  return (
    <div className="space-y-4">
      <p className="text-xs text-muted-foreground">
        Recorded incident scenarios with a known root cause. Replaying one runs the real agent against the telemetry
        recorded for it and compares its diagnosis with the expected one.
      </p>
      <ul className="grid gap-2 md:grid-cols-2">
        {cases.data.map((c) => (
          <li key={c.id}>
            <Card className="flex h-full flex-col gap-1.5 p-3">
              <div className="flex items-start justify-between gap-2">
                <p className="font-mono text-xs font-medium">{c.id}</p>
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() => {
                    setActive(c.id);
                    replay.mutate(c.id);
                  }}
                  disabled={replay.isPending}
                >
                  {replay.isPending && active === c.id ? <Loader2 className="animate-spin" /> : <RotateCcw />} Replay incident
                </Button>
              </div>
              <p className="text-sm">{c.question}</p>
              <p className="text-xs text-muted-foreground">
                Expected: {c.expected_root_cause ? humanize(c.expected_root_cause) : "no root cause (agent must abstain)"}
                {c.expected_service ? ` on ${c.expected_service}` : ""}
                {c.unavailable_sources.length ? ` · unavailable: ${c.unavailable_sources.join(", ")}` : ""}
              </p>
            </Card>
          </li>
        ))}
      </ul>
      {replay.isError ? <ErrorState error={replay.error} onRetry={() => active && replay.mutate(active)} /> : null}
      {replay.data ? (
        <div id="replay-result">
          <ReplayView result={replay.data.data} />
        </div>
      ) : null}
    </div>
  );
}

export default function HistoryPage() {
  return (
    <>
      <PageHeader title="Incident History" description="Past investigations and incidents, and recorded incidents you can replay." />
      <Tabs defaultValue="investigations">
        <TabsList aria-label="History views">
          <TabsTrigger value="investigations">Investigations</TabsTrigger>
          <TabsTrigger value="incidents">Incidents</TabsTrigger>
          <TabsTrigger value="replays">Replayable incidents</TabsTrigger>
        </TabsList>
        <Card className="mt-2">
          <CardContent className="pt-3">
            <TabsContent value="investigations" className="mt-0">
              <HistoryTable />
            </TabsContent>
            <TabsContent value="incidents" className="mt-0">
              <Incidents />
            </TabsContent>
            <TabsContent value="replays" className="mt-0">
              <Replays />
            </TabsContent>
          </CardContent>
        </Card>
      </Tabs>
    </>
  );
}
