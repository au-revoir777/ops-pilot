import { render, screen, within } from "@testing-library/react";
import { ConfidenceBadge, ConfidenceBreakdown } from "@/components/domain/confidence";
import { EvidenceItem } from "@/components/domain/evidence";
import { FindingsPanel } from "@/components/domain/findings-panel";
import { DegradedBanner, EmptyState, ErrorState, LoadingRows } from "@/components/domain/states";
import { StatusBadge } from "@/components/domain/status-badge";
import { TooltipProvider } from "@/components/ui/tooltip";
import { ApiError } from "@/lib/api/errors";
import { clone, deployReport, poisonedReport, prometheusDownReport } from "../fixtures";

const wrap = (ui: React.ReactNode) => render(<TooltipProvider>{ui}</TooltipProvider>);

describe("StatusBadge", () => {
  it.each([
    ["healthy", "Healthy"],
    ["ok", "Healthy"],
    ["degraded", "Degraded"],
    ["down", "Down"],
    ["unavailable", "Down"],
    [null, "Unknown"],
    ["something-else", "Unknown"],
  ])("renders %s as a word, not only a color", (status, word) => {
    render(<StatusBadge status={status} />);
    expect(screen.getByText(word)).toBeInTheDocument();
  });
});

describe("Confidence", () => {
  it("shows a caution state below the threshold", () => {
    render(<ConfidenceBadge value={0.29} />);
    const badge = screen.getByLabelText(/Estimated confidence 29%, low/);
    expect(badge).toHaveAttribute("data-low", "true");
  });

  it("labels model-estimated values", () => {
    render(<ConfidenceBadge value={0.8} modelEstimated />);
    expect(screen.getByText(/Model-estimated/)).toBeInTheDocument();
  });

  it("renders every component of the breakdown and never says probability or accuracy as a claim", () => {
    const { container } = wrap(<ConfidenceBreakdown breakdown={deployReport.confidence_breakdown} />);
    for (const label of ["Temporal correlation", "Metric correlation", "Log correlation", "Deployment correlation", "RAG support", "Contradictions"]) {
      expect(screen.getByText(label)).toBeInTheDocument();
    }
    expect(container.textContent).toContain("not a probability");
    expect(container.textContent?.toLowerCase()).not.toContain("accuracy");
  });
});

describe("FindingsPanel", () => {
  it("renders the sections in order with their labels", () => {
    wrap(<FindingsPanel report={deployReport} />);
    const headings = screen.getAllByRole("heading", { level: 3 }).map((h) => h.textContent?.replace(/\d+$/, "").trim());
    expect(headings).toEqual([
      "Observed facts",
      "Retrieved evidence",
      "Hypotheses",
      "Contradictions and gaps",
      "Validation",
      "Diagnosis",
      "Recommendation",
    ]);
    const facts = screen.getByRole("region", { name: /Observed facts/ });
    expect(within(facts).getAllByText("Fact").length).toBe(deployReport.observations.length);
    expect(within(facts).queryByText("Hypothesis")).toBeNull();
  });

  it("flags an unsupported diagnosis instead of hiding it", () => {
    const report = clone(deployReport);
    for (const h of report.hypotheses) h.supporting = [];
    wrap(<FindingsPanel report={report} />);
    const diagnosis = screen.getByRole("region", { name: /Diagnosis/ });
    expect(within(diagnosis).getByText(/Unsupported/)).toBeInTheDocument();
    expect(within(diagnosis).getByTestId("diagnosis-text")).toHaveTextContent(report.conclusion);
  });

  it("names unavailable sources in the gaps section", () => {
    wrap(<FindingsPanel report={prometheusDownReport} />);
    const gaps = screen.getByRole("region", { name: /Contradictions and gaps/ });
    expect(within(gaps).getAllByText("Unavailable").length).toBeGreaterThan(0);
    expect(within(gaps).getAllByText(/query_metrics returned unavailable/).length).toBeGreaterThan(0);
  });

  it("offers copyable instructions, not execution, for recommendations", () => {
    wrap(<FindingsPanel report={deployReport} />);
    const recs = screen.getByRole("region", { name: /Recommendation/ });
    expect(within(recs).getAllByRole("button", { name: /Review action/ }).length).toBe(deployReport.recommendations.length);
    expect(within(recs).queryByRole("button", { name: /execute|run|apply/i })).toBeNull();
  });
});

describe("EvidenceItem", () => {
  it("shows title, source, relevance score and the injection warning", () => {
    const flagged = poisonedReport.evidence.find((e) => e.flags.length)!;
    render(<EvidenceItem evidence={flagged} />);
    expect(screen.getByText(flagged.citation)).toBeInTheDocument();
    expect(screen.getByText(`score ${flagged.score.toFixed(2)}`)).toBeInTheDocument();
    expect(screen.getByText(/Possible prompt injection/)).toBeInTheDocument();
  });
});

describe("honest states", () => {
  it("loading uses an accessible skeleton", () => {
    render(<LoadingRows label="Loading metrics" />);
    expect(screen.getByRole("status", { name: "Loading metrics" })).toBeInTheDocument();
  });

  it("empty explains what to do", () => {
    render(<EmptyState title="No services">Add a scrape target.</EmptyState>);
    expect(screen.getByText("Add a scrape target.")).toBeInTheDocument();
  });

  it("error names the dependency and shows the correlation ID", () => {
    const error = new ApiError({ kind: "http", code: "mcp_unavailable", message: "x", status: 503, requestId: "req-42", path: "/api/x" });
    render(<ErrorState error={error} onRetry={() => {}} />);
    const alert = screen.getByRole("alert");
    expect(alert).toHaveTextContent("MCP server");
    expect(alert).toHaveTextContent("req-42");
    expect(within(alert).getByRole("button", { name: /Retry/ })).toBeInTheDocument();
  });

  it("degraded names the missing source", () => {
    render(<DegradedBanner sources={["metrics_unavailable"]} />);
    expect(screen.getByRole("status")).toHaveTextContent("metrics_unavailable");
  });
});
