import type { Incident } from "./api/schemas";

/** Opens the investigation form pre-filled from an incident. */
export function investigateHref(incident: Pick<Incident, "id" | "title" | "service_name">) {
  const params = new URLSearchParams({ new: "1", incident: incident.id, q: `Investigate: ${incident.title}` });
  if (incident.service_name) params.set("service", incident.service_name);
  return `/investigations?${params.toString()}`;
}

export function newInvestigationHref(query: string, service?: string | null) {
  const params = new URLSearchParams({ new: "1", q: query });
  if (service) params.set("service", service);
  return `/investigations?${params.toString()}`;
}
