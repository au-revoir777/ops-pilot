// Redacts values that look like credentials before log excerpts or tool output
// are rendered (UI prompt section 10). Defence in depth: the backend should
// never return secrets, but logs are untrusted input.

const PATTERNS: [RegExp, string][] = [
  // key=value / "key": "value" pairs whose key names a secret
  [
    /((?:pass(?:word|wd)?|secret|token|api[_-]?key|access[_-]?key|auth(?:orization)?|credential|private[_-]?key)["']?\s*[:=]\s*["']?)([^\s"',;&]+)/gi,
    "$1[REDACTED]",
  ],
  [/\b(Bearer|Basic)\s+[A-Za-z0-9._~+/=-]{8,}/g, "$1 [REDACTED]"],
  // user:password@ in connection strings
  [/(\b[a-z][a-z0-9+.-]*:\/\/[^:\s/@]+:)[^@\s]+@/gi, "$1[REDACTED]@"],
  [/\b(sk|pk|rk)-[A-Za-z0-9_-]{16,}\b/g, "[REDACTED]"],
  [/\bAKIA[0-9A-Z]{16}\b/g, "[REDACTED]"],
  [/\bgh[pousr]_[A-Za-z0-9]{20,}\b/g, "[REDACTED]"],
  [/\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b/g, "[REDACTED]"],
];

export function redact(text: string): string {
  return PATTERNS.reduce((acc, [pattern, replacement]) => acc.replace(pattern, replacement), text);
}

/** Redacts every string inside a JSON-like value, keeping its shape. */
export function redactValue<T>(value: T): T {
  if (typeof value === "string") return redact(value) as T;
  if (Array.isArray(value)) return value.map(redactValue) as T;
  if (value && typeof value === "object") {
    return Object.fromEntries(
      Object.entries(value as Record<string, unknown>).map(([k, v]) => [
        k,
        /pass|secret|token|api[_-]?key|authorization|credential/i.test(k) && typeof v === "string"
          ? "[REDACTED]"
          : redactValue(v),
      ]),
    ) as T;
  }
  return value;
}
