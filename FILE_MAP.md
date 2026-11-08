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
| `app/agents/` | *(Phase 6)* LangGraph agent: graph, state, planner, etc. |
| `app/rag/` | *(Phase 4)* RAG pipeline: ingest, chunking, embeddings, retriever |

### Tests

| File | Purpose |
|------|---------|
| `tests/conftest.py` | Auto-applies `unit` / `integration` markers by directory |
| `tests/unit/test_config.py` | Settings defaults, env parsing, environments, test-DB guard, secret masking |
| `tests/unit/test_health.py` | Probes, request IDs, structured/non-leaking errors, validation (no DB) |
| `tests/unit/test_metrics.py` | /metrics, route-template labels, domain counters, log context |
| `tests/unit/test_services.py` | State machines, transaction commit/rollback with mocked repositories |
| `tests/integration/conftest.py` | Real Postgres fixtures: Alembic to head, savepoint-rollback isolation |
| `tests/integration/test_migrations.py` | Upgrade from empty, downgrade/re-upgrade, models == migrations |
| `tests/integration/test_persistence.py` | Repositories, constraints, FKs, cascades, pgvector, N+1, rollback |
| `tests/integration/test_api.py` | HTTP API against the real database |

---

## `mcp/` — MCP Server

| File | Purpose |
|------|---------|
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

## `docs/` — Knowledge Base for RAG

| Directory | Purpose |
|-----------|---------|
| `runbooks/` | *(Phase 4)* Operational runbooks |
| `postmortems/` | *(Phase 4)* Incident postmortems |
| `architecture/` | *(Phase 4)* Architecture documentation |
| `incidents/` | *(Phase 4)* Incident scenario definitions |

---

## `tests/` — Top-Level Test Suites

| Path | Purpose |
|------|---------|
| `observability/test_observability_config.py` | Unit: scrape targets vs Compose, rules/dashboards only use emitted metrics, stale dashboard, data-source UIDs, ports |
| `system/test_observability_stack.py` | System (`pytest -m system`, needs the stack): targets up, rules loaded, Grafana, cross-service request trace in Loki, latency injection visible |
| `evaluation/` | *(Phase 10)* Agent evaluation test cases |
| `fixtures/` | *(Phase 10)* Shared test data |

-----------|---------|
| `system/` | *(Phase 10)* End-to-end system tests |
| `evaluation/` | *(Phase 10)* Agent evaluation test cases |
| `fixtures/` | *(Phase 10)* Shared test data |
