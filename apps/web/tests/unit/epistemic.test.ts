import { buildFindings, reportToMarkdown, SECTION_ORDER, validationChecks } from "@/lib/epistemic";
import { clone, deployReport, poisonedReport, prometheusDownReport, unknownReport } from "../fixtures";

describe("epistemic findings", () => {
  it("keeps the seven sections in the required order", () => {
    expect(SECTION_ORDER).toEqual(["facts", "retrieved", "hypotheses", "gaps", "validation", "diagnosis", "recommendation"]);
  });

  it("never merges hypotheses into facts", () => {
    const f = buildFindings(deployReport);
    const factIds = new Set(f.facts.map((o) => o.id));
    expect(f.hypotheses.length).toBeGreaterThan(0);
    for (const h of f.hypotheses) expect(factIds.has(h.id)).toBe(false);
    expect(f.facts).toEqual(deployReport.observations);
  });

  it("links the diagnosis to the evidence behind the leading hypothesis", () => {
    const f = buildFindings(deployReport);
    expect(f.diagnosis?.unsupported).toBe(false);
    expect(f.diagnosis?.refs.length).toBeGreaterThan(0);
    expect(f.diagnosis?.refs.every((r) => r.type !== "missing")).toBe(true);
    expect(f.hypotheses.find((h) => h.leading)?.cause).toBe("deployment_db_regression");
  });

  it("flags a diagnosis as unsupported when nothing in the payload backs it", () => {
    const report = clone(deployReport);
    for (const h of report.hypotheses) h.supporting = ["F999"];
    const f = buildFindings(report);
    expect(f.diagnosis?.unsupported).toBe(true);
    expect(f.diagnosis?.refs[0]).toEqual({ type: "missing", id: "F999" });
  });

  it("flags recommendation references that were never retrieved", () => {
    const report = clone(deployReport);
    report.recommendations[0]!.references = ["runbooks/made-up.md#chunk-0"];
    const [first] = buildFindings(report).recommendations;
    expect(first?.unsupported).toBe(true);
    expect(first?.unknownReferences).toEqual(["runbooks/made-up.md#chunk-0"]);
  });

  it("lists unavailable telemetry as gaps instead of dropping it", () => {
    const f = buildFindings(prometheusDownReport);
    expect(f.gaps.some((g) => g.kind === "unavailable" && g.tool === "query_metrics")).toBe(true);
    expect(f.gaps.some((g) => g.kind === "missing")).toBe(true);
    expect(f.hypotheses[0]?.label).toBe("weakened");
  });

  it("marks a telemetry-free diagnosis as documentation only", () => {
    const report = clone(prometheusDownReport);
    report.observations = [];
    report.tool_calls = report.tool_calls.map((c) => ({ ...c, status: "unavailable" }));
    expect(buildFindings(report).documentationOnly).toBe(true);
    expect(buildFindings(prometheusDownReport).documentationOnly).toBe(false);
  });

  it("handles an investigation with no service and no hypotheses", () => {
    const f = buildFindings(unknownReport);
    expect(f.hypotheses).toEqual([]);
    expect(f.validation).toEqual([]);
    expect(f.diagnosis?.unsupported).toBe(false); // no root cause claimed, so nothing is unsupported
  });

  it("derives validation checks from the confidence breakdown", () => {
    const checks = validationChecks(deployReport.confidence_breakdown);
    expect(checks.map((c) => c.label)).toContain("Temporal correlation");
    expect(checks.find((c) => c.key === "contradictions")?.result).toBe("clear");
  });

  it("does not cite the flagged prompt-injection document", () => {
    const refs = buildFindings(poisonedReport).recommendations.flatMap((r) => r.references);
    expect(refs.some((r) => r.startsWith("runbooks/evil.md"))).toBe(false);
  });

  it("exports Markdown that labels confidence as a heuristic", () => {
    const md = reportToMarkdown(deployReport, { id: "abc", requestId: "rid-1" });
    expect(md).toContain("## Observed facts");
    expect(md).toContain("heuristic, not a probability");
    expect(md).toContain("rid-1");
    expect(md.toLowerCase()).not.toContain("accuracy");
  });
});
