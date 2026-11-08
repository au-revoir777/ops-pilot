import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";
import { apiJson, MODES, PALETTES, useAppearance } from "./helpers";

// axe-core (WCAG 2.1 A/AA rules) on every page, in every palette, light and dark.

const PAGES = [
  { path: "/", ready: "Dashboard" },
  { path: "/investigations", ready: "Investigations" },
  { path: "/incident-lab", ready: "Incident Lab" },
  { path: "/history", ready: "Incident History" },
  { path: "/system", ready: "System Status" },
];

let investigationPath: string | null = null;

test.beforeAll(async ({ browser }) => {
  const page = await browser.newPage();
  try {
    const list = await apiJson<{ id: string; status: string }[]>(page, "/api/investigations?status=completed&limit=1");
    if (list[0]) investigationPath = `/investigations/${list[0].id}`;
  } finally {
    await page.close();
  }
});

for (const palette of PALETTES) {
  for (const mode of MODES) {
    test(`no axe violations: ${palette} ${mode}`, async ({ page }) => {
      test.setTimeout(120_000);
      await useAppearance(page, palette, mode);
      const pages = investigationPath ? [...PAGES, { path: investigationPath, ready: "Investigation" }] : PAGES;
      for (const { path, ready } of pages) {
        await page.goto(path);
        await expect(page.getByRole("heading", { level: 1, name: new RegExp(ready) })).toBeVisible();
        await expect(page.locator("html")).toHaveAttribute("data-theme", palette);
        await expect(page.locator("html")).toHaveClass(new RegExp(mode));
        // Let skeletons resolve so the real content is what gets checked.
        await page.waitForLoadState("networkidle").catch(() => {});
        await expect(page.locator('[role="status"][aria-label^="Loading"]')).toHaveCount(0, { timeout: 30_000 });
        const results = await new AxeBuilder({ page })
          .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"])
          // React Flow renders its own attribution/control chrome we do not style.
          .exclude(".react-flow__attribution")
          .analyze();
        const summary = results.violations.map((v) => `${path}: ${v.id} (${v.nodes.length}) ${v.nodes[0]?.target.join(" ")}`);
        expect(summary, summary.join("\n")).toEqual([]);
      }
    });
  }
}
