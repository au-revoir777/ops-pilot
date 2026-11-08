import { CircleCheck, CircleHelp, CircleX, Loader2, TriangleAlert } from "lucide-react";
import { Badge, type BadgeVariant } from "@/components/ui/badge";
import { cn } from "@/lib/utils";

// Status colors are fixed across palettes and always paired with an icon and a
// word, so the meaning never depends on color alone.
type Status = "healthy" | "degraded" | "down" | "unknown" | "running";

const NORMALIZE: Record<string, Status> = {
  healthy: "healthy",
  ok: "healthy",
  up: "healthy",
  completed: "healthy",
  degraded: "degraded",
  partial: "degraded",
  empty: "degraded",
  warning: "degraded",
  down: "down",
  unhealthy: "down",
  failed: "down",
  error: "down",
  unavailable: "down",
  running: "running",
  pending: "running",
};

const META: Record<Status, { variant: BadgeVariant; icon: typeof CircleCheck; label: string }> = {
  healthy: { variant: "healthy", icon: CircleCheck, label: "Healthy" },
  degraded: { variant: "degraded", icon: TriangleAlert, label: "Degraded" },
  down: { variant: "down", icon: CircleX, label: "Down" },
  unknown: { variant: "unknown", icon: CircleHelp, label: "Unknown" },
  running: { variant: "info", icon: Loader2, label: "Running" },
};

export function normalizeStatus(value: string | null | undefined): Status {
  return (value && NORMALIZE[value.toLowerCase()]) || "unknown";
}

export function StatusBadge({
  status,
  label,
  className,
}: {
  status: string | null | undefined;
  /** Overrides the default word, e.g. the raw "completed". */
  label?: string;
  className?: string;
}) {
  const s = normalizeStatus(status);
  const { variant, icon: Icon, label: word } = META[s];
  return (
    <Badge variant={variant} className={className} data-status={s}>
      <Icon aria-hidden className={cn(s === "running" && "animate-spin")} />
      {label ?? word}
    </Badge>
  );
}

export function StatusDot({ status, className }: { status: string | null | undefined; className?: string }) {
  const s = normalizeStatus(status);
  const color = {
    healthy: "bg-status-healthy",
    degraded: "bg-status-degraded",
    down: "bg-status-down",
    unknown: "bg-status-unknown",
    running: "bg-status-info",
  }[s];
  return <span aria-hidden className={cn("inline-block size-2 shrink-0 rounded-full", color, className)} />;
}
