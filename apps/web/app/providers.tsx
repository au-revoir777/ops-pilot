"use client";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { ThemeProvider } from "next-themes";
import { useState } from "react";
import { Toaster } from "sonner";
import { TooltipProvider } from "@/components/ui/tooltip";
import { isApiError } from "@/lib/api/errors";

function makeClient() {
  return new QueryClient({
    defaultOptions: {
      queries: {
        // Queries are GETs (idempotent): retry transient failures with backoff,
        // but not client errors or contract errors, which will not fix themselves.
        retry: (count, error) =>
          count < 2 && !(isApiError(error) && (error.kind === "contract" || (error.status ?? 0) >= 400 && (error.status ?? 0) < 500)),
        retryDelay: (attempt) => Math.min(1000 * 2 ** attempt, 8000),
        refetchOnWindowFocus: false,
        // Structural sharing keeps unchanged poll results referentially equal,
        // so charts do not re-render when nothing changed.
        structuralSharing: true,
      },
      mutations: { retry: false },
    },
  });
}

export function Providers({ children }: { children: React.ReactNode }) {
  const [client] = useState(makeClient);
  return (
    <ThemeProvider attribute="class" defaultTheme="system" enableSystem disableTransitionOnChange>
      <QueryClientProvider client={client}>
        <TooltipProvider>
          {children}
          <Toaster position="bottom-right" closeButton toastOptions={{ className: "font-sans" }} />
        </TooltipProvider>
      </QueryClientProvider>
    </ThemeProvider>
  );
}
