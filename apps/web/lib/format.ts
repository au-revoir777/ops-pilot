// Formatting for durations, numbers and timestamps. Missing values render as an
// em dash, never as zero: an absent metric is not a healthy metric.

export const MISSING = "—";

export function formatMs(ms: number | null | undefined): string {
  if (ms == null || !Number.isFinite(ms)) return MISSING;
  if (ms < 1) return "<1 ms";
  if (ms < 1000) return `${Math.round(ms)} ms`;
  if (ms < 60_000) return `${(ms / 1000).toFixed(ms < 10_000 ? 2 : 1)} s`;
  const minutes = Math.floor(ms / 60_000);
  const seconds = Math.round((ms % 60_000) / 1000);
  return `${minutes}m ${seconds}s`;
}

export function formatSeconds(s: number | null | undefined): string {
  return s == null ? MISSING : formatMs(s * 1000);
}

export function formatPercent(ratio: number | null | undefined, digits = 1): string {
  if (ratio == null || !Number.isFinite(ratio)) return MISSING;
  const pct = ratio * 100;
  if (pct > 0 && pct < 0.1) return "<0.1%";
  return `${pct.toFixed(digits)}%`;
}

export function formatRate(rps: number | null | undefined): string {
  if (rps == null || !Number.isFinite(rps)) return MISSING;
  return `${rps < 10 ? rps.toFixed(2) : rps.toFixed(1)} req/s`;
}

export function formatConfidence(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return MISSING;
  return `${Math.round(value * 100)}%`;
}

export function formatTimestamp(iso: string | null | undefined): string {
  if (!iso) return MISSING;
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return MISSING;
  return d.toLocaleString(undefined, {
    year: "numeric",
    month: "short",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

export function formatClock(iso: string | Date | null | undefined): string {
  if (!iso) return MISSING;
  const d = typeof iso === "string" ? new Date(iso) : iso;
  if (Number.isNaN(d.getTime())) return MISSING;
  return d.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

export function formatAge(iso: string | null | undefined, now: Date = new Date()): string {
  if (!iso) return MISSING;
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return MISSING;
  const seconds = Math.max(0, Math.round((now.getTime() - then) / 1000));
  if (seconds < 60) return `${seconds}s ago`;
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 48) return `${hours}h ago`;
  return `${Math.round(hours / 24)}d ago`;
}

export function shortId(id: string): string {
  return id.slice(0, 8);
}

/** Rule identifiers like deployment_db_regression become "Deployment db regression". */
export function humanize(identifier: string | null | undefined): string {
  if (!identifier) return MISSING;
  const text = identifier.replace(/[_-]+/g, " ").trim();
  return text.charAt(0).toUpperCase() + text.slice(1);
}
