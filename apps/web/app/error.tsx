"use client";

import { ErrorState } from "@/components/domain/states";

export default function RouteError({ error, reset }: { error: Error & { digest?: string }; reset: () => void }) {
  return (
    <div className="mx-auto max-w-2xl py-10">
      <ErrorState error={error} onRetry={reset} />
    </div>
  );
}
