import { afterEach, vi } from "vitest";
import { request } from "@/lib/api/client";
import { describeError, isApiError } from "@/lib/api/errors";
import { investigationDetailSchema, publicConfigSchema, replayResultSchema } from "@/lib/api/schemas";
import { clone, deployReport, raw, replayCases } from "../fixtures";

describe("zod contracts against real API payloads", () => {
  it("parses every exported replay fixture", () => {
    for (const payload of [raw.deployRaw, raw.poisonedRaw, raw.prometheusDownRaw, raw.unknownRaw]) {
      expect(replayResultSchema.safeParse(payload).success).toBe(true);
    }
    expect(replayCases.length).toBeGreaterThan(5);
    expect(deployReport.trace.map((t) => t.node)).toEqual(["planner", "rag", "mcp", "hypothesis", "validator", "synthesizer"]);
  });

  it("parses an investigation detail built from a real report", () => {
    const detail = {
      id: "6c2d3409-c591-4b56-bb34-f2ce6f727317",
      incident_id: "1c2d3409-c591-4b56-bb34-f2ce6f727317",
      status: "completed",
      query: deployReport.query,
      service: "checkout",
      root_cause: deployReport.root_cause,
      diagnosis: deployReport.conclusion,
      confidence: deployReport.confidence,
      latency_ms: 20,
      summary: null,
      started_at: "2026-11-08T11:00:00Z",
      completed_at: "2026-11-08T11:00:01Z",
      created_at: "2026-11-08T11:00:00Z",
      updated_at: "2026-11-08T11:00:01Z",
      report: deployReport,
      events: [{ sequence: 1, event_type: "status_change", message: "Investigation created", details: { to: "pending", request_id: "abc" }, created_at: "2026-11-08T11:00:00Z" }],
    };
    expect(investigationDetailSchema.safeParse(detail).success).toBe(true);
  });

  it("rejects a payload with a missing field", () => {
    const broken = clone(raw.deployRaw) as { report: Record<string, unknown> };
    delete broken.report.hypotheses;
    expect(replayResultSchema.safeParse(broken).success).toBe(false);
  });
});

describe("API client", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("sends a correlation ID and surfaces a contract error instead of bad data", async () => {
    const fetchMock = vi.fn(async (_url: string, init: RequestInit) => {
      const id = new Headers(init.headers).get("X-Request-ID");
      return new Response(JSON.stringify({ environment: "development" }), {
        status: 200,
        headers: { "Content-Type": "application/json", "X-Request-ID": id ?? "" },
      });
    });
    vi.stubGlobal("fetch", fetchMock);
    vi.spyOn(console, "error").mockImplementation(() => {});
    const error = await request("/api/config", publicConfigSchema).catch((e: unknown) => e);
    expect(isApiError(error) && error.code).toBe("CONTRACT_ERROR");
    const sent = new Headers(fetchMock.mock.calls[0]![1].headers).get("X-Request-ID");
    expect(sent).toMatch(/^[0-9a-f-]{20,}$/);
    expect(isApiError(error) && error.requestId).toBe(sent);
  });

  it("normalizes API error bodies and maps codes to messages", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        Response.json({ error: { code: "LAB_DISABLED", message: "off", request_id: "r-1" } }, { status: 403 }),
      ),
    );
    const error = await request("/api/lab/failure", publicConfigSchema, { method: "POST", body: {} }).catch((e: unknown) => e);
    const info = describeError(error);
    expect(info.code).toBe("LAB_DISABLED");
    expect(info.title).toBe("The incident lab is disabled");
    expect(info.requestId).toBe("r-1");
  });

  it("reports network failures as the API being unreachable", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => Promise.reject(new TypeError("fetch failed"))));
    const info = describeError(await request("/api/config", publicConfigSchema).catch((e: unknown) => e));
    expect(info.code).toBe("NETWORK_ERROR");
    expect(info.dependency).toBe("API");
    expect(info.requestId).toBeTruthy();
  });

  it.each([
    ["metrics_unavailable", "Prometheus"],
    ["logs_unavailable", "Loki"],
    ["rag_unavailable", "PostgreSQL / pgvector"],
    ["mcp_unavailable", "MCP server"],
    ["llm_unavailable", "LLM provider"],
  ])("maps %s to its dependency", async (code, dependency) => {
    vi.stubGlobal("fetch", vi.fn(async () => Response.json({ error: { code, message: "x" } }, { status: 503 })));
    const info = describeError(await request("/api/x", publicConfigSchema).catch((e: unknown) => e));
    expect(info.dependency).toBe(dependency);
  });
});
