// Real API payloads exported by scripts/export_fixtures.py (the agent replayed
// over recorded scenarios). Parsed with the production schemas, so a contract
// change in the backend fails these tests.
import { replayCaseListSchema, replayResultSchema, type Report } from "@/lib/api/schemas";
import deployRaw from "./replay-deploy-db-regression.json";
import poisonedRaw from "./replay-poisoned-knowledge.json";
import prometheusDownRaw from "./replay-prometheus-down-logs-only.json";
import unknownRaw from "./replay-unknown-service.json";
import replaysRaw from "./replays.json";

export const raw = { deployRaw, poisonedRaw, prometheusDownRaw, unknownRaw, replaysRaw };

export const deployReplay = replayResultSchema.parse(deployRaw);
export const deployReport: Report = deployReplay.report;
export const poisonedReport: Report = replayResultSchema.parse(poisonedRaw).report;
export const prometheusDownReport: Report = replayResultSchema.parse(prometheusDownRaw).report;
export const unknownReport: Report = replayResultSchema.parse(unknownRaw).report;
export const replayCases = replayCaseListSchema.parse(replaysRaw);

/** A deep copy to mutate in a test. */
export function clone<T>(value: T): T {
  return structuredClone(value);
}
