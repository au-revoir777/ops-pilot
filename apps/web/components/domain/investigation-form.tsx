"use client";

import { Loader2, Play, RotateCcw } from "lucide-react";
import { useRouter, useSearchParams } from "next/navigation";
import { useEffect, useId, useState } from "react";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Label, NativeSelect, Textarea } from "@/components/ui/input";
import { useReplay, useReplays, useServices, useStartInvestigation } from "@/hooks/use-api";
import { ReplayView } from "./replay-result";
import { ErrorState } from "./states";

const WINDOWS = [15, 30, 60, 120, 360];

export function InvestigationForm() {
  const router = useRouter();
  const params = useSearchParams();
  const ids = { query: useId(), service: useId(), window: useId(), replay: useId() };
  const [mode, setMode] = useState<"live" | "replay">(params.get("mode") === "replay" ? "replay" : "live");
  const [query, setQuery] = useState(params.get("q") ?? "");
  const [service, setService] = useState(params.get("service") ?? "");
  const [windowMinutes, setWindowMinutes] = useState("");
  const [caseId, setCaseId] = useState(params.get("case") ?? "");
  const incidentId = params.get("incident");

  const services = useServices({ refetchInterval: false });
  const replays = useReplays();
  const start = useStartInvestigation();
  const replay = useReplay();

  useEffect(() => {
    if (!caseId && replays.data?.[0]) setCaseId(replays.data[0].id);
  }, [caseId, replays.data]);

  const names = (services.data?.services ?? []).map((s) => s.name);
  const busy = start.isPending || replay.isPending;
  const canRun = mode === "live" ? query.trim().length >= 3 : !!caseId;

  const submit = (event?: React.FormEvent) => {
    event?.preventDefault();
    if (!canRun || busy) return;
    if (mode === "replay") {
      replay.mutate(caseId);
      return;
    }
    start.mutate(
      {
        query: query.trim(),
        service: service || undefined,
        incident_id: incidentId ?? undefined,
        window_minutes: windowMinutes ? Number(windowMinutes) : undefined,
        wait: false, // returns 202 at once; the detail page polls for the result
      },
      { onSuccess: ({ data }) => router.push(`/investigations/${data.id}`) },
    );
  };

  return (
    <div className="space-y-4">
      <Card>
        <CardContent className="pt-3">
          <form onSubmit={submit} className="space-y-3" aria-label="New investigation">
            <div role="radiogroup" aria-label="Mode" className="inline-flex rounded-md border p-0.5">
              {(["live", "replay"] as const).map((m) => (
                <Button
                  key={m}
                  type="button"
                  role="radio"
                  aria-checked={mode === m}
                  size="sm"
                  variant={mode === m ? "secondary" : "ghost"}
                  className="h-6"
                  onClick={() => setMode(m)}
                >
                  {m === "live" ? "Live investigation" : "Replay incident"}
                </Button>
              ))}
            </div>
            {mode === "live" ? (
              <>
                <div className="space-y-1">
                  <Label htmlFor={ids.query}>What should OpsPilot investigate?</Label>
                  <Textarea
                    id={ids.query}
                    value={query}
                    onChange={(e) => setQuery(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) submit();
                    }}
                    placeholder="e.g. Investigate why checkout latency increased"
                    maxLength={1000}
                    rows={2}
                    autoFocus={params.get("new") === "1"}
                  />
                </div>
                <div className="flex flex-wrap items-end gap-3">
                  <div className="space-y-1">
                    <Label htmlFor={ids.service}>Service</Label>
                    <NativeSelect id={ids.service} value={service} onChange={(e) => setService(e.target.value)} className="w-44">
                      <option value="">Auto-detect</option>
                      {names.map((n) => (
                        <option key={n} value={n}>
                          {n}
                        </option>
                      ))}
                    </NativeSelect>
                  </div>
                  <div className="space-y-1">
                    <Label htmlFor={ids.window}>Time window</Label>
                    <NativeSelect id={ids.window} value={windowMinutes} onChange={(e) => setWindowMinutes(e.target.value)} className="w-36">
                      <option value="">Default</option>
                      {WINDOWS.map((w) => (
                        <option key={w} value={w}>
                          Last {w < 60 ? `${w} min` : `${w / 60} h`}
                        </option>
                      ))}
                    </NativeSelect>
                  </div>
                  {incidentId ? <p className="text-xs text-muted-foreground">Linked to incident {incidentId.slice(0, 8)}</p> : null}
                  <div className="flex-1" />
                  <Button type="submit" disabled={!canRun || busy}>
                    {start.isPending ? <Loader2 className="animate-spin" /> : <Play />} Investigate
                  </Button>
                </div>
              </>
            ) : (
              <div className="flex flex-wrap items-end gap-3">
                <div className="min-w-64 flex-1 space-y-1">
                  <Label htmlFor={ids.replay}>Recorded incident</Label>
                  <NativeSelect id={ids.replay} value={caseId} onChange={(e) => setCaseId(e.target.value)} disabled={!replays.data}>
                    {(replays.data ?? []).map((c) => (
                      <option key={c.id} value={c.id}>
                        {c.id}: {c.question}
                      </option>
                    ))}
                  </NativeSelect>
                </div>
                <Button type="submit" disabled={!canRun || busy}>
                  {replay.isPending ? <Loader2 className="animate-spin" /> : <RotateCcw />} Replay
                </Button>
              </div>
            )}
            <p className="text-xs text-muted-foreground">
              {mode === "live"
                ? "Runs the read-only agent against live telemetry and the knowledge base. Ctrl+Enter to run."
                : "Replays a recorded scenario through the real agent. Nothing is stored and no live system is touched."}
            </p>
          </form>
        </CardContent>
      </Card>
      {start.isError ? <ErrorState error={start.error} onRetry={() => submit()} /> : null}
      {replays.isError && mode === "replay" ? <ErrorState error={replays.error} onRetry={() => void replays.refetch()} /> : null}
      {replay.isError ? <ErrorState error={replay.error} onRetry={() => submit()} /> : null}
      {mode === "replay" && replay.data ? <ReplayView result={replay.data.data} /> : null}
    </div>
  );
}
