import type * as React from "react";
import { redactValue } from "@/lib/redact";

// A tiny JSON highlighter built from React elements (no HTML strings), so raw
// tool output can never inject markup. Used instead of Shiki: the payloads are
// small and only JSON needs highlighting (DECISIONS D-035).

function render(value: unknown, indent: number, key: string): React.ReactNode {
  const pad = "  ".repeat(indent);
  const padInner = "  ".repeat(indent + 1);
  if (value === null) return <span className="text-muted-foreground">null</span>;
  if (typeof value === "string") return <span className="text-foreground">{JSON.stringify(value)}</span>;
  if (typeof value === "number") return <span className="font-semibold text-primary">{String(value)}</span>;
  if (typeof value === "boolean") return <span className="font-semibold text-primary">{String(value)}</span>;
  if (Array.isArray(value)) {
    if (value.length === 0) return "[]";
    return (
      <>
        {"[\n"}
        {value.map((v, i) => (
          <span key={`${key}.${i}`}>
            {padInner}
            {render(v, indent + 1, `${key}.${i}`)}
            {i < value.length - 1 ? ",\n" : "\n"}
          </span>
        ))}
        {pad}
        {"]"}
      </>
    );
  }
  if (typeof value === "object") {
    const entries = Object.entries(value as Record<string, unknown>);
    if (entries.length === 0) return "{}";
    return (
      <>
        {"{\n"}
        {entries.map(([k, v], i) => (
          <span key={`${key}.${k}`}>
            {padInner}
            <span className="text-muted-foreground">{JSON.stringify(k)}</span>
            {": "}
            {render(v, indent + 1, `${key}.${k}`)}
            {i < entries.length - 1 ? ",\n" : "\n"}
          </span>
        ))}
        {pad}
        {"}"}
      </>
    );
  }
  return String(value);
}

export function JsonView({ value, label }: { value: unknown; label: string }) {
  return (
    <pre
      aria-label={label}
      tabIndex={0}
      className="max-h-80 overflow-auto rounded-md border bg-muted/40 p-2 font-mono text-[11px] leading-relaxed"
    >
      <code>{render(redactValue(value), 0, "$")}</code>
    </pre>
  );
}
