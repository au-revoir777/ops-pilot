// Zod schemas for every API response. They mirror the FastAPI models in
// apps/api/app/routes/* and apps/api/app/agents/models.py. A response that does
// not match is surfaced as a CONTRACT_ERROR (lib/api/errors.ts), never ignored.
import { z } from "zod";

const nullableString = z.string().nullable();
const nullableNumber = z.number().nullable();
const record = z.record(z.string(), z.unknown());

// ---------- system ----------

export const publicConfigSchema = z.object({
  environment: z.string(),
  version: z.string(),
  read_only: z.boolean(),
  llm_provider: z.string(),
  llm_model: nullableString,
  incident_lab_enabled: z.boolean(),
  grafana_url: nullableString,
});
export type PublicConfig = z.infer<typeof publicConfigSchema>;

export const dependencyHealthSchema = z.object({
  status: z.enum(["ok", "degraded", "down"]),
  timestamp: z.string(),
  checks: z.record(z.string(), z.string()),
});
export type DependencyHealth = z.infer<typeof dependencyHealthSchema>;

export const healthStatusSchema = z.enum(["healthy", "degraded", "down", "unknown"]);
export type HealthStatus = z.infer<typeof healthStatusSchema>;

const dependencyStatusSchema = z.object({
  service: z.string(),
  status: z.string(),
  error_rate: nullableNumber.optional(),
  p95_latency_ms: nullableNumber.optional(),
});

export const serviceInfoSchema = z.object({
  name: z.string(),
  project: nullableString,
  sources: z.array(z.enum(["registered", "telemetry"])),
  health: nullableString.optional(),
  p95_latency_ms: nullableNumber.optional(),
  error_rate: nullableNumber.optional(),
  request_rate: nullableNumber.optional(),
  version: nullableString.optional(),
  reasons: z.array(z.string()).default([]),
  dependency_status: z.array(dependencyStatusSchema).default([]),
});
export type ServiceInfo = z.infer<typeof serviceInfoSchema>;

export const servicesResponseSchema = z.object({
  services: z.array(serviceInfoSchema),
  telemetry_status: z.enum(["ok", "unavailable"]),
});
export type ServicesResponse = z.infer<typeof servicesResponseSchema>;

// ---------- telemetry ----------

export const metricRanges = ["15m", "30m", "1h", "6h"] as const;
export type MetricRange = (typeof metricRanges)[number];
export const seriesNames = [
  "request_rate",
  "error_rate",
  "p50_latency_s",
  "p95_latency_s",
  "p99_latency_s",
] as const;
export type SeriesName = (typeof seriesNames)[number];

export const pointSchema = z.object({ timestamp: z.string(), value: nullableNumber });
export type Point = z.infer<typeof pointSchema>;

export const metricsResponseSchema = z.object({
  service: z.string(),
  range: z.enum(metricRanges),
  status: z.enum(["ok", "partial", "unavailable"]),
  errors: z.array(z.string()),
  series: z.record(z.string(), z.array(pointSchema)),
});
export type MetricsResponse = z.infer<typeof metricsResponseSchema>;

export const deploymentSchema = z.object({
  version: z.string(),
  deployment_time: z.string(),
  last_seen: z.string().optional(),
  status: z.string().optional(),
  deployed_before_window: z.boolean().optional(),
});
export type Deployment = z.infer<typeof deploymentSchema>;

export const deploymentsResponseSchema = z.object({
  service: z.string(),
  status: z.string(),
  errors: z.array(record),
  deployments: z.array(deploymentSchema),
});
export type DeploymentsResponse = z.infer<typeof deploymentsResponseSchema>;

// ---------- incidents ----------

export const severitySchema = z.enum(["SEV1", "SEV2", "SEV3", "SEV4"]);
export type Severity = z.infer<typeof severitySchema>;
export const incidentStatusSchema = z.enum([
  "open",
  "investigating",
  "mitigated",
  "resolved",
  "closed",
]);

export const incidentSchema = z.object({
  id: z.string(),
  title: z.string(),
  description: nullableString,
  status: incidentStatusSchema,
  severity: severitySchema,
  service_name: nullableString,
  resolved_at: nullableString,
  created_at: z.string(),
  updated_at: z.string(),
});
export type Incident = z.infer<typeof incidentSchema>;
export const incidentListSchema = z.array(incidentSchema);

// ---------- agent report ----------

export const observationSchema = z.object({
  id: z.string(),
  kind: z.string(),
  statement: z.string(),
  source: z.string(),
  at: nullableString.optional(),
  signals: z.array(z.string()).default([]),
  data: record.default({}),
});
export type Observation = z.infer<typeof observationSchema>;

export const retrievedEvidenceSchema = z.object({
  id: z.string(),
  citation: z.string(),
  title: z.string(),
  section: nullableString,
  score: z.number(),
  excerpt: z.string(),
  flags: z.array(z.string()).default([]),
});
export type RetrievedEvidence = z.infer<typeof retrievedEvidenceSchema>;

export const toolCallSchema = z.object({
  tool: z.string(),
  arguments: record,
  status: z.string(),
  duration_ms: z.number(),
  error: nullableString.optional(),
  result_summary: nullableString.optional(),
  result: record.nullable().optional(),
});
export type ToolCall = z.infer<typeof toolCallSchema>;

export const confidenceBreakdownSchema = z.object({
  base: z.number(),
  temporal: z.number(),
  metric: z.number(),
  log: z.number(),
  deployment: z.number(),
  knowledge: z.number(),
  contradictions: z.number(),
  coverage_factor: z.number(),
  value: z.number(),
});
export type ConfidenceBreakdown = z.infer<typeof confidenceBreakdownSchema>;

export const hypothesisSchema = z.object({
  id: z.string(),
  cause: z.string(),
  statement: z.string(),
  supporting: z.array(z.string()).default([]),
  contradicting: z.array(z.string()).default([]),
  contradictions: z.array(z.string()).default([]),
  confidence: confidenceBreakdownSchema.nullable().optional(),
  status: z.enum(["supported", "weak", "rejected"]),
});
export type Hypothesis = z.infer<typeof hypothesisSchema>;

export const traceStepSchema = z.object({
  node: z.string(),
  duration_ms: z.number(),
  summary: z.string(),
});
export type TraceStep = z.infer<typeof traceStepSchema>;

export const recommendationSchema = z.object({
  action: z.string(),
  rationale: z.string(),
  requires_human_approval: z.boolean(),
  references: z.array(z.string()).default([]),
});
export type Recommendation = z.infer<typeof recommendationSchema>;

export const reportSchema = z.object({
  query: z.string(),
  service: nullableString,
  symptoms: z.array(z.string()).default([]),
  window_minutes: z.number(),
  observations: z.array(observationSchema),
  evidence: z.array(retrievedEvidenceSchema),
  hypotheses: z.array(hypothesisSchema),
  conclusion: z.string(),
  root_cause: nullableString,
  confidence: z.number(),
  confidence_breakdown: confidenceBreakdownSchema.nullable(),
  recommendations: z.array(recommendationSchema),
  missing_evidence: z.array(z.string()),
  tool_calls: z.array(toolCallSchema),
  trace: z.array(traceStepSchema),
  iterations: z.number(),
  llm: record.default({}),
  completed: z.boolean().default(true),
});
export type Report = z.infer<typeof reportSchema>;

// ---------- investigations ----------

export const investigationStatusSchema = z.enum([
  "pending",
  "running",
  "paused",
  "completed",
  "failed",
]);
export type InvestigationStatus = z.infer<typeof investigationStatusSchema>;

export const investigationSummarySchema = z.object({
  id: z.string(),
  incident_id: z.string(),
  status: investigationStatusSchema,
  query: nullableString,
  service: nullableString,
  root_cause: nullableString,
  diagnosis: nullableString,
  confidence: nullableNumber,
  latency_ms: nullableNumber,
  summary: nullableString,
  started_at: nullableString,
  completed_at: nullableString,
  created_at: z.string(),
  updated_at: z.string(),
});
export type InvestigationSummary = z.infer<typeof investigationSummarySchema>;
export const investigationListItemSchema = investigationSummarySchema.extend({
  severity: severitySchema.nullable().optional(),
});
export type InvestigationListItem = z.infer<typeof investigationListItemSchema>;
export const investigationListSchema = z.array(investigationListItemSchema);

export const investigationEventSchema = z.object({
  sequence: z.number(),
  event_type: z.string(),
  message: z.string(),
  details: record.nullable(),
  created_at: z.string(),
});
export type InvestigationEvent = z.infer<typeof investigationEventSchema>;

export const investigationDetailSchema = investigationSummarySchema.extend({
  report: reportSchema.nullable(),
  events: z.array(investigationEventSchema),
});
export type InvestigationDetail = z.infer<typeof investigationDetailSchema>;

// ---------- lab ----------

export const failureModes = ["none", "latency", "errors", "db"] as const;
export type FailureMode = (typeof failureModes)[number];

export const labServiceSchema = z.object({
  name: z.string(),
  mode: z.enum(failureModes).nullable(),
  reachable: z.boolean(),
});
export type LabService = z.infer<typeof labServiceSchema>;

export const labStatusSchema = z.object({
  enabled: z.boolean(),
  services: z.array(labServiceSchema),
});
export type LabStatus = z.infer<typeof labStatusSchema>;

export const trafficAcceptedSchema = z.object({ target: z.string(), requests: z.number() });

// ---------- replay ----------

export const replayCaseSchema = z.object({
  id: z.string(),
  question: z.string(),
  expected_service: nullableString,
  expected_root_cause: nullableString,
  unavailable_sources: z.array(z.string()),
});
export type ReplayCase = z.infer<typeof replayCaseSchema>;
export const replayCaseListSchema = z.array(replayCaseSchema);

export const replayResultSchema = z.object({
  case: replayCaseSchema,
  match: z.boolean(),
  service_match: z.boolean(),
  report: reportSchema,
});
export type ReplayResult = z.infer<typeof replayResultSchema>;

// ---------- errors ----------

export const errorBodySchema = z.object({
  error: z.object({
    code: z.string(),
    message: z.string(),
    request_id: nullableString.optional(),
  }),
});
