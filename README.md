# OpsPilot

**AI-Powered Production Incident Investigation and SRE Copilot**

---

## Overview

OpsPilot is a production-style AI SRE platform that investigates production incidents by combining:

- **Agentic reasoning** (LangGraph state machine)
- **Retrieval-Augmented Generation** (RAG with pgvector)
- **Model Context Protocol** (MCP operational tools)
- **Real-time observability** (Prometheus + Loki + Grafana)
- **Evidence-based diagnosis** with confidence scoring

## Problem

Production incidents require engineers to manually correlate metrics, logs, deployment history, service health, architecture documentation, runbooks, and historical incidents. This is time-consuming and error-prone.

## Solution

OpsPilot automates incident investigation by:

1. Understanding the investigation request
2. Retrieving relevant knowledge (runbooks, architecture docs, postmortems)
3. Querying operational data (metrics, logs, deployments, service health)
4. Generating evidence-backed hypotheses
5. Validating hypotheses against collected evidence
6. Producing root-cause diagnosis with confidence scoring
7. Recommending remediation actions

## Architecture

```
Browser (Next.js) → FastAPI API → Agent (LangGraph)
                                      ├── RAG (pgvector)
                                      └── MCP Server
                                            ├── Prometheus
                                            ├── Loki
                                            └── Workload data
```

## Technology Stack

| Layer          | Technology                          |
|----------------|-------------------------------------|
| Frontend       | Next.js, TypeScript, Tailwind CSS   |
| Backend        | Python, FastAPI, Pydantic           |
| Agent          | LangGraph, LangChain               |
| RAG            | PostgreSQL, pgvector                |
| MCP            | Custom typed tool server            |
| Database       | PostgreSQL + pgvector               |
| Observability  | Prometheus, Loki, Grafana, OTel     |
| Containers     | Docker, Docker Compose              |
| Cloud          | AWS (ECS Fargate, RDS, ALB, ECR)    |
| IaC            | Terraform                           |
| CI/CD          | GitHub Actions                      |
| Testing        | pytest, evaluation harness          |
| Security       | Trivy, least-privilege IAM          |

## Quick Start

```bash
# 1. Clone and setup
cp .env.example .env
# Edit .env with your LLM_API_KEY

# 2. Start everything
make up

# 3. Open the dashboard
open http://localhost:3001

# 4. Inject a test incident
make incident

# 5. Investigate
# Navigate to the Investigation page and ask:
# "Why is checkout latency high?"
```

## Database

PostgreSQL 16 + pgvector is the single datastore (relational data now, RAG
embeddings in Phase 4). The API uses SQLAlchemy 2.x (async, asyncpg) and
Alembic.

```
routes (thin, Pydantic schemas)
  ↓
services (business rules, transaction boundary: commit / rollback)
  ↓
repositories (queries, add/flush; never commit)
  ↓
SQLAlchemy AsyncSession → PostgreSQL
```

Tables: `workloads`, `incidents`, `investigations`, `investigation_events`.
See `DECISIONS.md` (D-013 to D-019) for the reasoning.

### Local development

```bash
cp .env.example .env               # then set POSTGRES_PASSWORD / DATABASE_URL
docker compose up -d postgres      # pgvector/pgvector:0.8.0-pg16, 127.0.0.1:5432
cd apps/api && alembic upgrade head
make dev                           # http://localhost:8000/docs
```

Or run Postgres, migrations and the API together:
`docker compose up -d --build postgres migrate api`. The one-shot `migrate`
service runs `alembic upgrade head` and the API starts only if it succeeds.
If port 5432 is already taken on your machine, set `POSTGRES_PORT=55432`.

Health probes: `GET /health` (process alive, no I/O) and `GET /ready`
(runs `SELECT 1` with a 2s timeout, returns 503 when the database is down).

New migration: `cd apps/api && alembic revision --autogenerate -m "describe change"`,
then review the generated file. The schema is only ever changed through migrations.

## Testing

```bash
make test-unit         # no database needed
make test-db-up        # disposable Postgres on 127.0.0.1:5433 (tmpfs)
make test-integration  # real PostgreSQL: migrations, repositories, API
make test-db-down
make test              # everything
make lint              # Ruff lint + format check
```

Integration tests read `TEST_DATABASE_URL` (default: the `postgres-test`
Compose service) and refuse any database whose name does not end in `_test`.
The schema is built once with `alembic upgrade head`. Each test runs inside a
transaction that is rolled back afterwards; service commits become SAVEPOINT
releases, so tests never leak state into each other.

## Project Status

- [x] Phase 0: Project Bootstrap
- [x] Phase 1: Database & Core Backend
- [ ] Phase 2: Demo Workloads
- [ ] Phase 3: Observability
- [ ] Phase 4: RAG Pipeline
- [ ] Phase 5: MCP Server
- [ ] Phase 6: Agent
- [ ] Phase 7: Investigation API
- [ ] Phase 8: Frontend
- [ ] Phase 9: E2E Incident Scenario
- [ ] Phase 10: Testing Expansion
- [ ] Phase 11: Security Hardening
- [ ] Phase 12: Docker Production Parity
- [ ] Phase 13: CI/CD
- [ ] Phase 14: Terraform
- [ ] Phase 15: AWS Deployment
- [ ] Phase 16: Cost Controls
- [ ] Phase 17: Performance & Reliability
- [ ] Phase 18: Architecture Documentation
- [ ] Phase 19: Interview Preparation
- [ ] Phase 20: Final Audit

## License

Private — Portfolio project.
