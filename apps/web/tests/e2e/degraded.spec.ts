import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { expect, test } from "@playwright/test";

// Degraded mode with MCP unavailable. The API is intercepted in the browser so
// the outage is deterministic and nothing in the running stack is stopped.

const fixture = (name: string) => fileURLToPath(new URL(`../fixtures/${name}`, import.meta.url));
const prometheusDown = JSON.parse(readFileSync(fixture("replay-prometheus-down-logs-only.json"), "utf8"));

test("dashboard names the missing sources and keeps the rest working", async ({ page }) => {
  await page.route("**/api/health", (route) =>
    route.fulfill({ json: { status: "degraded", timestamp: new Date().toISOString(), checks: { database: "ok", knowledge_base: "ok", mcp: "down", llm: "disabled" } } }),
  );
  await page.route("**/api/services?**", (route) => route.fulfill({ json: { services: [], telemetry_status: "unavailable" } }));
  await page.goto("/");
  const banner = page.getByRole("status").filter({ hasText: "Degraded:" });
  await expect(banner).toContainText("metrics_unavailable");
  await expect(banner).toContainText("mcp: down");
  // Panels that do not need MCP still render (incidents come from the database).
  await expect(page.getByRole("heading", { name: "Active incidents" })).toBeVisible();
});

test("investigation without operational evidence is marked documentation-only", async ({ page }) => {
  const report = structuredClone(prometheusDown.report);
  report.observations = [];
  report.tool_calls = report.tool_calls.map((c: Record<string, unknown>) => ({ ...c, status: "unavailable", error: "mcp_unavailable" }));
  for (const h of report.hypotheses) h.supporting = h.supporting.filter((id: string) => id.startsWith("K"));
  const id = "00000000-0000-4000-8000-000000000001";
  await page.route(`**/api/investigations/${id}`, (route) =>
    route.fulfill({
      json: {
        id,
        incident_id: "00000000-0000-4000-8000-000000000002",
        status: "completed",
        query: report.query,
        service: report.service,
        root_cause: report.root_cause,
        diagnosis: report.conclusion,
        confidence: report.confidence,
        latency_ms: 1200,
        summary: null,
        started_at: "2026-11-08T11:00:00Z",
        completed_at: "2026-11-08T11:00:01Z",
        created_at: "2026-11-08T11:00:00Z",
        updated_at: "2026-11-08T11:00:01Z",
        report,
        events: [],
      },
    }),
  );
  await page.goto(`/investigations/${id}`);
  await expect(page.getByRole("status").filter({ hasText: "mcp_unavailable" })).toContainText("based on documentation only");
  const diagnosis = page.getByRole("region", { name: /Diagnosis/ });
  await expect(diagnosis).toContainText("Based on documentation only");
  await expect(page.getByRole("region", { name: /Observed facts/ })).toContainText("operational evidence was unavailable");
  await expect(page.getByRole("region", { name: /Contradictions and gaps/ })).toContainText("Unavailable");
});

test("an unreachable API shows which dependency failed and a correlation ID", async ({ page }) => {
  await page.route("**/api/investigations?**", (route) =>
    route.fulfill({ status: 502, json: { error: { code: "API_UNREACHABLE", message: "down", request_id: "e2e-req-1" } } }),
  );
  await page.goto("/investigations");
  const alert = page.getByRole("alert").first();
  await expect(alert).toContainText("The OpsPilot API is unreachable");
  await expect(alert).toContainText("e2e-req-1");
});
