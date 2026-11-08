// Liveness for the container health check. Served by Next.js itself, so it
// stays up when the backend API is down (that is shown in the UI, not here).
// Lives under /api/healthz but is matched before the /api/* proxy rewrite.
export const dynamic = "force-dynamic";

export function GET() {
  return Response.json({ status: "ok", service: "opspilot-web" });
}
