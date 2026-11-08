# OpsPilot MCP tools

The MCP server (`mcp/opsmcp`) is the only way the investigation agent reaches
operational data. It uses the official MCP Python SDK (FastMCP) over Streamable
HTTP (`POST /mcp`, stateless, JSON responses).

## Why typed tools instead of shell access

- **Bounded blast radius:** every tool can only make read-only GET requests to
  three configured backends (Prometheus, Loki, the OpsPilot API). There is no
  code path that runs commands, writes files, or reaches a URL the caller chose.
- **Validated input:** published JSON schemas plus server-side validation.
  Service names must match `^[a-z0-9][a-z0-9_-]{0,99}$` before they are put into
  a PromQL or LogQL selector, so queries can't be injected. Loki queries are
  always built server-side.
- **Honest output:** results are typed. Every result has a `status` field
  (`ok`, `partial` or `unavailable`) and an `errors` list. Data that couldn't be
  read comes back as `null`; it is never estimated or defaulted.
- **Auditable:** every call is logged (`tool_call` with `tool_name`, `latency_ms`,
  `outcome` and the arguments) and counted in Prometheus
  (`opspilot_mcp_tool_calls_total{tool,outcome}`,
  `opspilot_mcp_tool_duration_seconds`).
- **Testable:** each tool is a plain async function over injected clients.

A shell tool would give the model (and anyone who can influence its context,
for example through a poisoned document) the full privileges of the host.

## Transport and access control

- **Network:** only on the internal Compose/VPC network. The host port is bound to 127.0.0.1.
- **Auth:** with `MCP_AUTH_TOKEN` set, `/mcp` requires `Authorization: Bearer <token>`, compared in constant time. `/health` and `/metrics` stay open for probes and Prometheus.
- **Container:** runs as a non-root user and gets no `.env` file. Its only settings are the backend URLs, the catalog path and the token.

## Tools

The six tools share these properties:

- **Security boundary:** read-only GET requests to Prometheus, Loki and/or the OpsPilot API at fixed URLs. Service names are validated before use.
- **Errors:**
  - Invalid input returns an MCP tool error (`isError`).
  - A backend that is down or returns 5xx gives `status: unavailable` (or `partial` if other sources still answered), with an `errors` entry such as `metrics_unavailable`.
  - Raw backend responses are never echoed.

### get_service_health

- **Input:**
  - `service`
- **Output:**
  - `health`: `healthy`, `degraded`, `down` or `unknown`
  - `error_rate`, `p95_latency_ms`, `request_rate`, `version`, `targets_up`
  - `reasons`: why health is not `healthy`
  - `dependency_status`: per dependency, `service`, `status`, `error_rate` and `p95_latency_ms`
- **Purpose:** first look at a service during an investigation.
- **How it works:**
  - The Prometheus recording rules provide the error rate, p95 and request rate.
  - Scrape `up` is joined with the last hour of `app_info` to find the service's targets.
  - Dependencies come from the service catalog plus observed downstream traffic.
  - **degraded:** 5xx ratio above 5% or p95 above 1000 ms (both configurable).
  - **down:** none of the service's targets is up.
  - **unknown:** the service has not been seen in the last hour.
- **Failure modes:**
  - Prometheus down: `status: unavailable`, `health: unknown`, all metrics `null`.
  - Catalog missing: `status: partial`, with dependencies taken from telemetry only.
- **Tests:** healthy, degraded, down, unknown service, Prometheus down, catalog missing, MCP protocol round trip, live latency incident.

### query_metrics

- **Input:**
  - `query`: PromQL, at most 2000 characters
  - `start_time`: ISO 8601 or `now-<n>m|h|d`
  - `end_time`: default `now`
  - `step_seconds`: optional
- **Output:**
  - the query and time window actually used, including the effective step
  - `series`: each with `metric` labels and `points` (`timestamp`, `value`)
  - `truncated`
- **Purpose:** ad-hoc metric evidence, using the recording rules or any PromQL.
- **Security:**
  - PromQL is read-only by design.
  - The range is capped at 24 h and each series at 300 points (the step is raised to fit).
  - At most 50 series are returned.
- **Failure modes:**
  - A query Prometheus rejects comes back as `invalid_query`, with Prometheus' short error message.
  - Prometheus down: `metrics_unavailable`.
- **Tests:** series parsing (NaN becomes `null`), resolution and series caps, validation cases, invalid PromQL, outage, live query.

### get_recent_logs

- **Input:**
  - `service`
  - `minutes`: 1 to 360 by default
  - `severity`: optional minimum level (`debug`, `info`, `warning` or `error`)
  - `limit`: at most 200 by default
- **Output:**
  - `entries`: each with `timestamp`, `level`, `message` and `metadata` (`request_id`, `route`, `latency_ms`, `query_time_ms`, `version`, ...)
  - `truncated`
- **Purpose:** log evidence such as `request_slow`, `slow_query_detected` and `dependency_error`.
- **How it works:**
  - LogQL is built server-side from the service name and severity only.
  - JSON lines are parsed; any other line is returned as plain text.
  - Metadata values are capped at 500 characters.
- **Failure modes:**
  - Loki down: `logs_unavailable`, with an empty `entries` list.
- **Tests:** parsing and order, the generated severity filter, validation, outage, live slow-request logs.

### get_recent_deployments

- **Input:**
  - `service`
  - `lookback_hours`: 1 to 72, default 24
- **Output:**
  - `deployments`: each with `version`, `deployment_time` (first observed), `last_seen`, `status` (`active` or `superseded`) and `deployed_before_window`
- **Purpose:** correlate incidents with releases.
- **How it works:**
  - Derived from the version history of `app_info{version}` in Prometheus, so it works for any service that exports a version label, with no CD integration needed.
  - `deployed_before_window` marks versions whose real deploy time is earlier than the window.
- **Failure modes:**
  - Prometheus down: `unavailable`.
  - Retention (3 days locally) limits how far back it can see.
- **Tests:** version history parsing, validation, outage. Live: a version change from 1.8.2 to 1.8.3 was detected.

### get_service_dependencies

- **Input:**
  - `service`
- **Output:**
  - `known_service`: whether the service is in the catalog
  - `dependencies`: each with `service`, `direction` (`downstream` or `upstream`) and `sources` (`catalog` and/or `telemetry`)
- **Purpose:** blast radius, and deciding where to look next.
- **How it works:**
  - Combines the declared catalog (`observability/catalog/services.yml`, re-read whenever it changes) with traffic observed in the last hour through `downstream_request_duration_seconds_count`.
- **Failure modes:**
  - One source failing gives `partial`; both failing gives `unavailable`.
- **Tests:** merging the two sources, upstream lookup, partial and unavailable, catalog validation, live telemetry merge.

### get_incident_events

- **Input:**
  - `service`
  - `minutes`: default 60
- **Output:**
  - `events`, newest first, each with `timestamp`, `kind` (`alert`, `incident` or `deployment`), `summary` and `details`
- **Purpose:** an incident timeline in one call.
- **How it works:**
  - Combines Prometheus alerts (firing or pending, labelled with the service), OpsPilot incidents for the service created in the window, and deployments first observed in the window.
- **Failure modes:**
  - Each source fails independently and is listed in `errors`, while the other events are still returned.
- **Tests:** timeline merge and filtering, API outage reported as partial. Live: the firing `HighLatencyP95` alert and the version 1.8.3 deployment both appeared.

## Onboarding an external project

1. Add its scrape targets: `python observability/scripts/add_monitored_project.py`.
2. Optionally describe its services and dependencies in `observability/catalog/services.yml`.

No MCP code changes are needed: tools take service names as data.
