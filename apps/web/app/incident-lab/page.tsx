"use client";

import { Activity, FlaskConical, HeartPulse, Loader2, Search, Send } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";
import { toast } from "sonner";
import { MetricChart } from "@/components/domain/metric-chart";
import { EmptyState, ErrorState, LoadingRows } from "@/components/domain/states";
import { StatusBadge } from "@/components/domain/status-badge";
import { PageHeader } from "@/components/layout/page-header";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogTitle } from "@/components/ui/dialog";
import { Input, Label } from "@/components/ui/input";
import { useLab, useMetrics, useSendTraffic, useServices, useSetFailure } from "@/hooks/use-api";
import { describeError } from "@/lib/api/errors";
import type { FailureMode } from "@/lib/api/schemas";
import { formatClock, formatMs, formatPercent } from "@/lib/format";
import { newInvestigationHref } from "@/lib/links";

type Scenario = {
  id: string;
  title: string;
  service: string;
  mode: Exclude<FailureMode, "none">;
  does: string;
  expect: string;
  question: string;
};

// Scenarios map onto the demo workloads' own failure modes (apps/workloads).
const SCENARIOS: Scenario[] = [
  {
    id: "checkout-latency",
    title: "Inject checkout latency",
    service: "checkout",
    mode: "latency",
    does: "Adds a fixed delay (2 s by default) to every checkout request.",
    expect: "checkout p95 and p99 latency rise; error rate stays flat; no database change.",
    question: "Why is checkout latency high?",
  },
  {
    id: "checkout-errors",
    title: "Inject checkout errors",
    service: "checkout",
    mode: "errors",
    does: "Makes about half of checkout requests fail with HTTP 500 (default rate).",
    expect: "checkout 5xx error rate rises; error logs appear in Loki.",
    question: "Why is checkout returning errors?",
  },
  {
    id: "db-slowness",
    title: "Simulate DB slowness",
    service: "checkout",
    mode: "db",
    does: "Slows every checkout database query (about +900 ms by default), as a bad query plan would.",
    expect: "checkout DB query latency and request latency rise together; slow_query_detected warnings in logs.",
    question: "Checkout is slow, why?",
  },
  {
    id: "payments-errors",
    title: "Inject payments errors",
    service: "payments",
    mode: "errors",
    does: "Makes a share of payments requests fail with HTTP 500.",
    expect: "payments error rate rises; checkout sees dependency errors (502) because it calls payments.",
    question: "Why is checkout failing?",
  },
];

type LogEntry = { at: string; action: string; result: "ok" | "failed"; requestId: string; detail?: string };
const LOG_KEY = "opspilot-lab-activity";

function useActivityLog() {
  const [entries, setEntries] = useState<LogEntry[]>([]);
  useEffect(() => {
    try {
      setEntries(JSON.parse(sessionStorage.getItem(LOG_KEY) ?? "[]") as LogEntry[]);
    } catch {
      // ignore unavailable storage
    }
  }, []);
  const add = (entry: LogEntry) =>
    setEntries((prev) => {
      const next = [entry, ...prev].slice(0, 50);
      try {
        sessionStorage.setItem(LOG_KEY, JSON.stringify(next));
      } catch {
        // ignore unavailable storage
      }
      return next;
    });
  return [entries, add] as const;
}

export default function IncidentLabPage() {
  const lab = useLab();
  const services = useServices({ refetchInterval: 5_000 });
  const setFailure = useSetFailure();
  const traffic = useSendTraffic();
  const [pending, setPending] = useState<Scenario | null>(null);
  const [requests, setRequests] = useState("60");
  const [log, addLog] = useActivityLog();
  const checkoutMetrics = useMetrics("checkout", "15m", { refetchInterval: 5_000 });

  const modes = new Map((lab.data?.services ?? []).map((s) => [s.name, s]));
  const healthOf = (name: string) => services.data?.services.find((s) => s.name === name);
  const active = (lab.data?.services ?? []).filter((s) => s.mode && s.mode !== "none");
  const activeScenario = SCENARIOS.find((s) => modes.get(s.service)?.mode === s.mode);

  const change = async (service: string, mode: FailureMode, label: string) => {
    try {
      const { requestId } = await setFailure.mutateAsync({ service, mode });
      addLog({ at: new Date().toISOString(), action: label, result: "ok", requestId });
      toast.success(label);
    } catch (error) {
      const info = describeError(error);
      addLog({ at: new Date().toISOString(), action: label, result: "failed", requestId: info.requestId ?? "—", detail: info.title });
      toast.error(info.title);
    }
  };

  const resetAll = async () => {
    const targets = (lab.data?.services ?? []).filter((s) => s.mode !== "none");
    for (const s of targets.length ? targets : lab.data?.services ?? []) {
      await change(s.name, "none", `Reset ${s.name} to healthy`);
    }
  };

  const sendTraffic = async () => {
    const count = Math.max(1, Math.min(300, Number(requests) || 0));
    try {
      const { data, requestId } = await traffic.mutateAsync(count);
      addLog({ at: new Date().toISOString(), action: `Sent ${data.requests} requests to ${data.target}`, result: "ok", requestId });
      toast.success(`Sending ${data.requests} requests to ${data.target}`);
    } catch (error) {
      const info = describeError(error);
      addLog({ at: new Date().toISOString(), action: `Send ${count} requests`, result: "failed", requestId: info.requestId ?? "—", detail: info.title });
      toast.error(info.title);
    }
  };

  if (lab.isPending) return <LoadingRows rows={6} label="Loading the incident lab" />;
  if (lab.isError) return <ErrorState error={lab.error} onRetry={() => void lab.refetch()} />;

  if (!lab.data.enabled) {
    return (
      <>
        <PageHeader title="Incident Lab" description="Safe, reversible failure injection for the demo services." />
        <EmptyState title="The incident lab is disabled">
          Set <code>ENABLE_INCIDENT_LAB=true</code> on the API to use it with the bundled demo services. It can never
          target a project you connect for monitoring: OpsPilot is read-only toward those.
        </EmptyState>
      </>
    );
  }

  const series = checkoutMetrics.data?.series ?? {};

  return (
    <>
      <PageHeader
        title="Incident Lab"
        description="Break the demo services on purpose, watch the telemetry respond, then let OpsPilot investigate. Only the bundled demo workloads can be targeted."
        actions={
          <Button variant="secondary" onClick={() => void resetAll()} disabled={setFailure.isPending}>
            <HeartPulse /> Reset to healthy
          </Button>
        }
      />
      <div className="space-y-4">
        <section aria-labelledby="demo-path" className="rounded-md border border-dashed px-4 py-3 text-sm">
          <h2 id="demo-path" className="font-semibold">
            Flagship demo, about 30–60 seconds
          </h2>
          <ol className="mt-1 list-decimal space-y-0.5 pl-5 text-muted-foreground">
            <li>Start from healthy: every service below shows mode none and Healthy.</li>
            <li>Inject checkout latency, then send traffic.</li>
            <li>Wait for the p95 chart to rise (usually 15–35 s).</li>
            <li>Choose Open in Investigation and run it: expect checkout&apos;s own request handling as the cause.</li>
            <li>Reset to healthy, and give it a minute of traffic before the next run.</li>
          </ol>
        </section>
        <Card>
          <CardHeader>
            <div>
              <CardTitle>Current state</CardTitle>
              <CardDescription>
                Failure modes as reported by each service, and health measured from Prometheus. Updated every 5 s.
              </CardDescription>
            </div>
            {activeScenario ? (
              <Button asChild size="sm">
                <Link href={newInvestigationHref(activeScenario.question, activeScenario.service)}>
                  <Search /> Open in Investigation
                </Link>
              </Button>
            ) : null}
          </CardHeader>
          <CardContent>
            <ul className="grid gap-2 sm:grid-cols-3">
              {lab.data.services.map((s) => {
                const health = healthOf(s.name);
                return (
                  <li key={s.name} className="flex items-center justify-between gap-2 rounded-md border p-2.5">
                    <div>
                      <p className="text-sm font-medium">{s.name}</p>
                      <p className="text-xs text-muted-foreground">
                        Failure mode:{" "}
                        <span className="font-mono text-foreground">{s.reachable ? s.mode : "unreachable"}</span>
                      </p>
                      <p className="font-mono text-[11px] text-muted-foreground">
                        p95 {formatMs(health?.p95_latency_ms)} · err {formatPercent(health?.error_rate)}
                      </p>
                    </div>
                    <StatusBadge status={health?.health ?? "unknown"} />
                  </li>
                );
              })}
            </ul>
            {active.length === 0 ? (
              <p className="mt-2 text-xs text-muted-foreground">No failure is active. All demo services run normally.</p>
            ) : null}
          </CardContent>
        </Card>

        <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
          {SCENARIOS.map((s) => {
            const on = modes.get(s.service)?.mode === s.mode;
            const reachable = modes.get(s.service)?.reachable ?? false;
            return (
              <Card key={s.id} className="flex flex-col" aria-label={s.title}>
                <CardHeader>
                  <CardTitle className="flex items-center gap-1.5">
                    <FlaskConical className="size-4 text-muted-foreground" aria-hidden />
                    {s.title}
                  </CardTitle>
                  {on ? <Badge variant="degraded">Active</Badge> : null}
                </CardHeader>
                <CardContent className="flex flex-1 flex-col gap-2 text-xs">
                  <p>{s.does}</p>
                  <dl className="space-y-1">
                    <div>
                      <dt className="font-medium">Blast radius</dt>
                      <dd className="text-muted-foreground">
                        Only the demo <span className="font-mono">{s.service}</span> service. Non-destructive: no data
                        is changed.
                      </dd>
                    </div>
                    <div>
                      <dt className="font-medium">Expected telemetry</dt>
                      <dd className="text-muted-foreground">{s.expect}</dd>
                    </div>
                    <div>
                      <dt className="font-medium">Duration</dt>
                      <dd className="text-muted-foreground">Until you reset it. There is no automatic revert.</dd>
                    </div>
                  </dl>
                  <div className="mt-auto pt-1">
                    {on ? (
                      <Button size="sm" variant="secondary" onClick={() => void change(s.service, "none", `Reset ${s.service} to healthy`)}>
                        <HeartPulse /> Revert
                      </Button>
                    ) : (
                      <Button size="sm" variant="outline" disabled={!reachable} onClick={() => setPending(s)}>
                        Inject…
                      </Button>
                    )}
                  </div>
                </CardContent>
              </Card>
            );
          })}
        </div>

        <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.4fr)]">
          <Card>
            <CardHeader>
              <div>
                <CardTitle>Generate traffic</CardTitle>
                <CardDescription>
                  Sends checkout requests one after another from the API, so the metrics have something to move. Failed
                  requests during an incident are expected.
                </CardDescription>
              </div>
            </CardHeader>
            <CardContent className="space-y-3">
              <div className="flex items-end gap-2">
                <div className="space-y-1">
                  <Label htmlFor="traffic-count">Requests (1–300)</Label>
                  <Input
                    id="traffic-count"
                    type="number"
                    min={1}
                    max={300}
                    value={requests}
                    onChange={(e) => setRequests(e.target.value)}
                    className="w-28"
                  />
                </div>
                <Button onClick={() => void sendTraffic()} disabled={traffic.isPending}>
                  {traffic.isPending ? <Loader2 className="animate-spin" /> : <Send />} Send traffic
                </Button>
              </div>
              <p className="text-xs text-muted-foreground">
                Requests run sequentially, so the duration depends on the service&apos;s latency (about 60 requests per
                minute when healthy, fewer while latency is injected).
              </p>
            </CardContent>
          </Card>
          <Card>
            <CardHeader>
              <div>
                <CardTitle>checkout response</CardTitle>
                <CardDescription>p95 latency and error rate, last 15 minutes, every 5 s.</CardDescription>
              </div>
            </CardHeader>
            <CardContent>
              {checkoutMetrics.isError ? (
                <ErrorState error={checkoutMetrics.error} compact onRetry={() => void checkoutMetrics.refetch()} />
              ) : checkoutMetrics.isPending ? (
                <LoadingRows rows={3} label="Loading checkout metrics" />
              ) : (
                <div className="grid gap-3 sm:grid-cols-2">
                  <MetricChart
                    title="p95 latency"
                    height={130}
                    series={[{ key: "p95", label: "p95", points: series["p95_latency_s"] ?? [], color: "var(--chart-1)" }]}
                    format={(v) => formatMs(v * 1000)}
                  />
                  <MetricChart
                    title="Error rate"
                    height={130}
                    series={[{ key: "err", label: "errors", points: series["error_rate"] ?? [], color: "var(--chart-5)" }]}
                    format={(v) => formatPercent(v)}
                  />
                </div>
              )}
            </CardContent>
          </Card>
        </div>

        <Card>
          <CardHeader>
            <div>
              <CardTitle className="flex items-center gap-1.5">
                <Activity className="size-4 text-muted-foreground" aria-hidden /> Activity log
              </CardTitle>
              <CardDescription>Everything the lab did in this browser session, with correlation IDs for the API logs.</CardDescription>
            </div>
          </CardHeader>
          <CardContent>
            {log.length === 0 ? (
              <p className="text-xs text-muted-foreground">Nothing yet.</p>
            ) : (
              <table className="w-full text-xs">
                <thead className="text-left text-muted-foreground">
                  <tr>
                    <th scope="col" className="py-1 font-medium">Time</th>
                    <th scope="col" className="py-1 font-medium">Action</th>
                    <th scope="col" className="py-1 font-medium">Result</th>
                    <th scope="col" className="py-1 font-medium">Correlation ID</th>
                  </tr>
                </thead>
                <tbody>
                  {log.map((e, i) => (
                    <tr key={`${e.at}-${i}`} className="border-t">
                      <td className="py-1 pr-3 font-mono">{formatClock(e.at)}</td>
                      <td className="py-1 pr-3">{e.action}</td>
                      <td className="py-1 pr-3">
                        <StatusBadge status={e.result === "ok" ? "healthy" : "down"} label={e.result === "ok" ? "OK" : `Failed${e.detail ? `: ${e.detail}` : ""}`} />
                      </td>
                      <td className="py-1 font-mono text-muted-foreground">{e.requestId}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </CardContent>
        </Card>
      </div>

      <Dialog open={pending != null} onOpenChange={(open) => !open && setPending(null)}>
        <DialogContent>
          <DialogTitle>{pending?.title}?</DialogTitle>
          <DialogDescription>
            This changes the failure mode of the demo <span className="font-mono">{pending?.service}</span> service.
          </DialogDescription>
          <dl className="grid grid-cols-[7rem_1fr] gap-x-3 gap-y-1.5 text-sm">
            <dt className="text-muted-foreground">Scenario</dt>
            <dd>{pending?.does}</dd>
            <dt className="text-muted-foreground">Target</dt>
            <dd className="font-mono">
              {pending?.service} → mode &quot;{pending?.mode}&quot;
            </dd>
            <dt className="text-muted-foreground">How to revert</dt>
            <dd>Press Revert on the card or Reset to healthy. Nothing reverts on its own.</dd>
          </dl>
          <DialogFooter>
            <Button variant="ghost" onClick={() => setPending(null)}>
              Cancel
            </Button>
            <Button
              onClick={() => {
                const s = pending;
                setPending(null);
                if (s) void change(s.service, s.mode, `Injected ${s.mode} into ${s.service}`);
              }}
            >
              Inject
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}
