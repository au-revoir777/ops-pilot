# OpsPilot — File Map

> Quick reference for navigating the repository during development and interviews.
> Updated as new files are added in each phase.

---

## Root

| File | Purpose |
|------|---------|
| `README.md` | Project overview, setup, architecture, tech stack |
| `DECISIONS.md` | Architecture Decision Records (ADRs) |
| `FILE_MAP.md` | This file — repository navigation guide |
| `ARCHITECTURE_REPORT.md` | *(Phase 18)* Comprehensive architecture documentation |
| `INTERVIEW_PREPARATION.md` | *(Phase 19)* Interview Q&A and study guide |
| `docker-compose.yml` | Local stack: postgres, migrate, api, mcp, workloads, observability, web; `postgres-test` under the `test` profile |
| `Makefile` | All build/test/deploy commands |
| `.env.example` | Environment variable template (no secrets) |
| `pyproject.toml` | Python tooling config (Ruff, pytest) |
| `.gitignore` | Git ignore rules |

---

## `apps/api/` — Backend API (FastAPI)

| File | Purpose |
|------|---------|
| `Dockerfile` | API container (non-root, multi-stage, health check) |
| `requirements.txt` | Python dependencies |
| `alembic.ini` | Alembic config (no URL inside; env.py reads `DATABASE_URL`) |
| `app/main.py` | App factory, lifespan (engine create/dispose), CORS, request-ID middleware, error handlers |
| `app/config.py` | Pydantic Settings: env-driven config, DB pool settings, `_test` database guard |
| `app/dependencies.py` | DI providers: request-scoped session, services |
| `app/routes/health.py` | `/health` (liveness) and `/ready` (DB `SELECT 1`, 503 on failure) |
| `app/routes/incidents.py` | `POST/GET /api/incidents`, `GET /api/incidents/{id}`, `PATCH .../status` |
| `app/routes/system.py` | `GET /api/services`, `GET /api/health` (dependency status) |
| `app/services/investigation_runner.py` | Runs the agent for an investigation, persists evidence/result, handles timeouts |
| `app/db/migrations/versions/0003_investigation_results.py` | Investigation query/result columns |
| `app/routes/investigations.py` | `POST /api/investigations`, `GET /api/investigations/{id}`, `GET /api/incidents/{id}/investigations` |
| `app/routes/chat.py` | Agent chat endpoint *(skeleton)* |
| `app/metrics.py` | Prometheus metrics: RED middleware, domain metrics, agent metric contract |
| `app/db/base.py` | Declarative base, naming convention, UUID/timestamp mixins, `pg_enum` helper |
| `app/db/session.py` | Engine/session factory lifecycle, `get_db_session`, slow-query logging |
| `app/db/models/` | `Workload`, `Incident`, `Investigation`, `InvestigationEvent` + status enums |
| `app/db/repositories/` | Query/persistence classes (never commit) |
| `app/db/migrations/env.py` | Async Alembic environment |
| `app/db/migrations/versions/0001_initial.py` | pgvector extension + the four tables, enums, indexes |
| `app/services/incident.py` | Incident lifecycle rules (transition table), create/update |
| `app/services/investigation.py` | Investigation lifecycle, timeline events, incident coupling |
| `app/services/transactions.py` | `transaction()` commit/rollback boundary |
| `app/services/exceptions.py` | Domain exceptions with error codes and HTTP statuses |
| `app/rag/documents.py` | Knowledge-base loader + cleaner (front matter validation) |
| `app/rag/chunking.py` | Heading-aware Markdown chunker with overlap |
| `app/rag/embeddings.py` | Embedding providers: local bge-small (default), OpenAI, hashing (tests) |
| `app/rag/ingest.py` | Idempotent ingestion service + `python -m app.rag.ingest` CLI |
| `app/rag/retrieval.py` | Similarity retrieval, ranking, provenance, fenced LLM context |
| `app/rag/safety.py` | Prompt-injection flagging for retrieved text |
| `app/rag/evaluate.py` | Retrieval quality metrics (hit@k, MRR, threshold checks) |
| `app/routes/knowledge.py` | `POST /api/knowledge/search`, `GET /api/knowledge/documents` |
| `app/db/models/knowledge.py` | `Document`, `DocumentChunk` (vector(384), HNSW cosine) |
| `app/db/repositories/knowledge.py` | Document/chunk persistence and filtered vector search |
| `app/db/migrations/versions/0002_knowledge_base.py` | Knowledge-base tables and indexes |
| `app/agents/graph.py` | Bounded LangGraph agent: planner, rag, mcp, hypothesis, validator, synthesizer |
| `app/agents/evidence.py` | Telemetry → observations with signal tags (step detection, log counts, deploys) |
| `app/agents/reasoning.py` | Cause rules, validation, confidence heuristic, recommendations |
| `app/agents/tools.py` | Allow-listed MCP client (official SDK) |
| `app/agents/llm.py` | Optional LLM providers (none/openai/anthropic), labelled summaries |
| `app/agents/models.py` | Report, observation, hypothesis, confidence models |
| `app/agents/simulation.py` | Scenario replay: simulated MCP/RAG results for evaluation and tests |
| `app/agents/evaluation.py` | Evaluation metrics over `apps/api/app/agents/scenarios/cases.json` |
| `app/agents/render.py` | Markdown rendering of a report |
| `app/agents/run.py` | CLI: `python -m app.agents.run "question"` against the live stack |

### Tests

| File | Purpose |
|------|---------|
| `tests/conftest.py` | Auto-applies `unit` / `integration` markers by directory |
| `tests/unit/test_config.py` | Settings defaults, env parsing, environments, test-DB guard, secret masking |
| `tests/unit/test_health.py` | Probes, request IDs, structured/non-leaking errors, validation (no DB) |
| `tests/unit/test_metrics.py` | /metrics, route-template labels, domain counters, log context |
| `tests/unit/test_rag.py` | Loader, cleaner, chunker, embedders, ranking, prompt-injection defence, search API errors |
| `tests/integration/test_rag_pipeline.py` | Ingest → pgvector → retrieval, filters, idempotency, pruning, search API |
| `tests/integration/test_rag_quality.py` | `pytest -m evaluation`: retrieval quality with the real model |
| `tests/unit/test_agent.py` | Graph transitions, bounds, planner, evidence, confidence, LLM stub |
| `tests/unit/test_investigation_runner.py` | Runner success/timeout/failure, report → events, route validation |
| `tests/integration/test_investigation_api.py` | API → database → agent: sync/background runs, failures, services, health |
| `tests/unit/test_services.py` | State machines, transaction commit/rollback with mocked repositories |
| `tests/integration/conftest.py` | Real Postgres fixtures: Alembic to head, savepoint-rollback isolation |
| `tests/integration/test_migrations.py` | Upgrade from empty, downgrade/re-upgrade, models == migrations |
| `tests/integration/test_persistence.py` | Repositories, constraints, FKs, cascades, pgvector, N+1, rollback |
| `tests/integration/test_api.py` | HTTP API against the real database |

---

## `mcp/` — MCP Server

| File | Purpose |
|------|---------|
| `Dockerfile` | MCP container (non-root, health check, port 8001) |
| `requirements.txt` | MCP SDK and server dependencies |
| `opsmcp/server.py` | FastMCP server: tool registration, schemas, `/health`, `/metrics`, bearer auth, ASGI app |
| `opsmcp/tools.py` | The six tool implementations (validation, queries, typed results) |
| `opsmcp/models.py` | Typed tool outputs (published as MCP output schemas) |
| `opsmcp/backends.py` | Read-only Prometheus, Loki and OpsPilot API clients |
| `opsmcp/catalog.py` | Service catalog loader (declared dependencies) |
| `opsmcp/instrumentation.py` | Tool-call logging and Prometheus metrics |
| `opsmcp/config.py` | Env-driven settings and guard rails |
| `scripts/call_tool.py` | CLI: list or call tools through the MCP client |
| `tests/test_mcp_tools.py` | Unit tests for every tool (fake backends) |
| `tests/test_mcp_protocol.py` | Integration: real MCP client ↔ server over Streamable HTTP |
| `tests/mcp_fakes.py` | Fake Prometheus/Loki/API transport |

------|---------|
| `Dockerfile` | MCP container (non-root, health check) |
| `requirements.txt` | MCP dependencies (lighter than API) |
| `server.py` | Official MCP SDK (FastMCP) server *(skeleton)* |
| `tools/` | *(Phase 5)* Typed operational tools (metrics, logs, deployments, etc.) |

---

## `workloads/` — Demo Microservices

One package, one image, three services (D-020). Compose picks the service via the container command.

| File | Purpose |
|------|---------|
| `Dockerfile` | Single non-root image for checkout, payments and users (health check on `SERVICE_PORT`) |
| `requirements.txt` | Shared workload dependencies |
| `opsdemo/app.py` | Shared app factory: `/health`, `/metrics`, `/admin/failure`, error handling, simulated DB, downstream HTTP client |
| `opsdemo/config.py` | Env-driven `WorkloadSettings` (failure injection off by default) |
| `opsdemo/failures.py` | Seedable `FailureInjector`: `none`, `latency`, `errors`, `db` |
| `opsdemo/observability.py` | JSON logs, request-ID middleware, bounded RED/DB/downstream metrics |
| `opsdemo/checkout.py` | `POST /checkout`: users lookup → cart query → payment → order write (port 8080) |
| `opsdemo/payments.py` | `POST /payments`: capture or decline (port 8081) |
| `opsdemo/users.py` | `GET /users/{user_id}`: demo users `u-1`..`u-1000` (port 8082) |
| `scripts/traffic.py` | Sends checkout traffic and prints p50/p95 and status counts |
| `tests/test_failure_injection.py` | Unit: injector modes, seeding, settings |
| `tests/test_workload_endpoints.py` | Unit: endpoints, metrics labels, request IDs, failure behaviour, admin gate (stubbed downstream) |
| `tests/test_workload_integration.py` | Integration: the three services as real HTTP servers talking to each other |

---

## `observability/` — Monitoring Stack

| File | Purpose |
|------|---------|
| `prometheus/prometheus.yml` | Scrape config: API, workloads, Loki, Alloy, Prometheus (10 s) |
| `prometheus/targets/demo-workloads.yml` | File-discovered demo targets (`project=opsdemo`) |
| `prometheus/targets/external-project.yml.example` | Format for onboarding an external project |
| `scripts/add_monitored_project.py` | Custom option: connect an external project's /metrics endpoints |
| `catalog/services.yml` | Service catalog: owners and declared dependencies (read by MCP) |
| `prometheus/rules/opspilot.yml` | RED recording rules (rate, error ratio, p50/p95/p99, DB p95) + alerts |
| `loki/loki-config.yml` | Loki single-binary config (filesystem storage, schema v13) |
| `alloy/config.alloy` | Grafana Alloy: Docker log discovery → JSON parsing → Loki (request_id as structured metadata) |
| `grafana/provisioning/datasources/datasources.yml` | Prometheus and Loki data sources with fixed UIDs |
| `grafana/provisioning/dashboards/dashboards.yml` | File-based dashboard provider |
| `grafana/build_dashboards.py` | Generates the dashboard JSON (dashboards as code) |
| `grafana/dashboards/opspilot-services.json` | Generated "OpsPilot — Services" dashboard |

------|---------|
| `prometheus/prometheus.yml` | Scrape config targeting all services |
| `loki/loki-config.yml` | Loki local-mode config (filesystem storage) |
| `grafana/dashboards/` | *(Phase 3)* Grafana dashboard JSON |

---

## `infra/terraform/` — AWS Infrastructure

| File | Purpose |
|------|---------|
| `main.tf` | Terraform provider config + default tags *(skeleton)* |
| `variables.tf` | Input variables (region, environment, project name) |

---

## `.github/workflows/` — CI/CD

| File | Purpose |
|------|---------|
| `ci.yml` | GitHub Actions: lint → unit tests + integration tests (pgvector service, migration round-trip) → Docker build → Trivy → Terraform validate |

---

## `docs/design/`

| File | Purpose |
|------|---------|
| `mcp-tools.md` | Per-tool schemas, security boundary, failure modes, tests |
| `agent.md` | Agent state diagram, nodes, rules, confidence formula, limits |

## `docs/knowledge/` — RAG Knowledge Base

Markdown with YAML front matter (`title`, `doc_type`, `services`, extras kept as metadata).

| Directory | Contents |
|-----------|----------|
| `runbooks/` | Checkout and payments on-call runbooks |
| `architecture/` | Checkout and payments architecture, service dependency map |
| `troubleshooting/` | Database, latency and Redis troubleshooting guides |
| `procedures/` | Deployment rollback procedure |
| `postmortems/` | Simulated checkout slow-query postmortem |

-----------|---------|
| `runbooks/` | *(Phase 4)* Operational runbooks |
| `postmortems/` | *(Phase 4)* Incident postmortems |
| `architecture/` | *(Phase 4)* Architecture documentation |
| `incidents/` | *(Phase 4)* Incident scenario definitions |

---

## `tests/` — Top-Level Test Suites

| Path | Purpose |
|------|---------|
| `observability/test_observability_config.py` | Unit: scrape targets vs Compose, rules/dashboards only use emitted metrics, stale dashboard, data-source UIDs, ports |
| `observability/test_add_monitored_project.py` | Unit: onboarding script output and validation |
| `system/test_mcp_stack.py` | System: MCP tools against the live stack, incl. a latency incident |
| `system/test_observability_stack.py` | System (`pytest -m system`, needs the stack): targets up, rules loaded, Grafana, cross-service request trace in Loki, latency injection visible |
| `apps/api/app/agents/scenarios/cases.json` | 14 scenarios (evaluation, replay, tests) |
| `evaluation/test_agent_evaluation.py` | `pytest -m evaluation`: runs the scenarios, writes `results/latest.json` |
| `fixtures/rag_eval.yml` | Labelled retrieval questions (relevant + off-topic) |

-----------|---------|
| `system/` | *(Phase 10)* End-to-end system tests |
| `apps/api/app/agents/scenarios/cases.json` | 14 scenarios (evaluation, replay, tests) |
| `evaluation/test_agent_evaluation.py` | `pytest -m evaluation`: runs the scenarios, writes `results/latest.json` |
| `fixtures/rag_eval.yml` | Labelled retrieval questions (relevant + off-topic) |
