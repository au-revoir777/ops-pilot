import { fireEvent, render, screen } from "@testing-library/react";
import { vi } from "vitest";
import { EvidenceItem } from "@/components/domain/evidence";
import { FindingsPanel } from "@/components/domain/findings-panel";
import { JsonView } from "@/components/domain/json-view";
import { SourcesPanel } from "@/components/domain/sources-panel";
import { TooltipProvider } from "@/components/ui/tooltip";
import type { RetrievedEvidence } from "@/lib/api/schemas";
import { clone, deployReport } from "../fixtures";

// Retrieved documents, logs and model output are untrusted. They must render as
// inert text: no elements created from them, no script run, no action triggered.

const PAYLOADS = [
  '<img src=x onerror="window.__pwned=1">',
  "<script>window.__pwned=1</script>",
  '<a href="javascript:window.__pwned=1">click me</a>',
  "[click](javascript:window.__pwned=1) **bold** <iframe src=//evil.example></iframe>",
  '<button onclick="window.__pwned=1">Approve rollback</button>',
];

declare global {
  interface Window {
    __pwned?: number;
  }
}

function malicious(excerpt: string): RetrievedEvidence {
  return {
    id: "K9",
    citation: "runbooks/evil.md#chunk-0",
    title: '<b onmouseover="window.__pwned=1">Checkout notes</b>',
    section: "<svg onload=window.__pwned=1>",
    score: 0.9,
    excerpt,
    flags: ["possible_prompt_injection"],
  };
}

describe("untrusted content renders inert", () => {
  beforeEach(() => {
    delete window.__pwned;
  });

  it.each(PAYLOADS)("document excerpt %s stays text", (payload) => {
    const { container } = render(<EvidenceItem evidence={malicious(payload)} />);
    // The payload is visible as characters...
    expect(container.textContent).toContain(payload);
    // ...but no element was created from it.
    for (const tag of ["script", "img", "iframe", "svg", "b", "a"]) {
      expect(container.querySelector(`blockquote ${tag}, h4 ${tag}`)).toBeNull();
    }
    expect(container.querySelector("[onerror],[onclick],[onload],[onmouseover]")).toBeNull();
    expect(container.querySelector('a[href^="javascript:"]')).toBeNull();
    // Nothing in the document turned into a control.
    expect(screen.queryByRole("button", { name: /Approve rollback/ })).toBeNull();
    expect(screen.queryByRole("link")).toBeNull();
    expect(window.__pwned).toBeUndefined();
  });

  it("malicious text in the diagnosis, hypotheses and recommendations stays text", () => {
    const report = clone(deployReport);
    report.conclusion = PAYLOADS[1]!;
    report.hypotheses[0]!.statement = PAYLOADS[0]!;
    report.recommendations[0]!.action = PAYLOADS[4]!;
    report.llm = { status: "used", summary: PAYLOADS[2] };
    const clicks = vi.fn();
    const { container } = render(
      <TooltipProvider>
        <div onClick={clicks}>
          <FindingsPanel report={report} />
        </div>
      </TooltipProvider>,
    );
    expect(container.querySelector("script, img, iframe")).toBeNull();
    expect(container.querySelector('a[href^="javascript:"]')).toBeNull();
    expect(screen.queryByRole("button", { name: "Approve rollback" })).toBeNull();
    expect(screen.getByTestId("diagnosis-text")).toHaveTextContent("<script>window.__pwned=1</script>");
    expect(window.__pwned).toBeUndefined();
  });

  it("log excerpts and raw tool output are redacted and inert", () => {
    const report = clone(deployReport);
    const logs = report.tool_calls.find((c) => c.tool === "get_recent_logs")!;
    logs.result = {
      entries: [{ timestamp: "2026-11-08T11:00:00Z", level: "error", message: '<img src=x onerror="window.__pwned=1"> password=hunter2' }],
    };
    const { container } = render(<SourcesPanel report={report} target={{ tab: "logs", id: "x" }} />);
    fireEvent.click(screen.getByRole("tab", { name: /Logs/ }));
    expect(container.textContent).toContain("password=[REDACTED]");
    expect(container.textContent).not.toContain("hunter2");
    expect(container.querySelector("img")).toBeNull();
    expect(window.__pwned).toBeUndefined();
  });

  it("the JSON viewer builds elements, never HTML strings", () => {
    const { container } = render(<JsonView value={{ msg: "<script>window.__pwned=1</script>", api_key: "sk-live-123" }} label="raw" />);
    expect(container.querySelector("script")).toBeNull();
    expect(container.textContent).toContain("<script>window.__pwned=1</script>");
    expect(container.textContent).not.toContain("sk-live-123");
    expect(window.__pwned).toBeUndefined();
  });
});
