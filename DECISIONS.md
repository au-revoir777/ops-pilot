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
