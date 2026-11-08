# OpsPilot — Decision Log

> Significant implementation decisions made during development.
> Each entry documents the context, alternatives considered, and consequences.

---

## D-001: Python 3.11 as minimum runtime

- **Date:** 2026-10-02
- **Context:** Need a stable Python version with good async support, `datetime.UTC`, and typing improvements.
- **Alternatives:** Python 3.10 (missing `datetime.UTC`, older typing), Python 3.12/3.13 (less ecosystem testing).
- **Decision:** Python 3.11 — mature, fast, widely supported, good typing.
- **Consequences:** Can use `datetime.UTC` alias, `match` statements, `ExceptionGroup` if needed. All major libraries support 3.11.

---

## D-002: FastAPI for the backend API

- **Date:** 2026-10-02
- **Context:** Need an async Python web framework with automatic validation, OpenAPI docs, and good performance.
- **Alternatives:** Django REST Framework (heavier, sync-first), Flask (no built-in validation/async), Litestar (smaller ecosystem).
- **Decision:** FastAPI — async-native, Pydantic integration, automatic OpenAPI, excellent performance.
- **Consequences:** Natural Pydantic model validation. OpenAPI docs for free. Strong community. Well-understood in interviews.

---

## D-003: Pydantic Settings for configuration

- **Date:** 2026-10-02
- **Context:** All configuration must be environment-driven, no hard-coded secrets.
- **Alternatives:** python-dotenv only (no validation), dynaconf (more complex), manual os.getenv.
- **Decision:** `pydantic-settings` — type-safe, validated, `.env` file support, auto-documentation via Field descriptions.
- **Consequences:** Config errors surface at startup. Settings are testable. Easy to reason about in interviews.

---

## D-004: Structlog for structured logging

- **Date:** 2026-10-02
- **Context:** Need JSON structured logging with correlation IDs for observability.
- **Alternatives:** stdlib `logging` with `python-json-logger` (less ergonomic), loguru (not stdlib-compatible).
- **Decision:** structlog — composable processors, context variables, JSON output, integrates with stdlib.
- **Consequences:** Every log entry is machine-parseable. Correlation IDs via `contextvars`. Loki-friendly.

---

## D-005: Separate MCP server from the API

- **Date:** 2026-10-02
- **Context:** The agent needs operational tools (metrics, logs, deployments). Could be built into the API or run as a separate service.
- **Alternatives:** Embed tools directly in the API (simpler but violates separation), use a generic tool framework.
- **Decision:** Dedicated MCP server running in its own container as a separate service, using the official Model Context Protocol (MCP) Python SDK (`FastMCP`) over standard Streamable HTTP transport.
- **Consequences:** Clear blast radius. Agent communicates using standard MCP protocol rather than arbitrary custom REST endpoints. Additional container in Docker Compose.

---

## D-006: Non-root Docker containers

- **Date:** 2026-10-02
- **Context:** Security best practice for containerized services.
- **Alternatives:** Run as root (simpler, less secure), use distroless (harder to debug).
- **Decision:** Create dedicated `opspilot`/`workload` users in Dockerfiles, switch with `USER` directive.
- **Consequences:** Reduced attack surface. Cannot bind to privileged ports (not needed). Consistent with ECS Fargate best practices.

---

## D-007: Prometheus metrics in workloads

- **Date:** 2026-10-02
- **Context:** Demo workloads need to expose metrics that the agent can query during investigations. We must avoid metric cardinality explosion.
- **Alternatives:** StatsD (requires collector), OpenTelemetry metrics (more complex setup), custom JSON endpoints.
- **Decision:** `prometheus_client` library with `/metrics` endpoint. Metric-label strategy strictly uses normalized routes (e.g. `/checkout` instead of `/checkout/123`) to prevent unbounded high-cardinality labels.
- **Consequences:** Prometheus scrapes workloads directly. Metrics labels include service name, method, normalized endpoint, and status. Histograms provide p50/p95/p99 latency buckets.

---

## D-008: Controlled failure injection via environment variable

- **Date:** 2026-10-02
- **Context:** Need safe, reproducible incident scenarios for the demo and testing without risking production incidents.
- **Alternatives:** Chaos monkey (too destructive), sidecar proxy (complex), code-level flags.
- **Decision:** `FAILURE_MODE` env var + runtime `/admin/failure` endpoint, gated by an explicit `ENABLE_FAILURE_INJECTION` flag defaulting to `false`. Modes: `none`, `latency`, `errors`, `db`.
- **Consequences:** Safe and non-destructive. Admin endpoint returns 403 when disabled in production. Deterministic for testing. Runtime-switchable for demos. No real infrastructure damage.

---

## D-009: Ruff for linting and formatting

- **Date:** 2026-10-02
- **Context:** Need fast, comprehensive Python linting and formatting.
- **Alternatives:** Flake8 + isort + Black (three tools), pylint (slow, verbose).
- **Decision:** Ruff — single tool for linting and formatting, extremely fast, replaces Flake8/isort/Black.
- **Consequences:** Single config in `pyproject.toml`. Includes security rules (bandit). Sub-second lint on the whole project.

---

## D-010: GitHub Actions for CI/CD

- **Date:** 2026-10-02
- **Context:** Need automated quality checks on every push/PR.
- **Alternatives:** GitLab CI (requires GitLab), CircleCI (external service), Jenkins (self-hosted overhead).
- **Decision:** GitHub Actions — native to GitHub, free for public repos, YAML-based, good marketplace.
- **Consequences:** Pipeline: lint → unit tests → Docker build → Trivy scan → Terraform validate. OIDC for AWS deployment possible.

---

## D-011: PostgreSQL + pgvector for unified database

- **Date:** 2026-10-02
- **Context:** Need a database for relational data, incident logs, and vector embeddings for RAG architecture.
- **Alternatives:** PostgreSQL + separate vector DB (Pinecone/Qdrant) which adds operational complexity.
- **Decision:** PostgreSQL with `pgvector` extension as the single unified database and vector storage solution.
- **Consequences:** Simplifies infrastructure. Ensures transactional integrity between relational data and embeddings. No need for external vector database services unless a concrete scaling requirement emerges.

---

## D-012: Scope of Workload Microservices

- **Date:** 2026-10-02
- **Context:** The system needs microservices to simulate a realistic production environment.
- **Alternatives:** Build fully functional, elaborate e-commerce business applications.
- **Decision:** Keep checkout, payments, and users intentionally lightweight. Their primary purpose is to generate realistic operational telemetry (metrics, logs, traces) and reproducible incidents.
- **Consequences:** Development time is focused on the core SRE Copilot and investigation agent rather than bloated business logic in demo workloads.

---

## D-013: Async SQLAlchemy 2.x with one engine per process

- **Date:** 2026-11-08 (Phase 1)
- **Context:** The API is async (FastAPI), and each request needs a database session without paying connection setup costs.
- **Alternatives:** Sync SQLAlchemy in a threadpool; an engine per request; raw asyncpg.
- **Decision:** `create_async_engine` (asyncpg driver) is created once in the FastAPI lifespan and disposed on shutdown. A request-scoped `AsyncSession` comes from `async_sessionmaker` through the `get_db_session` dependency. Pool size, max overflow, timeout, recycle and pre-ping are all configured through settings (`DB_POOL_*`). Sessions use `expire_on_commit=False`, so committed objects can still be serialised without lazy loads (lazy loads are not allowed under asyncio).
- **Consequences:** One bounded pool per process. Pool sizing is part of capacity planning: `(pool_size + max_overflow) × replicas` must stay under PostgreSQL `max_connections`.

---

## D-014: Services own the transaction boundary; repositories never commit

- **Date:** 2026-11-08 (Phase 1)
- **Context:** One use case often touches several tables. For example, opening an investigation also moves the incident to `investigating` and writes the first timeline event. Those writes must succeed or fail together.
- **Alternatives:** Commit inside every repository method (partial writes on failure); commit in route handlers (business logic leaks into HTTP); a full Unit-of-Work framework (too much machinery for this size).
- **Decision:** Repositories only `add`/`flush`/`select`. Each state-changing service method wraps its whole unit of work in `async with transaction(session, "<operation>")` (`app/services/transactions.py`), which commits on success and rolls back on any exception. Driver errors are logged by type only and re-raised as `DatabaseOperationError` (HTTP 503 with a generic message). Rows whose state machine is being changed are locked with `SELECT … FOR UPDATE` (incident status changes, investigation events and sequence numbers).
- **Consequences:** Atomic multi-table operations, and lifecycle rules are enforced in one place. Routes are thin. Integration tests verify that a failure mid-operation leaves no partial writes.

---

## D-015: Initial domain model

- **Date:** 2026-11-08 (Phase 1)
- **Decision:** Four tables:
  - `workloads`: the monitored service (unique `name`, matching the metrics/log label). Incidents reference it by FK (`ON DELETE RESTRICT`). A workload is registered automatically the first time an incident names it.
  - `incidents`: native enums for status and severity, `resolved_at`. Indexes follow the actual query patterns: `(status, created_at)` for filtered lists, `created_at` for unfiltered lists, `workload_id` for the FK.
  - `investigations`: FK to incident (`ON DELETE CASCADE`), lifecycle status, `started_at`/`completed_at`, `summary`.
  - `investigation_events`: an append-only timeline (status changes, tool calls, evidence, hypotheses, conclusions) with a per-investigation `sequence` (unique together with `investigation_id`, which also serves as the lookup index). `details` is the only JSONB column, because tool output and evidence really are semi-structured.
  - UUID primary keys and timezone-aware `created_at`/`updated_at` set by the database clock. Enums store lowercase values. Lifecycle transitions are explicit tables in the service layer.
- **Not modelled yet (on purpose):** deployments, hypotheses as entities, users/auth, documents/embeddings. They arrive with the phases that need them.

---

## D-016: pgvector enabled now, vector columns deferred to Phase 4

- **Date:** 2026-11-08 (Phase 1)
- **Context:** A pgvector column needs a fixed dimension, and the dimension depends on the embedding model, which has not been chosen. The `EMBEDDING_DIMENSIONS=1536` setting is only a placeholder.
- **Decision:** Migration `0001` runs `CREATE EXTENSION IF NOT EXISTS vector`, and the integration tests check that vector operators work. No embedding table or column is created until Phase 4 selects and documents the model. Phase 4 then adds its own migration with the real dimension and index type (HNSW vs IVFFlat).
- **Consequences:** No guessed dimension baked into the schema, so no later rewrite of a vector column. The extension is still available in every environment from day one.

---

## D-017: Pinned `pgvector/pgvector:0.8.0-pg16` image; database never publicly exposed

- **Date:** 2026-11-08 (Phase 1)
- **Decision:** Local dev, the test database and CI all use the same pinned image, so the PostgreSQL major version and pgvector version cannot drift. In Compose, Postgres runs on a dedicated `backend` network with a named volume and a `pg_isready` health check. Its port is published only on `127.0.0.1` (configurable through `POSTGRES_PORT`) for local tools. In the cloud architecture it is RDS in private subnets with no public endpoint. Migrations run as a one-shot `migrate` service, and the API waits for it to succeed (`service_completed_successfully`).
- **Consequences:** Upgrading Postgres or pgvector becomes a deliberate change in one place, not something that happens when a `latest` tag moves.

---

## D-018: Integration tests use real PostgreSQL with transaction rollback isolation

- **Date:** 2026-11-08 (Phase 1)
- **Context:** Mocked databases do not catch problems with constraints, enums, cascades, migrations or locking.
- **Alternatives:** SQLite (different dialect, no pgvector/JSONB/enums); truncating tables between tests (slower, order-dependent); a database per test (slow).
- **Decision:** A disposable `postgres-test` service (tmpfs storage, `127.0.0.1:5433`) locally and the same image as a GitHub Actions service container in CI. The schema is built once per session with the real Alembic migrations. Each test opens a connection and an outer transaction. The session joins it with `join_transaction_mode="create_savepoint"`, so service `commit()`/`rollback()` act on SAVEPOINTs, and the outer transaction is rolled back after the test. Tests are marked by directory (`unit`, `integration`). Unit tests never need a database.
- **Safeguard:** Test fixtures and `APP_ENV=test` refuse any database whose name does not end in `_test`. That makes it hard for a test run to wipe a development or production database by mistake.

---

## D-019: Centralized, non-leaking error handling with correlation IDs

- **Date:** 2026-11-08 (Phase 1)
- **Decision:** Domain exceptions carry a stable `code` and HTTP status (`*_NOT_FOUND` → 404, `INVALID_*_STATE` → 409, `DATABASE_ERROR` → 503). One handler renders `{"error": {"code", "message", "request_id"}}`. 5xx responses never include internal messages. Unhandled exceptions are logged with their traceback on the server and return a generic 500. A pure-ASGI middleware binds an `X-Request-ID` (reused if the client's value is safe, otherwise generated) to structlog context vars and echoes it in the response. `DATABASE_URL` is a `SecretStr`. SQL errors are logged by exception type only, and slow queries (over `DB_SLOW_QUERY_MS`) log the SQL text without bound parameters.
- **Consequences:** Every log line for a request can be correlated, and no credentials, SQL or stack traces reach API clients.

---

## D-020: One shared workload package and one image for checkout, payments and users

- **Date:** 2026-11-08 (Phase 2)
- **Context:** The three demo services need the same plumbing: config, JSON logs, request IDs, metrics, failure injection and an admin endpoint. Three copies of that would drift apart, and the Phase 0 copies already had (checkout had a crashing failure-injection branch, and errors came back as HTTP 200).
- **Alternatives:** Three independent apps with copy-pasted code; a separately versioned internal library.
- **Decision:** A single `workloads/opsdemo` package. `app.py` is the shared factory, `observability.py` holds logs, metrics and request IDs, and `failures.py` holds the injector. Each service module contains only its routes. One `opspilot-workloads` image is built, and Compose picks the service through the container command (`uvicorn opsdemo.checkout:app`, and so on).
- **Consequences:** Less code and one build. Services are still deployed and scaled as separate containers. The trade-off is that all three ship together, which is acceptable for demo workloads (D-012).

---

## D-021: Realistic failure signals without "cheat" signals

- **Date:** 2026-11-08 (Phase 2)
- **Context:** OpsPilot must diagnose incidents from telemetry. If `/health` or the request logs said "failure_mode=db", investigations would be trivial and meaningless.
- **Decision:** Failure modes produce only the signals a real fault would:
  - **latency:** slower business requests and `request_slow` WARN logs.
  - **errors:** HTTP 500s, `request_processing_failed` ERROR logs and `http_request_errors_total`.
  - **db:** a simulated database where every query gains about 900 ms, plus `db_query_duration_seconds` and `slow_query_detected` WARN logs. Checkout runs two queries per request, so p95 rises from about 200 ms to about 2 s.

  Dependency failures cascade realistically: checkout returns 502 when payments returns 5xx, 504 on timeout, and records `downstream_request_duration_seconds` by outcome. `/health` is liveness only and never reveals the mode. Only the startup log and the operator's `/admin/failure` call mention injection.
- **Reproducibility:** All randomness (injected and baseline jitter, IDs) comes from one RNG seeded by `FAILURE_SEED`.
- **Safety:** `ENABLE_FAILURE_INJECTION` defaults to false. A configured `FAILURE_MODE` is ignored, with a warning, unless injection is enabled. `/admin/failure` returns 403 when injection is disabled, can additionally require `X-Admin-Token` (`FAILURE_ADMIN_TOKEN`, compared in constant time), and is hidden from OpenAPI. Probes and `/metrics` are never slowed down or failed.

---

## D-022: Workload metrics and log conventions

- **Date:** 2026-11-08 (Phase 2)
- **Metrics:**
  - RED metrics: `http_requests_total{service,method,route,status}`, `http_request_duration_seconds{service,method,route}`, `http_request_errors_total{service,route}` and `http_requests_in_progress{service}`.
  - `db_query_duration_seconds{service,operation}`, `downstream_request_duration_seconds{service,target,outcome}`, and `app_info{service,version}` for correlating deployments.
  - `route` is the route template taken from Starlette's matched route (`/users/{user_id}`). Unmatched paths collapse to `unmatched`, and `/metrics` and `/health` are not counted, so every label set stays bounded.
  - Histogram buckets are dense around 0.1–3 s, where the demo baseline and incident live.
  - Each app uses its own `CollectorRegistry`, so several apps can run in one process during tests.
- **Logs:** JSON on stdout, one object per line, with `timestamp`, `level`, `service`, `version`, `request_id` and an `event` name. `X-Request-ID` is accepted when it is safe (otherwise generated), echoed in the response, and forwarded on every downstream call, so one checkout can be traced across all three services.

---

## D-023: Prometheus + Loki + Grafana, with Grafana Alloy as the log collector

- **Date:** 2026-11-08 (Phase 3)
- **Context:** Investigations need metrics and logs that correlate on service, time, request and version.
- **Alternatives:**
  - Promtail as the collector: it was in maintenance mode and reached end-of-life in 2026.
  - Docker's Loki logging driver: a Docker plugin install on every host, and it fails closed when Loki is down.
  - A full OpenTelemetry Collector pipeline: more moving parts than a 2–3 day scope needs.
- **Decision:**
  - Prometheus scrapes `/metrics` from the API and every workload every 10 s.
  - Grafana Alloy (pinned `v1.5.1`) discovers this Compose project's containers through the read-only Docker socket. It parses our JSON lines and pushes to Loki 3.2.
  - Loki labels stay low-cardinality: `service`, `container`, `level`, `version`. `request_id` is stored as structured metadata, so `{service="checkout"} | request_id="…"` works without an index explosion.
  - The `service` value an app logs wins over the Compose service name, so logs and metrics use identical service names.
  - Grafana data sources and the dashboard are provisioned from files with fixed UIDs.
  - All UIs and APIs are bound to `127.0.0.1`. The Grafana admin password comes from the environment, and anonymous access is Viewer-only.
- **Consequences:** One `docker compose up` gives a working stack. Alloy needs the Docker socket, which is acceptable locally. In AWS the equivalent is the awslogs/FireLens driver to CloudWatch or Loki (Phase 15).

---

## D-024: RED recording rules, alerts and dashboards as code

- **Date:** 2026-11-08 (Phase 3)
- **Decision:**
  - Recording rules: `service:http_requests:rate1m`, `service:http_errors:ratio_rate1m`, `service:http_latency_seconds:p50|p95|p99_1m` and `service_operation:db_query_seconds:p95_1m`.
  - The dashboard and (from Phase 5) the MCP tools query these rules, not ad-hoc PromQL, so both see the same numbers.
  - Alerts: `HighLatencyP95` (p95 > 1 s for 1 m), `HighErrorRate` (5xx > 5% for 1 m) and `TargetDown`. They are visible at `/api/v1/alerts`. There is no Alertmanager locally.
  - The Grafana dashboard JSON is generated by `observability/grafana/build_dashboards.py`. A unit test fails if the committed JSON is stale, or if any panel or rule queries a metric that no code emits.
  - CI runs `promtool check config` (which also checks the rules) and `alloy fmt`.
- **Consequences:** Dashboard changes are reviewable diffs, and broken panels are caught before anyone opens Grafana.

---

## D-025: API metrics, the agent metrics contract, and pinning FastAPI 0.115.x

- **Date:** 2026-11-08 (Phase 3)
- **Decision:**
  - The API exposes the same RED metric names and labels as the workloads (`service="opspilot-api"`), plus domain metrics: incidents created and status changes, investigations opened and finished, investigation duration, and failed DB transactions by operation.
  - Domain counters increment only after a successful commit, so rolled-back work is never counted.
  - Agent, RAG, MCP and LLM metrics (`opspilot_tool_calls_total`, `opspilot_rag_retrieval_duration_seconds`, `opspilot_agent_execution_duration_seconds`, `opspilot_llm_errors_total`, `opspilot_llm_tokens_total`) are declared now as a contract. Their dashboard panels exist and stay empty until Phases 4–6 emit them.
  - Every API log line now carries `service` and `version`.
- **Pinning:** FastAPI is pinned to `>=0.115,<0.116` in the API and workloads. The Docker build had pulled FastAPI 0.162, which puts the un-prefixed route object in `scope["route"]`. That silently changed the route label from `/api/incidents/{incident_id}` to `/incidents/{incident_id}`. `test_metrics_use_full_route_template` guards against this on future upgrades.

---

## D-026: Monitored services come from target files; external projects are a custom, opt-in option

- **Date:** 2026-11-08 (between Phase 3 and Phase 4)
- **Context:** The master spec's end goal (section 2) is that OpsPilot monitors the owner's separately deployed project. The demo workloads are kept only as a rough evaluation test bed.
- **Decision:**
  - `prometheus.yml` no longer lists any service. A `services` job uses `file_sd_configs` over `observability/prometheus/targets/*.yml`, re-read every 30 s.
  - The demo workloads are one file, `demo-workloads.yml`, labelled `project=opsdemo`.
  - Connecting an external project is the custom option: `observability/scripts/add_monitored_project.py --project <name> --target host:port` writes `<name>.yml` with `project` and `environment` labels. `external-project.yml.example` documents the format.
  - Recording rules aggregate `by (project, service)`, so demo and real services never blend.
  - Onboarded target files are git-ignored by default because they hold internal hostnames. The project names `opspilot` and `opsdemo` are reserved.
- **Verified:** adding a target file made Prometheus scrape it within about 30 s without a restart, and deleting the file stopped the scraping.
- **Still to do (spec: by Phase 12/15):**
  - Log shipping for external projects.
  - Registering them as workloads in the database.
  - Authenticated scraping (basic auth/TLS) for targets outside the local network.

---

## D-027: Local embeddings with BAAI/bge-small-en-v1.5 (384 dimensions)

- **Date:** 2026-11-08 (Phase 4)
- **Context:** D-016 deferred the embedding dimension until a model was chosen. No LLM/API key is configured, unit tests must not need a live model, and every environment must embed identically.
- **Alternatives:**
  - OpenAI `text-embedding-3-small`: needs a key, costs money and sends documents to a third party.
  - sentence-transformers: pulls in PyTorch, which multiplies the image size.
  - Larger bge or e5 models: better quality, but slower on CPU for a corpus this small.
- **Decision:** `BAAI/bge-small-en-v1.5` through `fastembed` (ONNX Runtime, CPU), pinned with `fastembed>=0.7.4,<0.8`.
  - Queries use bge's retrieval instruction prefix.
  - Vectors are L2-normalised.
  - The model is baked into the API image (`/opt/models`), so containers never download it at runtime.
- **Alternative providers:**
  - `EMBEDDING_PROVIDER=openai` uses `text-embedding-3-small` with `dimensions=384`, so the schema still fits.
  - `EMBEDDING_PROVIDER=hashing` is a deterministic lexical embedder for tests and offline work only.
  - Switching provider requires a full re-ingest. Each document records which `embedding_model` produced its vectors, and a model change triggers re-embedding automatically.
- **Consequences:** The column is `vector(384)`. The API image is about 1.2 GB, mostly existing Python dependencies plus about 130 MB of model.

---

## D-028: RAG pipeline parameters and storage

- **Date:** 2026-11-08 (Phase 4). These are actual implementation values (spec section 43).
- **Sources:** Markdown with YAML front matter in `docs/knowledge/`, organised as `runbooks/`, `architecture/`, `troubleshooting/`, `procedures/` and `postmortems/`. The corpus is 10 documents producing 43 chunks.
  - Malformed files are reported and never ingested.
  - If a previously ingested file breaks, its last good version is kept.
- **Cleaning:**
  - normalise newlines
  - strip HTML comments and control characters
  - collapse runs of blank lines
- **Chunking:**
  - Heading-aware: sections at `#`/`##`/`###` carry a heading trail into each chunk.
  - Paragraphs are packed up to 300 words with 40 words of overlap. Sizes are counted in words, not model tokens; a chunk is at most 340 words.
  - The embedded text is "title > section" plus the content.
- **Storage:**
  - Tables: `documents` (source unique, doc_type, `services text[]` with a GIN index, content hash, metadata JSONB) and `document_chunks` (`vector(384)`, unique `(document_id, chunk_index)`).
  - Index: HNSW (`m=16`, `ef_construction=64`) with `vector_cosine_ops`.
  - Filtered queries use `hnsw.iterative_scan = relaxed_order` (pgvector 0.8), so filters don't starve the ANN result set.
- **Retrieval:**
  1. Cosine similarity over a candidate pool of 4×top_k, after the SQL metadata filters (doc type, service overlap).
  2. Drop results below the threshold of 0.55.
  3. Keep at most 2 chunks per document.
  4. Return the top 5.
  - An empty result means "no relevant knowledge". An unavailable model or database is reported as 503 `KNOWLEDGE_UNAVAILABLE`, never as empty.
- **Provenance:** every result carries source, title, doc type, services, section, chunk index (`citation = source#chunk-N`) and score.
- **Prompt injection (spec 31):** retrieved text is treated as data.
  - Instruction-like passages are flagged `possible_prompt_injection`.
  - Context for the LLM is fenced in `<reference>` blocks behind an "untrusted reference material" preamble, and a passage cannot close its fence early.
  - The RAG layer has no path to tools or I/O; a test asserts that retrieving a hostile chunk executes nothing.
- **Measured quality** (real model, 15 labelled questions in `tests/fixtures/rag_eval.yml`, `make rag-eval`):

  | Metric | Value |
  |---|---|
  | hit@1 | 0.733 |
  | hit@5 | 1.0 |
  | MRR | 0.856 |
  | Recall above the threshold | 1.0 |
  | Off-topic questions returning nothing | 3 of 3 |

  Observed scores: relevant questions top out around 0.70–0.82; off-topic questions around 0.40–0.43. The threshold sits between the two. The `pytest -m evaluation` test fails on regressions below hit@5 0.9 or MRR 0.75.
