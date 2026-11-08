import { defineConfig, devices } from "@playwright/test";

// E2E tests run against a running stack (docker compose up, web on :3001).
// Override with E2E_BASE_URL. The flagship flow needs ENABLE_INCIDENT_LAB=true
// and ENABLE_FAILURE_INJECTION=true.
export default defineConfig({
  testDir: "./tests/e2e",
  timeout: 60_000,
  expect: { timeout: 15_000 },
  fullyParallel: false,
  workers: 1,
  retries: 0,
  reporter: [["list"], ["html", { open: "never" }]],
  use: {
    baseURL: process.env.E2E_BASE_URL ?? "http://127.0.0.1:3001",
    trace: "off",
    screenshot: "only-on-failure",
    viewport: { width: 1440, height: 900 },
  },
  projects: [
    {
      name: "chromium",
      use: {
        ...devices["Desktop Chrome"],
        viewport: { width: 1440, height: 900 },
        // Optional: reuse an already-installed Chromium instead of downloading Playwright's own.
        launchOptions: process.env.PW_CHROMIUM_PATH ? { executablePath: process.env.PW_CHROMIUM_PATH } : {},
      },
    },
  ],
});
