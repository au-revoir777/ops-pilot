"use client";

import { FileDown, Link as LinkIcon, RotateCcw } from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useCopy } from "@/hooks/use-copy";
import { useMediaQuery } from "@/hooks/use-media-query";
import type { Report } from "@/lib/api/schemas";
import { buildFindings, isModelEstimated, reportToMarkdown } from "@/lib/epistemic";
import { formatMs, formatTimestamp, humanize } from "@/lib/format";
import { newInvestigationHref } from "@/lib/links";
import { AgentTrace, type TraceSelection } from "./agent-trace";
import { ConfidenceBadge } from "./confidence";
import { CopyButton } from "./copy-button";
import type { SourceTarget } from "./evidence";
import { FindingsPanel } from "./findings-panel";
import { SourcesPanel } from "./sources-panel";
import { DegradedBanner } from "./states";
import { UntrustedText } from "./untrusted-text";

export type InvestigationMeta = {
  id?: string;
  requestId?: string | null;
  latencyMs?: number | null;
  createdAt?: string | null;
  /** Replays have no stored record and no shareable link. */
  replay?: boolean;
};

export function InvestigationView({ report, meta }: { report: Report; meta: InvestigationMeta }) {
  const [step, setStep] = useState<TraceSelection>(null);
  const [target, setTarget] = useState<SourceTarget | null>(null);
  const [mobileTab, setMobileTab] = useState("findings");
  const copy = useCopy();
  const desktop = useMediaQuery("(min-width: 1024px)");
  const modelEstimated = isModelEstimated(report);
  const findings = buildFindings(report);
  const unavailable = report.tool_calls.filter((c) => c.status === "unavailable" || c.status === "error").map((c) => `${c.tool}: ${c.status}`);
  const llmStatus = report.llm?.["status"];

  const cite = (t: SourceTarget) => {
    setTarget({ ...t }); // new object so a repeat click re-triggers the highlight
    setMobileTab("sources");
  };
  const url = meta.id && typeof window !== "undefined" ? `${window.location.origin}/investigations/${meta.id}` : undefined;

  const trace = <AgentTrace steps={report.trace} selected={step} onSelect={setStep} />;
  const center = <FindingsPanel report={report} focus={step?.node} onCite={cite} modelEstimated={modelEstimated} />;
  const sources = <SourcesPanel report={report} target={target} />;

  return (
    <div className="space-y-4">
      <Card>
        <CardContent className="space-y-2 pt-3">
          <div className="flex flex-wrap items-center gap-2">
            {meta.replay ? <Badge variant="info">Replay</Badge> : null}
            <Badge variant="outline" className="font-mono">
              {report.service ?? "service unknown"}
            </Badge>
            <ConfidenceBadge value={report.root_cause ? report.confidence : null} modelEstimated={modelEstimated} />
            {meta.latencyMs != null ? <span className="font-mono text-xs text-muted-foreground">{formatMs(meta.latencyMs)} total</span> : null}
            {meta.createdAt ? <span className="text-xs text-muted-foreground">{formatTimestamp(meta.createdAt)}</span> : null}
            <span className="flex-1" />
            <Button variant="outline" size="sm" onClick={() => void copy(reportToMarkdown(report, { id: meta.id, requestId: meta.requestId ?? undefined, url }), "Investigation copied as Markdown")}>
              <FileDown /> Copy as Markdown
            </Button>
            {url ? (
              <Button variant="outline" size="sm" onClick={() => void copy(url, "Link copied")}>
                <LinkIcon /> Copy link
              </Button>
            ) : null}
            {!meta.replay ? (
              <Button asChild variant="outline" size="sm">
                <Link href={newInvestigationHref(report.query, report.service)}>
                  <RotateCcw /> Run again
                </Link>
              </Button>
            ) : null}
          </div>
          <p className="text-xs text-muted-foreground">
            Question: <UntrustedText text={report.query} className="text-foreground" />
          </p>
          <h2 className="text-lg leading-snug font-semibold" data-testid="diagnosis-headline">
            {report.root_cause ? (
              <>
                <span className="mr-1.5 align-middle text-xs font-medium tracking-wide text-muted-foreground">Most likely root cause:</span>
                {humanize(report.root_cause)}
              </>
            ) : (
              "No root cause identified"
            )}
          </h2>
          <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-muted-foreground">
            {meta.id ? (
              <span className="flex items-center gap-1">
                Investigation <code className="font-mono text-foreground">{meta.id}</code>
                <CopyButton value={meta.id} label="Copy investigation ID" />
              </span>
            ) : null}
            {meta.requestId ? (
              <span className="flex items-center gap-1">
                Correlation ID <code className="font-mono text-foreground">{meta.requestId}</code>
                <CopyButton value={meta.requestId} label="Copy correlation ID" />
              </span>
            ) : null}
            <span>
              {report.iterations} evidence round{report.iterations === 1 ? "" : "s"} · {report.window_minutes} min window
            </span>
            {llmStatus === "used" ? <span>Language model used for: summary or service extraction (labelled)</span> : null}
          </div>
        </CardContent>
      </Card>

      {findings.documentationOnly ? (
        <DegradedBanner sources={["mcp_unavailable"]}>
          Operational evidence was unavailable. Any diagnosis below is based on documentation only.
        </DegradedBanner>
      ) : unavailable.length ? (
        <DegradedBanner sources={unavailable}>These sources did not answer; confidence was lowered for the missing coverage.</DegradedBanner>
      ) : null}
      {llmStatus === "unavailable" ? (
        <DegradedBanner sources={["llm_unavailable"]}>The optional model summary is missing. Rule-based findings are unaffected.</DegradedBanner>
      ) : null}

      {/* Desktop: three regions. Below 1024px: tabs. Only one layout is mounted, so ids stay unique. */}
      {desktop ? (
        <div className="grid grid-cols-[17rem_minmax(0,1fr)_22rem] gap-4 xl:grid-cols-[19rem_minmax(0,1fr)_26rem]">
          <Card className="self-start">
            <CardHeader>
              <CardTitle>Agent trace</CardTitle>
            </CardHeader>
            <CardContent>{trace}</CardContent>
          </Card>
          <div>{center}</div>
          <Card className="sticky top-0 self-start">
            <CardHeader>
              <CardTitle>Sources</CardTitle>
            </CardHeader>
            <CardContent className="max-h-[calc(100dvh-6rem)] overflow-y-auto">{sources}</CardContent>
          </Card>
        </div>
      ) : (
        <Tabs value={mobileTab} onValueChange={setMobileTab}>
          <TabsList aria-label="Investigation regions">
            <TabsTrigger value="trace">Trace</TabsTrigger>
            <TabsTrigger value="findings">Findings</TabsTrigger>
            <TabsTrigger value="sources">Sources</TabsTrigger>
          </TabsList>
          <TabsContent value="trace">{trace}</TabsContent>
          <TabsContent value="findings">{center}</TabsContent>
          <TabsContent value="sources">{sources}</TabsContent>
        </Tabs>
      )}
    </div>
  );
}
