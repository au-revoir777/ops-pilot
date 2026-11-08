// The single API client. Every request gets an X-Request-ID (the API echoes it
// and logs it), a timeout, and a zod-validated response. Errors are normalized
// to ApiError so components can map them to messages.
import type { z } from "zod";
import { ApiError } from "./errors";
import * as s from "./schemas";

// Same-origin by default: next.config.ts proxies /api/* to the FastAPI service.
const BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? "";
const DEFAULT_TIMEOUT_MS = 20_000;
const SLOW_TIMEOUT_MS = 60_000;
// An investigation runs the whole agent before answering (wait=true).
const INVESTIGATION_TIMEOUT_MS = 180_000;

let lastRequestId: string | null = null;

export type InvestigationQuery = {
  status?: s.InvestigationStatus;
  service?: string;
  severity?: s.Severity;
  q?: string;
  since?: string;
  until?: string;
  sort?: "created_at" | "latency_ms" | "confidence";
  order?: "asc" | "desc";
  limit?: number;
  offset?: number;
};

/** The correlation ID of the most recent API request (command palette: copy). */
export function getLastRequestId(): string | null {
  return lastRequestId;
}

export function newRequestId(): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) return crypto.randomUUID();
  return `${Date.now().toString(16)}-${Math.random().toString(16).slice(2)}`;
}

type RequestOptions = {
  method?: "GET" | "POST" | "PATCH";
  body?: unknown;
  timeoutMs?: number;
  signal?: AbortSignal;
};

export async function request<T>(
  path: string,
  schema: z.ZodType<T>,
  { method = "GET", body, timeoutMs = DEFAULT_TIMEOUT_MS, signal }: RequestOptions = {},
): Promise<{ data: T; requestId: string; headers: Headers }> {
  const requestId = newRequestId();
  lastRequestId = requestId;
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort("timeout"), timeoutMs);
  const onAbort = () => controller.abort(signal?.reason);
  signal?.addEventListener("abort", onAbort);

  let response: Response;
  try {
    response = await fetch(`${BASE_URL}${path}`, {
      method,
      headers: {
        Accept: "application/json",
        "X-Request-ID": requestId,
        ...(body !== undefined ? { "Content-Type": "application/json" } : {}),
      },
      body: body !== undefined ? JSON.stringify(body) : undefined,
      signal: controller.signal,
      cache: "no-store",
    });
  } catch (error) {
    const timedOut = controller.signal.reason === "timeout";
    if (!timedOut && signal?.aborted) throw error; // the caller cancelled; not an API failure
    throw new ApiError({
      kind: timedOut ? "timeout" : "network",
      code: timedOut ? "TIMEOUT" : "NETWORK_ERROR",
      message: timedOut ? `No answer within ${Math.round(timeoutMs / 1000)}s` : "Network error",
      status: null,
      requestId,
      path,
    });
  } finally {
    clearTimeout(timer);
    signal?.removeEventListener("abort", onAbort);
  }

  const echoed = response.headers.get("X-Request-ID") ?? requestId;
  let payload: unknown = null;
  try {
    payload = await response.json();
  } catch {
    payload = null;
  }

  if (!response.ok) {
    const parsed = s.errorBodySchema.safeParse(payload);
    const validation = response.status === 422 && !parsed.success;
    throw new ApiError({
      kind: "http",
      code: parsed.success ? parsed.data.error.code : validation ? "VALIDATION_ERROR" : `HTTP_${response.status}`,
      message: parsed.success ? parsed.data.error.message : response.statusText || "Request failed",
      status: response.status,
      requestId: (parsed.success && parsed.data.error.request_id) || echoed,
      path,
    });
  }

  const result = schema.safeParse(payload);
  if (!result.success) {
    console.error("API contract error", { path, requestId: echoed, issues: result.error.issues });
    throw new ApiError({
      kind: "contract",
      code: "CONTRACT_ERROR",
      message: `Response from ${path} did not match the expected schema`,
      status: response.status,
      requestId: echoed,
      path,
    });
  }
  return { data: result.data, requestId: echoed, headers: response.headers };
}

const get = async <T>(path: string, schema: z.ZodType<T>, signal?: AbortSignal, timeoutMs = DEFAULT_TIMEOUT_MS) =>
  (await request(path, schema, { signal, timeoutMs })).data;

function query(params: Record<string, string | number | boolean | undefined | null>): string {
  const search = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) if (v != null && v !== "") search.set(k, String(v));
  const text = search.toString();
  return text ? `?${text}` : "";
}

export const api = {
  config: (signal?: AbortSignal) => get("/api/config", s.publicConfigSchema, signal),
  health: async (signal?: AbortSignal) => {
    // 503 still carries the dependency report; surface it instead of an error.
    try {
      return await get("/api/health", s.dependencyHealthSchema, signal);
    } catch (error) {
      if (error instanceof ApiError && error.status === 503) {
        return {
          status: "down" as const,
          timestamp: new Date().toISOString(),
          checks: { database: "down" },
        };
      }
      throw error;
    }
  },
  // MCP-backed reads (one Prometheus query per series or service) get a longer budget.
  services: (health = true, signal?: AbortSignal) =>
    get(`/api/services${query({ health })}`, s.servicesResponseSchema, signal, SLOW_TIMEOUT_MS),
  metrics: (service: string, range: s.MetricRange, signal?: AbortSignal) =>
    get(`/api/metrics${query({ service, range })}`, s.metricsResponseSchema, signal, SLOW_TIMEOUT_MS),
  deployments: (service: string, hours = 6, signal?: AbortSignal) =>
    get(
      `/api/services/${encodeURIComponent(service)}/deployments${query({ hours })}`,
      s.deploymentsResponseSchema,
      signal,
      SLOW_TIMEOUT_MS,
    ),
  incidents: (signal?: AbortSignal) => get("/api/incidents", s.incidentListSchema, signal),
  incident: (id: string, signal?: AbortSignal) =>
    get(`/api/incidents/${encodeURIComponent(id)}`, s.incidentSchema, signal),
  incidentInvestigations: (id: string, signal?: AbortSignal) =>
    get(`/api/incidents/${encodeURIComponent(id)}/investigations`, s.investigationListSchema, signal),
  investigations: async (params: InvestigationQuery = {}, signal?: AbortSignal) => {
    const { data, headers } = await request(`/api/investigations${query(params)}`, s.investigationListSchema, { signal });
    const total = Number(headers.get("X-Total-Count"));
    return { items: data, total: Number.isFinite(total) && headers.has("X-Total-Count") ? total : data.length };
  },
  investigation: (id: string, signal?: AbortSignal) =>
    get(`/api/investigations/${encodeURIComponent(id)}`, s.investigationDetailSchema, signal),
  startInvestigation: (body: {
    query?: string;
    incident_id?: string;
    service?: string;
    window_minutes?: number;
    wait?: boolean;
  }) =>
    request("/api/investigations", s.investigationDetailSchema, {
      method: "POST",
      body,
      timeoutMs: body.wait === false ? DEFAULT_TIMEOUT_MS : INVESTIGATION_TIMEOUT_MS,
    }),
  lab: (signal?: AbortSignal) => get("/api/lab", s.labStatusSchema, signal),
  setFailure: (service: string, mode: s.FailureMode) =>
    request("/api/lab/failure", s.labServiceSchema, { method: "POST", body: { service, mode } }),
  sendTraffic: (requests: number) =>
    request("/api/lab/traffic", s.trafficAcceptedSchema, { method: "POST", body: { requests } }),
  replays: (signal?: AbortSignal) => get("/api/replays", s.replayCaseListSchema, signal),
  replay: (caseId: string) =>
    request(`/api/replays/${encodeURIComponent(caseId)}`, s.replayResultSchema, {
      method: "POST",
      timeoutMs: 60_000,
    }),
};
