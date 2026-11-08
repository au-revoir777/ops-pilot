// One error type for everything the API client can fail with, and the mapping
// from error codes to messages a person can act on (UI prompt section 8).

export type ApiErrorKind = "http" | "network" | "timeout" | "contract";

export class ApiError extends Error {
  readonly kind: ApiErrorKind;
  readonly code: string;
  readonly status: number | null;
  readonly requestId: string;
  readonly path: string;

  constructor(opts: {
    kind: ApiErrorKind;
    code: string;
    message: string;
    status: number | null;
    requestId: string;
    path: string;
  }) {
    super(opts.message);
    this.name = "ApiError";
    this.kind = opts.kind;
    this.code = opts.code;
    this.status = opts.status;
    this.requestId = opts.requestId;
    this.path = opts.path;
  }
}

export function isApiError(error: unknown): error is ApiError {
  return error instanceof ApiError;
}

type Described = { title: string; detail: string; dependency?: string };

const BY_CODE: Record<string, Described> = {
  metrics_unavailable: {
    title: "Metrics are unavailable",
    detail: "Prometheus did not answer. Charts and health values cannot be shown.",
    dependency: "Prometheus",
  },
  logs_unavailable: {
    title: "Logs are unavailable",
    detail: "Loki did not answer. Log evidence is missing from this view.",
    dependency: "Loki",
  },
  rag_unavailable: {
    title: "Knowledge base is unavailable",
    detail: "Runbooks and postmortems could not be searched.",
    dependency: "PostgreSQL / pgvector",
  },
  mcp_unavailable: {
    title: "Operational tools are unavailable",
    detail: "The MCP server did not answer, so no live telemetry could be read.",
    dependency: "MCP server",
  },
  llm_unavailable: {
    title: "Language model is unavailable",
    detail: "The optional LLM summary is missing. Rule-based results are unaffected.",
    dependency: "LLM provider",
  },
  INVESTIGATION_TIMEOUT: {
    title: "The investigation timed out",
    detail: "The agent did not finish within its time budget. It is marked failed; try again.",
    dependency: "Agent",
  },
  AGENT_FAILED: {
    title: "The agent failed",
    detail: "The investigation stopped with an internal error. Check the API logs with the request ID.",
    dependency: "Agent",
  },
  LAB_DISABLED: {
    title: "The incident lab is disabled",
    detail: "Set ENABLE_INCIDENT_LAB=true on the API to use failure injection with the demo services.",
  },
  LAB_TARGET_UNAVAILABLE: {
    title: "The demo service did not respond",
    detail: "The failure mode could not be changed. Is the demo workload running?",
    dependency: "Demo workload",
  },
  VALIDATION_ERROR: {
    title: "The request was rejected",
    detail: "Some input was invalid. Check the fields and try again.",
  },
  NOT_FOUND: { title: "Not found", detail: "Nothing exists at this address." },
  DATABASE_UNAVAILABLE: {
    title: "The database is unavailable",
    detail: "The API cannot reach PostgreSQL.",
    dependency: "PostgreSQL",
  },
  CONTRACT_ERROR: {
    title: "Unexpected response from the API",
    detail: "The response did not match the expected shape, so it was not displayed. This is a bug.",
    dependency: "API",
  },
  NETWORK_ERROR: {
    title: "The API is unreachable",
    detail: "The request did not reach the OpsPilot API. Is it running?",
    dependency: "API",
  },
  API_UNREACHABLE: {
    title: "The OpsPilot API is unreachable",
    detail: "The web server could not reach the API. Is the api container running?",
    dependency: "API",
  },
  TIMEOUT: {
    title: "The request timed out",
    detail: "The API took too long to answer.",
    dependency: "API",
  },
  INTERNAL_ERROR: {
    title: "The API hit an internal error",
    detail: "Something failed on the server. Check the API logs with the request ID.",
    dependency: "API",
  },
};

export function describeError(error: unknown): Described & { code: string; requestId?: string } {
  if (isApiError(error)) {
    const known = BY_CODE[error.code] ?? BY_CODE[error.code.toLowerCase()];
    if (known) return { ...known, code: error.code, requestId: error.requestId };
    return {
      title: error.status ? `Request failed (${error.status})` : "Request failed",
      detail: error.message,
      code: error.code,
      requestId: error.requestId,
    };
  }
  return {
    title: "Something went wrong",
    detail: error instanceof Error ? error.message : String(error),
    code: "UNKNOWN",
  };
}

/** Maps a telemetry source name from a degraded response to a code above. */
export function sourceCode(source: string): string {
  const s = source.toLowerCase();
  if (s.includes("prometheus") || s.includes("metric")) return "metrics_unavailable";
  if (s.includes("loki") || s.includes("log")) return "logs_unavailable";
  if (s.includes("knowledge") || s.includes("rag")) return "rag_unavailable";
  if (s.includes("mcp")) return "mcp_unavailable";
  if (s.includes("llm")) return "llm_unavailable";
  return s;
}
