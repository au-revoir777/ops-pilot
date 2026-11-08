"use client";

// Honest states (UI prompt section 8): loading, empty, error, degraded.
// Every data-bearing component uses these instead of rolling its own.
import { AlertTriangle, Inbox, RotateCw, TriangleAlert } from "lucide-react";
import type * as React from "react";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { describeError } from "@/lib/api/errors";
import { cn } from "@/lib/utils";
import { CopyButton } from "./copy-button";

export function LoadingRows({ rows = 3, className, label = "Loading" }: { rows?: number; className?: string; label?: string }) {
  return (
    <div role="status" aria-label={label} className={cn("space-y-2", className)}>
      {Array.from({ length: rows }, (_, i) => (
        <Skeleton key={i} className="h-6 w-full" />
      ))}
      <span className="sr-only">{label}…</span>
    </div>
  );
}

export function EmptyState({
  title,
  children,
  action,
  className,
}: {
  title: string;
  children?: React.ReactNode;
  action?: React.ReactNode;
  className?: string;
}) {
  return (
    <div className={cn("flex flex-col items-center gap-2 rounded-md border border-dashed px-4 py-6 text-center", className)}>
      <Inbox className="size-5 text-muted-foreground" aria-hidden />
      <p className="text-sm font-medium">{title}</p>
      {children ? <div className="max-w-md text-xs text-muted-foreground">{children}</div> : null}
      {action}
    </div>
  );
}

export function ErrorState({
  error,
  onRetry,
  className,
  compact = false,
}: {
  error: unknown;
  onRetry?: () => void;
  className?: string;
  compact?: boolean;
}) {
  const info = describeError(error);
  return (
    <div
      role="alert"
      className={cn(
        "flex gap-3 rounded-md border border-status-down/50 bg-status-down/5 p-3 text-sm",
        compact && "p-2 text-xs",
        className,
      )}
    >
      <AlertTriangle className="mt-0.5 size-4 shrink-0 text-status-down-text" aria-hidden />
      <div className="min-w-0 flex-1 space-y-1">
        <p className="font-medium">{info.title}</p>
        <p className="text-muted-foreground">{info.detail}</p>
        <dl className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground">
          {info.dependency ? (
            <div className="flex gap-1">
              <dt>Dependency:</dt>
              <dd className="text-foreground">{info.dependency}</dd>
            </div>
          ) : null}
          <div className="flex gap-1">
            <dt>Code:</dt>
            <dd className="font-mono text-foreground">{info.code}</dd>
          </div>
          {info.requestId ? (
            <div className="flex items-center gap-1">
              <dt>Correlation ID:</dt>
              <dd className="font-mono text-foreground">{info.requestId}</dd>
              <CopyButton value={info.requestId} label="Copy correlation ID" />
            </div>
          ) : null}
        </dl>
      </div>
      {onRetry ? (
        <Button variant="outline" size="sm" onClick={onRetry} className="self-start">
          <RotateCw /> Retry
        </Button>
      ) : null}
    </div>
  );
}

/** Partial data: names exactly which source is missing. */
export function DegradedBanner({
  sources,
  children,
  className,
}: {
  sources: string[];
  children?: React.ReactNode;
  className?: string;
}) {
  if (sources.length === 0) return null;
  return (
    <div
      role="status"
      className={cn(
        "flex items-start gap-2 rounded-md border border-status-degraded/60 bg-status-degraded/10 px-3 py-2 text-sm",
        className,
      )}
    >
      <TriangleAlert className="mt-0.5 size-4 shrink-0 text-status-degraded-foreground dark:text-status-degraded" aria-hidden />
      <div>
        <p>
          <span className="font-medium">Degraded:</span>{" "}
          {sources.map((s, i) => (
            <span key={s}>
              {i > 0 ? ", " : null}
              <code className="font-mono text-xs">{s}</code>
            </span>
          ))}
        </p>
        {children ? <div className="text-xs text-muted-foreground">{children}</div> : null}
      </div>
    </div>
  );
}
