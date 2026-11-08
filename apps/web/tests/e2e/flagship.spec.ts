import { expect, test } from "@playwright/test";
import { apiJson } from "./helpers";

// The flagship demo path against the live stack: inject a failure in the lab,
// generate traffic, watch the dashboard react, investigate, and check that the
// findings are labelled correctly. Needs ENABLE_INCIDENT_LAB=true and
// ENABLE_FAILURE_INJECTION=true. Resets checkout to healthy afterwards.

test.describe.configure({ mode: "serial" });

test.afterAll(async ({ browser }) => {
  const page = await browser.newPage();
  await apiJson(page, "/api/lab/failure", { method: "POST", data: { service: "checkout", mode: "none" } }).catch(() => {});
  await page.close();
});

test("inject, traffic, dashboard, investigate, diagnose", async ({ page }) => {
  test.setTimeout(8 * 60_000);
  const lab = await apiJson<{ enabled: boolean }>(page, "/api/lab");
  test.skip(!lab.enabled, "Incident lab is disabled (ENABLE_INCIDENT_LAB=false)");

  // 1. Incident Lab: inject DB slowness, with the confirmation dialog.
  await page.goto("/incident-lab");
  const card = page.getByRole("region", { name: "Simulate DB slowness" });
  await card.getByRole("button", { name: "Inject…" }).click();
  const dialog = page.getByRole("dialog");
  await expect(dialog).toContainText("How to revert");
  await dialog.getByRole("button", { name: "Inject" }).click();
  // Live status comes from the service itself, not the click.
  await expect(card.getByText("Active")).toBeVisible({ timeout: 20_000 });

  // 2. Generate traffic.
  await page.getByLabel("Requests (1–300)").fill("120");
  await page.getByRole("button", { name: "Send traffic" }).click();
  await expect(page.getByRole("table")).toContainText("Sent 120 requests to checkout");

  // 3. Dashboard: checkout turns degraded once Prometheus sees the slow requests.
  await page.goto("/");
  const checkout = page.getByRole("region", { name: "checkout service" });
  await expect(checkout.locator("[data-status]")).toHaveAttribute("data-status", /degraded|down/, { timeout: 150_000 });

  // 4. Investigate from the lab's pre-filled query.
  await page.goto("/incident-lab");
  await page.getByRole("link", { name: "Open in Investigation" }).click();
  await expect(page.getByLabel("What should OpsPilot investigate?")).toHaveValue(/checkout/i);
  await page.getByRole("button", { name: "Investigate", exact: true }).click();
  // On a loaded machine even the 202 can take a while.
  await expect(page).toHaveURL(/\/investigations\/[0-9a-f-]{36}$/, { timeout: 90_000 });

  // 5. Findings render with the right labels (the agent can take a while on a loaded machine).
  await expect(page.getByTestId("findings")).toBeVisible({ timeout: 240_000 });
  for (const section of ["Observed facts", "Retrieved evidence", "Hypotheses", "Contradictions and gaps", "Validation", "Diagnosis", "Recommendation"]) {
    await expect(page.getByRole("heading", { level: 3, name: new RegExp(section) })).toBeVisible();
  }
  await expect(page.getByTestId("diagnosis-headline")).toContainText("Most likely root cause:");
  await expect(page.getByTestId("diagnosis-headline")).toContainText(/database/i);
  await expect(page.getByText(/est\. confidence/).first()).toBeVisible();
  await expect(page.getByTestId("confidence-breakdown")).toContainText("not a probability");
  const facts = page.getByRole("region", { name: /Observed facts/ });
  await expect(facts.getByText("Fact").first()).toBeVisible();
  await expect(facts.getByText("Hypothesis")).toHaveCount(0);
  // The correlation ID of the creating request is shown and copyable.
  await expect(page.getByRole("button", { name: "Copy correlation ID" })).toBeVisible();

  // 6. A citation opens the source in the Sources panel.
  await facts.getByRole("button", { name: /Show tool call .* that produced this fact/ }).first().click();
  await expect(page.locator("[data-tool][data-highlighted]")).toBeVisible();
});
