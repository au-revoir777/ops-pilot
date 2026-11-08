import { expect, test } from "@playwright/test";

test("read-only mode is visible and explained", async ({ page }) => {
  await page.goto("/");
  const indicator = page.getByRole("button", { name: /READ-ONLY/ });
  await expect(indicator).toBeVisible();
  await indicator.hover();
  await expect(page.getByRole("tooltip")).toContainText("cannot restart, roll back, scale");
});

test("command palette switches palette and navigates by keyboard", async ({ page }) => {
  await page.goto("/");
  await page.keyboard.press("Control+k");
  const palette = page.getByRole("dialog", { name: "Command palette" });
  await expect(palette).toBeVisible();
  await page.keyboard.type("ocean");
  // cmdk filters asynchronously; wait until the match is the highlighted option.
  await expect(palette.getByRole("option", { name: /Switch to Ocean/ })).toHaveAttribute("aria-selected", "true");
  await page.keyboard.press("Enter");
  await expect(page.locator("html")).toHaveAttribute("data-theme", "ocean");
  // The choice survives a reload with no flash of the default palette.
  await page.reload();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "ocean");

  await page.keyboard.press("Control+k");
  await page.keyboard.type("System Status");
  await expect(page.getByRole("option", { name: /System Status/ })).toHaveAttribute("aria-selected", "true");
  await page.keyboard.press("Enter");
  await expect(page).toHaveURL(/\/system$/);

  // g-then-letter shortcuts
  await page.locator("body").press("g");
  await page.locator("body").press("h");
  await expect(page).toHaveURL(/\/history$/);
});

test("inject from the palette opens the lab instead of firing", async ({ page }) => {
  await page.goto("/");
  await page.keyboard.press("Control+k");
  await page.keyboard.type("inject");
  await expect(page.getByRole("option", { name: /Inject incident/ })).toHaveAttribute("aria-selected", "true");
  await page.keyboard.press("Enter");
  await expect(page).toHaveURL(/\/incident-lab$/);
});

test("security headers are set", async ({ page }) => {
  const response = await page.goto("/");
  const headers = response!.headers();
  expect(headers["content-security-policy"]).toContain("default-src 'self'");
  expect(headers["content-security-policy"]).toContain("frame-ancestors 'none'");
  expect(headers["x-content-type-options"]).toBe("nosniff");
});
