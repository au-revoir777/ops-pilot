import { CircleCheck, CircleX } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import type { ReplayResult } from "@/lib/api/schemas";
import { humanize } from "@/lib/format";
import { cn } from "@/lib/utils";
import { InvestigationView } from "./investigation-view";

export function ReplayComparison({ result }: { result: ReplayResult }) {
  const expected = result.case.expected_root_cause;
  const Mark = result.match ? CircleCheck : CircleX;
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Mark aria-hidden className={cn("size-4", result.match ? "text-status-healthy" : "text-status-down-text")} />
          {result.match ? "Match" : "Mismatch"}: agent diagnosis versus recorded root cause
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="grid gap-3 sm:grid-cols-2">
          <div className="rounded-md border p-3">
            <p className="text-xs text-muted-foreground">Agent diagnosis</p>
            <p className="text-sm font-medium" data-testid="replay-agent">
              {result.report.root_cause ? humanize(result.report.root_cause) : "No root cause claimed"}
            </p>
            <p className="font-mono text-xs text-muted-foreground">service: {result.report.service ?? "unknown"}</p>
          </div>
          <div className="rounded-md border p-3">
            <p className="text-xs text-muted-foreground">Recorded expected root cause</p>
            <p className="text-sm font-medium" data-testid="replay-expected">
              {expected ? humanize(expected) : "None: the agent must not claim a root cause"}
            </p>
            <p className="font-mono text-xs text-muted-foreground">
              service: {result.case.expected_service ?? "unknown"} {result.service_match ? "(matches)" : "(differs)"}
            </p>
          </div>
        </div>
        <p className="text-xs text-muted-foreground">
          Replay runs the real agent against telemetry recorded for this scenario, so it only sees information that was
          available during the simulated incident. Nothing is stored and no live system is touched.
          {result.case.unavailable_sources.length ? ` Unavailable in this scenario: ${result.case.unavailable_sources.join(", ")}.` : ""}
        </p>
      </CardContent>
    </Card>
  );
}

export function ReplayView({ result }: { result: ReplayResult }) {
  return (
    <div className="space-y-4">
      <ReplayComparison result={result} />
      <InvestigationView report={result.report} meta={{ replay: true }} />
    </div>
  );
}
