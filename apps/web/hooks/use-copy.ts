"use client";

import { useCallback } from "react";
import { toast } from "sonner";

export function useCopy() {
  return useCallback(async (text: string, what = "Copied") => {
    try {
      await navigator.clipboard.writeText(text);
      toast.success(what);
    } catch {
      toast.error("Could not copy to the clipboard");
    }
  }, []);
}
