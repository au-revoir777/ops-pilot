import type { Page } from "@playwright/test";

export const PALETTES = ["graphite", "ocean", "ember", "forest"] as const;
export const MODES = ["light", "dark"] as const;

/** Sets palette and mode before any page script runs (same keys the app uses). */
export async function useAppearance(page: Page, palette: string, mode: string) {
  await page.addInitScript(
    ([p, m]) => {
      localStorage.setItem("opspilot-palette", p!);
      localStorage.setItem("theme", m!);
    },
    [palette, mode],
  );
}

export async function apiJson<T>(page: Page, path: string, init?: { method?: string; data?: unknown }): Promise<T> {
  const response = await page.request.fetch(path, { method: init?.method ?? "GET", data: init?.data });
  if (!response.ok()) throw new Error(`${path} -> ${response.status()} ${await response.text()}`);
  return (await response.json()) as T;
}
