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
| `docker-compose.yml` | Full local development stack (11 services) |
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
| `app/main.py` | FastAPI app factory, lifespan hooks, CORS, router mounting |
| `app/config.py` | Pydantic Settings — all env-driven configuration |
| `app/dependencies.py` | FastAPI dependency injection providers |
| `app/routes/health.py` | `/health` and `/ready` endpoints |
| `app/routes/incidents.py` | Incident CRUD endpoints *(skeleton)* |
| `app/routes/investigations.py` | Investigation submission/retrieval *(skeleton)* |
| `app/routes/chat.py` | Agent chat endpoint *(skeleton)* |
| `app/agents/` | *(Phase 6)* LangGraph agent — graph, state, planner, etc. |
| `app/rag/` | *(Phase 4)* RAG pipeline — ingest, chunking, embeddings, retriever |
| `app/db/` | *(Phase 1)* SQLAlchemy models, database session, repositories |
| `app/services/` | *(Phase 7)* Business logic services |

### Tests

| File | Purpose |
|------|---------|
| `tests/conftest.py` | Shared fixtures — app factory, test client |
| `tests/unit/test_health.py` | Unit tests for health, incident, investigation, chat endpoints |
| `tests/unit/test_config.py` | Unit tests for Settings defaults, caching, properties |

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

### `workloads/checkout/`

| File | Purpose |
|------|---------|
| `main.py` | Checkout service with Prometheus metrics, structured logging, and failure injection (`latency`/`errors`/`db` modes) |
| `Dockerfile` | Container (non-root, port 8080) |
| `requirements.txt` | Minimal deps (FastAPI, uvicorn, prometheus-client) |

### `workloads/payments/`

| File | Purpose |
|------|---------|
| `main.py` | Payments service with `/process` endpoint, metrics |
| `Dockerfile` | Container (non-root, port 8081) |

### `workloads/users/`

| File | Purpose |
|------|---------|
| `main.py` | Users service with `/users/{id}` endpoint, metrics |
| `Dockerfile` | Container (non-root, port 8082) |

---

## `observability/` — Monitoring Stack

| File | Purpose |
|------|---------|
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
| `ci.yml` | GitHub Actions pipeline: lint → unit tests → Docker build → Trivy scan → Terraform validate |

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

| Directory | Purpose |
|-----------|---------|
| `system/` | *(Phase 10)* End-to-end system tests |
| `evaluation/` | *(Phase 10)* Agent evaluation test cases |
| `fixtures/` | *(Phase 10)* Shared test data |
