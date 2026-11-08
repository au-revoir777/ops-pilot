"use client";

// TanStack Query hooks over lib/api. Polling intervals live here so pages stay
// declarative. Retries with backoff apply to GETs only (set in providers.tsx);
// mutations never retry.
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, type InvestigationQuery } from "@/lib/api/client";
import type { FailureMode, MetricRange } from "@/lib/api/schemas";

export const DASHBOARD_REFRESH_MS = 15_000;
export const INVESTIGATION_POLL_MS = Number(process.env.NEXT_PUBLIC_INVESTIGATION_POLL_MS ?? 2_000);

export const keys = {
  config: ["config"] as const,
  health: ["health"] as const,
  services: ["services"] as const,
  metrics: (service: string, range: MetricRange) => ["metrics", service, range] as const,
  deployments: (service: string, hours: number) => ["deployments", service, hours] as const,
  incidents: ["incidents"] as const,
  incident: (id: string) => ["incident", id] as const,
  incidentInvestigations: (id: string) => ["incident", id, "investigations"] as const,
  investigations: (params: object) => ["investigations", params] as const,
  investigation: (id: string) => ["investigation", id] as const,
  lab: ["lab"] as const,
  replays: ["replays"] as const,
};

type Live = { refetchInterval?: number | false };

export function useConfig() {
  return useQuery({ queryKey: keys.config, queryFn: ({ signal }) => api.config(signal), staleTime: 60_000 });
}

export function useDependencyHealth({ refetchInterval = DASHBOARD_REFRESH_MS }: Live = {}) {
  return useQuery({ queryKey: keys.health, queryFn: ({ signal }) => api.health(signal), refetchInterval });
}

export function useServices({ refetchInterval = DASHBOARD_REFRESH_MS }: Live = {}) {
  return useQuery({
    queryKey: keys.services,
    queryFn: ({ signal }) => api.services(true, signal),
    refetchInterval,
  });
}

export function useMetrics(service: string | null, range: MetricRange, { refetchInterval = DASHBOARD_REFRESH_MS }: Live = {}) {
  return useQuery({
    queryKey: keys.metrics(service ?? "", range),
    queryFn: ({ signal }) => api.metrics(service!, range, signal),
    enabled: !!service,
    refetchInterval,
    placeholderData: (previous) => previous,
  });
}

export function useDeployments(service: string | null, hours = 6, { refetchInterval = DASHBOARD_REFRESH_MS }: Live = {}) {
  return useQuery({
    queryKey: keys.deployments(service ?? "", hours),
    queryFn: ({ signal }) => api.deployments(service!, hours, signal),
    enabled: !!service,
    refetchInterval,
  });
}

export function useIncidents({ refetchInterval = DASHBOARD_REFRESH_MS }: Live = {}) {
  return useQuery({ queryKey: keys.incidents, queryFn: ({ signal }) => api.incidents(signal), refetchInterval });
}

export function useIncident(id: string) {
  return useQuery({ queryKey: keys.incident(id), queryFn: ({ signal }) => api.incident(id, signal) });
}

export function useIncidentInvestigations(id: string) {
  return useQuery({
    queryKey: keys.incidentInvestigations(id),
    queryFn: ({ signal }) => api.incidentInvestigations(id, signal),
  });
}

export function useInvestigations(
  params: InvestigationQuery = {},
  { refetchInterval = false }: Live = {},
) {
  return useQuery({
    queryKey: keys.investigations(params),
    queryFn: ({ signal }) => api.investigations(params, signal),
    refetchInterval,
    placeholderData: (previous) => previous,
  });
}

/** Polls while the investigation is pending or running; stops once it settles. */
export function useInvestigation(id: string) {
  return useQuery({
    queryKey: keys.investigation(id),
    queryFn: ({ signal }) => api.investigation(id, signal),
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      return status === "pending" || status === "running" ? INVESTIGATION_POLL_MS : false;
    },
  });
}

export function useStartInvestigation() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: api.startInvestigation,
    retry: false,
    onSuccess: ({ data }) => {
      client.setQueryData(keys.investigation(data.id), data);
      void client.invalidateQueries({ queryKey: ["investigations"] });
    },
  });
}

export function useLab({ refetchInterval = 5_000 }: Live = {}) {
  return useQuery({ queryKey: keys.lab, queryFn: ({ signal }) => api.lab(signal), refetchInterval });
}

export function useSetFailure() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ service, mode }: { service: string; mode: FailureMode }) => api.setFailure(service, mode),
    retry: false,
    onSettled: () => {
      void client.invalidateQueries({ queryKey: keys.lab });
      void client.invalidateQueries({ queryKey: keys.services });
    },
  });
}

export function useSendTraffic() {
  return useMutation({ mutationFn: (requests: number) => api.sendTraffic(requests), retry: false });
}

export function useReplays() {
  return useQuery({ queryKey: keys.replays, queryFn: ({ signal }) => api.replays(signal), staleTime: 300_000 });
}

export function useReplay() {
  return useMutation({ mutationFn: (caseId: string) => api.replay(caseId), retry: false });
}
