"use client";

import { useCallback, useEffect, useState } from "react";
import { DEFAULT_PALETTE, PALETTE_STORAGE_KEY, isPalette, type PaletteId } from "@/lib/themes";

/** Palette (data-theme on <html>); light/dark is next-themes' job. */
export function usePalette(): [PaletteId, (palette: PaletteId) => void] {
  const [palette, setPaletteState] = useState<PaletteId>(DEFAULT_PALETTE);

  useEffect(() => {
    const current = document.documentElement.getAttribute("data-theme");
    if (isPalette(current)) setPaletteState(current);
    const onChange = (event: Event) => setPaletteState((event as CustomEvent<PaletteId>).detail);
    window.addEventListener("opspilot:palette", onChange);
    return () => window.removeEventListener("opspilot:palette", onChange);
  }, []);

  const setPalette = useCallback((next: PaletteId) => {
    document.documentElement.setAttribute("data-theme", next);
    try {
      localStorage.setItem(PALETTE_STORAGE_KEY, next);
    } catch {
      // storage can be unavailable (private mode); the palette still applies for this page
    }
    window.dispatchEvent(new CustomEvent("opspilot:palette", { detail: next }));
  }, []);

  return [palette, setPalette];
}
