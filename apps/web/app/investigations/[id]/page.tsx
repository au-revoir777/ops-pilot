"use client";

import { Loader2 } from "lucide-react";
import { use, useEffect, useState } from "react";
import { InvestigationView } from "@/components/domain/investigation-view";
import { ErrorState, LoadingRows } from "@/components/domain/states";
import { StatusBadge } from "@/components/domain/status-badge";
import { UntrustedText } from "@/components/domain/untrusted-text";
import { PageHeader } from "@/components/layout/page-header";
import { Card, CardContent } from "@/components/ui/card";
import { INVESTIGATION_POLL_MS, useInvestigation } from "@/hooks/use-api";
import type { InvestigationDetail } from "@/lib/api/schemas";
import { formatClock, formatMs, shortId } from "@/lib/format";

function Elapsed({ since }: { since: string }) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const id = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(id);
  }, []);
  return <span className="font-mono tabular">{formatMs(now - new Date(since).getTime())}</span>;
}

function requestIdOf(investigation: InvestigationDetail): string | null {
  const created = investigation.events.find((e) => e.sequence === 1);
  const id = created?.details?.["request_id"];
  return typeof id === "string" ? id : null;
}

function InProgress({ investigation }: { investigation: InvestigationDetail }) {
  return (
    <Card>
      <CardContent className="space-y-3 pt-4" role="status" aria-live="polite">
        <div className="flex items-center gap-2">
          <Loader2 className="size-4 animate-spin text-muted-foreground" aria-hidden />
          <StatusBadge status={investigation.status} label={investigation.status} />
          <span className="text-sm">
            Elapsed <Elapsed since={investigation.started_at ?? investigation.created_at} />
          </span>
        </div>
        <p className="text-sm">
          <UntrustedText text={investigation.query ?? ""} />
        </p>
        <p className="text-xs text-muted-foreground">
          The agent reports its steps when it finishes, so the trace appears all at once. This page checks for the
          result every {Math.round(INVESTIGATION_POLL_MS / 1000)} s. Cancelling is not supported by the API.
        </p>
        <ol className="space-y-1 text-xs text-muted-foreground">
          {investigation.events.map((e) => (
            <li key={e.sequence}>
              <span className="font-mono">{formatClock(e.created_at)}</span> {e.message}
            </li>
          ))}
        </ol>
      </CardContent>
    </Card>
  );
}

export default function InvestigationPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const query = useInvestigation(id);
  const investigation = query.data;

  return (
    <>
      <PageHeader
        title={`Investigation ${shortId(id)}`}
        crumbs={[{ label: "Investigations", href: "/investigations" }, { label: shortId(id) }]}
      />
      {query.isPending ? (
        <LoadingRows rows={6} label="Loading investigation" />
      ) : query.isError ? (
        <ErrorState error={query.error} onRetry={() => void query.refetch()} />
      ) : investigation?.status === "pending" || investigation?.status === "running" ? (
        <InProgress investigation={investigation} />
      ) : investigation?.status === "failed" ? (
        <ErrorState
          error={{
            name: "InvestigationFailed",
            message: investigation.summary ?? "The investigation failed.",
          }}
        />
      ) : investigation?.report ? (
        <InvestigationView
          report={investigation.report}
          meta={{ id: investigation.id, requestId: requestIdOf(investigation), latencyMs: investigation.latency_ms, createdAt: investigation.created_at }}
        />
      ) : (
        <ErrorState error={new Error("This investigation has no report.")} />
      )}
    </>
  );
}
