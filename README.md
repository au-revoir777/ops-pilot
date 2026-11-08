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
| Frontend       | Next.js 15, TypeScript, Tailwind v4, Radix, TanStack Query/Table, Recharts, React Flow |
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
| Testing        | pytest, evaluation harness, Vitest, Playwright, axe-core |
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

## Demo workloads and incident lab

`checkout`, `payments` and `users` are small FastAPI services built from one
image (`workloads/`). Checkout calls users, queries a simulated database and
charges payments. Each service exposes `/health` and `/metrics`, writes JSON
logs and forwards `X-Request-ID`.

```bash
ENABLE_FAILURE_INJECTION=true docker compose up -d --build checkout payments users
make traffic                     # baseline: p95 ~200 ms
make incident MODE=db            # or latency | errors | none
make traffic                     # db incident: p95 ~2 s, slow_query_detected logs
make incident MODE=none
```

Failure injection is off by default and `/admin/failure` returns 403 unless it is
enabled. Set `FAILURE_SEED` for reproducible incidents and `FAILURE_ADMIN_TOKEN`
to require an `X-Admin-Token` header. Host ports default to 8080/8081/8082 on
127.0.0.1 and can be changed with `CHECKOUT_PORT`, `PAYMENTS_PORT` and `USERS_PORT`.

## Observability

Prometheus scrapes every service's `/metrics`. Grafana Alloy ships container
logs (JSON) to Loki, and Grafana is provisioned with both data sources and the
**OpsPilot — Services** dashboard: request rate, error rate, p50/p95/p99,
targets up, deployed versions, DB and downstream latency, warning/error logs.

```bash
ENABLE_FAILURE_INJECTION=true docker compose up -d --build   postgres migrate api checkout payments users prometheus loki alloy grafana
```

| UI | URL |
|----|-----|
| Grafana | http://localhost:3000 (anonymous viewer; admin password from `GRAFANA_ADMIN_PASSWORD`) |
| Prometheus | http://localhost:9090 (rules and alerts under Status / Alerts) |
| Loki API | http://localhost:3100 |

Trace one request across services in Grafana Explore (Loki):
`{service=~"checkout|users|payments"} | request_id="<X-Request-ID>"`.

### Monitoring your own project (custom option)

The demo workloads are only a rough evaluation test bed. To monitor another
deployed project, point OpsPilot at its Prometheus `/metrics` endpoints:

```bash
python observability/scripts/add_monitored_project.py   --project my-project --target my-api.internal:8000 --environment production
```

This writes `observability/prometheus/targets/my-project.yml`. Prometheus picks
it up within 30 s (no restart), and its series carry `project="my-project"`, so
dashboards and alerts keep it apart from the demo (`project="opsdemo"`).
Delete the file to stop monitoring. OpsPilot only reads from external targets.

Dashboards are generated: edit `observability/grafana/build_dashboards.py`,
then run it. Ports are configurable with `GRAFANA_PORT`, `PROMETHEUS_PORT`,
`LOKI_PORT` and `API_PORT`.

## Knowledge base (RAG)

Runbooks, architecture notes, troubleshooting guides, a rollback procedure and a
postmortem live in `docs/knowledge/` as Markdown with YAML front matter. They are
chunked, embedded locally with `BAAI/bge-small-en-v1.5` (no API key) and stored
in PostgreSQL/pgvector.

```bash
make ingest          # or: docker compose exec api python -m app.rag.ingest
make rag-eval        # hit@1 / hit@5 / MRR on tests/fixtures/rag_eval.yml
curl -s -X POST localhost:8000/api/knowledge/search -H 'content-type: application/json' \
  -d '{"query": "Why did checkout latency increase?", "top_k": 3}'
```

Ingestion is idempotent: unchanged files are skipped, edited files are re-embedded,
and deleted files are removed. Every result carries its source, section, chunk and
score. Retrieved text is treated as untrusted data, and instruction-like
passages are flagged. To add a document, drop a Markdown file into the right
folder and re-run the ingest.

## MCP server (operational tools)

The agent reaches live telemetry only through six typed, read-only MCP tools:

- `get_service_health`
- `query_metrics`
- `get_recent_logs`
- `get_recent_deployments`
- `get_service_dependencies`
- `get_incident_events`

The server uses the official MCP SDK over Streamable HTTP on port 8001. See
[docs/design/mcp-tools.md](docs/design/mcp-tools.md) for schemas, security
boundaries and failure modes.

```bash
docker compose up -d --build mcp       # plus prometheus, loki and the services
python mcp/scripts/call_tool.py --list
python mcp/scripts/call_tool.py get_service_health service=checkout
python mcp/scripts/call_tool.py get_recent_logs service=checkout minutes=10 severity=warning
```

Set `MCP_AUTH_TOKEN` to require a bearer token. Service dependencies are declared
in `observability/catalog/services.yml` and merged with observed traffic.

## Investigation agent

A bounded LangGraph agent investigates an incident by combining the knowledge base
(RAG) with live telemetry (MCP tools). Its report separates five things:

- observed facts
- retrieved evidence
- hypotheses
- validation
- the conclusion, with a transparent confidence breakdown

It recommends remediation but never performs it.

```bash
cd apps/api
python -m app.agents.run "Investigate why checkout latency increased" --minutes 30
python -m app.agents.evaluation        # 14 scenarios, machine-readable metrics
```

The agent works without any LLM. Set `LLM_PROVIDER` (`openai` or `anthropic`),
`LLM_MODEL` and `LLM_API_KEY` to add a labelled, model-written summary. See
[docs/design/agent.md](docs/design/agent.md).

## Web UI

The UI (`apps/web`, http://localhost:3001) is built around one question: what
does OpsPilot actually know? Every investigation is split into observed facts,
retrieved evidence, hypotheses, contradictions and gaps, validation, diagnosis
and recommendation. Each claim links to the tool call or document behind it,
and a claim with nothing behind it is flagged as unsupported.

| Page | What it shows |
|------|---------------|
| Dashboard | Service health cards, request/error/latency charts with deployment markers, active incidents, the last investigation. Refreshes every 15 s. |
| Investigations | Ask a question or replay a recorded incident. The detail page shows the agent trace (steps or graph), findings, and sources (documents, tool calls with raw JSON, log excerpts). |
| Incident Lab | Inject latency, errors or DB slowness into the demo services, generate traffic and watch the charts respond. Every action is logged with its correlation ID. |
| Incident History | Server-side filtered and paginated history, incidents with timelines, and replayable incidents with match/mismatch against the recorded root cause. |
| System Status | Service map of OpsPilot's own components with live health, plus the safe public configuration. |

```bash
docker compose up -d --build web          # web on 127.0.0.1:3001, proxies /api/* to the API
# The incident lab needs both switches (demo services only):
ENABLE_INCIDENT_LAB=true ENABLE_FAILURE_INJECTION=true docker compose up -d api checkout payments users

cd apps/web && npm ci && npm run dev      # dev server on :3001 (API_INTERNAL_URL defaults to 127.0.0.1:8000)
```

- **Read-only:** the top bar shows a READ-ONLY indicator. Recommendations are proposals with copyable instructions; OpsPilot has no endpoint that executes them.
- **Untrusted content:** documents, logs and model text render as plain text only, with credential-looking values redacted. Chunks flagged as possible prompt injection carry a warning.
- **Appearance:** four palettes (Graphite, Ocean, Ember, Forest), each light and dark. Status colors never change between palettes. `npm run contrast` checks them against WCAG AA.
- **Keyboard:** Ctrl/Cmd+K opens the command palette, `?` lists shortcuts, and `g` then `d`/`i`/`l`/`h`/`s` jumps between pages.

## Investigation API

```bash
# Ask a question; the agent runs and the result is stored (201)
curl -s -X POST localhost:8000/api/investigations -H 'content-type: application/json' \
  -d '{"query": "Investigate why checkout latency increased", "window_minutes": 30}'

# Or run in the background (202) and poll
curl -s -X POST localhost:8000/api/investigations -H 'content-type: application/json' \
  -d '{"query": "Why is checkout returning errors?", "wait": false}'
curl -s localhost:8000/api/investigations/<id>

curl -s localhost:8000/api/services     # registered + telemetry-discovered services
curl -s localhost:8000/api/health       # database / MCP / knowledge base / LLM status
```

An investigation response carries:

- `status`, `service`, `root_cause`, `diagnosis` and `confidence`
- `latency_ms`
- the full agent `report`
- an ordered `events` timeline: status changes, evidence (telemetry and knowledge), tool calls, hypotheses and the conclusion

Timeouts return 504 `INVESTIGATION_TIMEOUT`, and the run is marked FAILED.

## Testing

```bash
make test-unit         # no database needed
make test-db-up        # disposable Postgres on 127.0.0.1:5433 (tmpfs)
make test-integration  # real PostgreSQL: migrations, repositories, API
make test-db-down
make test              # unit + integration (system/evaluation excluded)
make test-system       # needs the running stack (see Observability)
pytest -m evaluation   # retrieval quality with the real embedding model
make lint              # Ruff lint + format check
make test-web          # frontend: type-check, Vitest (unit, component, security), contrast
make lint-web          # ESLint (react/no-danger is an error)
make test-web-e2e      # Playwright + axe against the running stack (web on :3001)
```

Integration tests read `TEST_DATABASE_URL` (default: the `postgres-test`
Compose service) and refuse any database whose name does not end in `_test`.
The schema is built once with `alembic upgrade head`. Each test runs inside a
transaction that is rolled back afterwards; service commits become SAVEPOINT
releases, so tests never leak state into each other.


## License

Private — Portfolio project.
