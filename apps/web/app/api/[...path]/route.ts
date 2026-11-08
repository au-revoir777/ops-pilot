// Same-origin proxy to the FastAPI service. The browser only ever calls this
// server, so there is no CORS and the API address stays server-side.
// A route handler (not a next.config rewrite) because rewrites are fixed at
// build time, while API_INTERNAL_URL is runtime configuration (DECISIONS D-035).
import type { NextRequest } from "next/server";

export const dynamic = "force-dynamic";

const FORWARD_REQUEST = ["accept", "content-type", "x-request-id"];
const FORWARD_RESPONSE = ["content-type", "x-request-id", "x-total-count"];
// Investigations with wait=true run the whole agent before answering.
const TIMEOUT_MS = 190_000;

// Server-side only (no NEXT_PUBLIC_ prefix): the browser never sees the key.
function apiKey(): string | undefined {
  return process.env.OPSPILOT_API_KEY || undefined;
}

function apiBase(): string {
  return (process.env.API_INTERNAL_URL ?? "http://127.0.0.1:8000").replace(/\/$/, "");
}

async function proxy(request: NextRequest, { params }: { params: Promise<{ path: string[] }> }) {
  const { path } = await params;
  // Each segment is re-encoded, so ".." or encoded slashes cannot escape /api.
  const target = `${apiBase()}/api/${path.map(encodeURIComponent).join("/")}${request.nextUrl.search}`;
  const headers = new Headers();
  for (const name of FORWARD_REQUEST) {
    const value = request.headers.get(name);
    if (value) headers.set(name, value);
  }
  // Any X-API-Key a browser sends is dropped above; only the server's own key is used.
  const key = apiKey();
  if (key) headers.set("x-api-key", key);
  try {
    const upstream = await fetch(target, {
      method: request.method,
      headers,
      body: request.method === "GET" || request.method === "HEAD" ? undefined : await request.arrayBuffer(),
      cache: "no-store",
      redirect: "manual",
      signal: AbortSignal.timeout(TIMEOUT_MS),
    });
    const responseHeaders = new Headers({ "cache-control": "no-store" });
    for (const name of FORWARD_RESPONSE) {
      const value = upstream.headers.get(name);
      if (value) responseHeaders.set(name, value);
    }
    return new Response(upstream.body, { status: upstream.status, headers: responseHeaders });
  } catch (error) {
    const timedOut = error instanceof DOMException && error.name === "TimeoutError";
    return Response.json(
      {
        error: {
          code: timedOut ? "TIMEOUT" : "API_UNREACHABLE",
          message: timedOut ? "The OpsPilot API did not answer in time" : "The OpsPilot API is unreachable",
          request_id: request.headers.get("x-request-id"),
        },
      },
      { status: timedOut ? 504 : 502 },
    );
  }
}

export { proxy as GET, proxy as POST, proxy as PATCH, proxy as PUT, proxy as DELETE };
