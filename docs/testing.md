# Testing strategy

OpsPilot is tested as a pyramid. Many fast unit tests pin down the logic. Fewer
integration tests prove the parts work on real PostgreSQL and real protocols. A
handful of system tests drive the running stack end to end. A separate
evaluation tier measures how good the agent's answers are, not just whether the
code runs.

Every Python test carries exactly one tier marker. The root `conftest.py`
fails collection otherwise, so a test can never silently run in the wrong tier,
or in none.

## The tiers

All numbers below were measured on 8 November 2026 on the development laptop.

| Tier | Python | Frontend | Needs | Runtime | Command |
|------|--------|----------|-------|---------|---------|
| Unit | 309 | 64 Vitest + 237 contrast checks | nothing | ~20 s + ~30 s | `make test-unit` |
| Integration | 67 | | `postgres-test` (`make test-db-up`) | ~35 s | `make test-integration` |
| System | 11 | 16 Playwright (8 of them axe scans) | the running Compose stack | ~4 min + ~5 min | `make test-system` |
| Evaluation | 19 | | nothing; the retrieval check needs `postgres-test` and the local model | ~15 s | `make test-evaluation` |

`make test` runs unit + integration, Python and frontend. That is the gate
for every change.

`make` is not installed on this Windows laptop. Every target calls
`python scripts/run_tests.py <tier>`, which gives the same result on any OS
(`--no-web` skips the Node.js steps).

### Unit: logic, in isolation

No network, no database, no containers. External edges are faked at the
transport (httpx `MockTransport`, fake MCP sessions, `AsyncMock` repositories),
so the code under test is the real code.

- **API** (`apps/api/tests/unit`):
  - settings and the `_test` database guard;
  - health probes and request IDs;
  - error envelopes that never leak internals;
  - metrics labels;
  - service state machines and transaction boundaries;
  - the incident-lab allow-list;
  - the UI endpoints.
- **Agent:**
  - graph transitions and bounds (max steps, rounds, tool calls, timeout);
  - planner and evidence extraction;
  - the confidence formula;
  - every recommendation path;
  - the LLM providers' request shapes, including that a failed call never echoes the API key;
  - the MCP client allow-list;
  - report rendering.
- **RAG:**
  - loader, cleaner and chunker;
  - embedders and ranking;
  - prompt-injection flagging;
  - the fenced context, which hostile text cannot close early.
- **MCP tools and demo workloads** (`mcp/tests`, `workloads/tests`): tool schemas and validation, failure injection, workload endpoints.
- **Observability config** (`tests/observability`):
  - scrape targets match Compose;
  - recording rules and dashboards query only emitted metrics;
  - alerts carry a severity;
  - ports are bound to localhost;
  - the external-project onboarding script.
- **Scripts** (`tests/scripts`): the demo runner's safeguards and the test runner.
- **Frontend** (`apps/web/tests/unit`, Vitest):
  - formatters and credential redaction;
  - zod contracts parsed against real API payloads;
  - the epistemic model (section order, unsupported-claim flags);
  - components;
  - the security test that malicious HTML or Markdown renders inert.
  - Plus the WCAG contrast check of every palette.

### Integration: real infrastructure, one boundary at a time

- **Database** (`test_migrations`, `test_persistence`):
  - upgrade from empty, downgrade and re-upgrade;
  - models match migrations;
  - constraints, cascades and N+1 checks on real PostgreSQL 16 + pgvector.
- **API over the database** (`test_api`, `test_investigation_api`):
  - HTTP → service → database → agent;
  - synchronous and background runs, timeouts and crashes;
  - history filters (wildcards in search are literal);
  - correlation IDs stored for audit.
- **RAG** (`test_rag_pipeline`): ingest → pgvector → retrieval, idempotency, pruning, filters.
- **MCP protocol** (`mcp/tests/test_mcp_protocol`): the real MCP server and client over Streamable HTTP, including auth.
- **Workloads** (`workloads/tests/test_workload_integration`): checkout calling payments and users for real.

Each test runs inside a transaction that is rolled back, so tests never
see each other's data. The database name must end in `_test`, or the
fixtures refuse to connect.

### System: the running stack, as a user sees it

- `tests/system/test_demo_scenario.py` is **the primary system test**: the spec's flagship scenario through the public API.
  1. Inject latency into checkout and generate traffic.
  2. Wait for Prometheus to show it.
  3. Ask "Why is checkout latency high?".
  4. Require the diagnosis `application_latency`, backed by facts, retrieved evidence and a recommendation.
- `test_mcp_stack`, `test_observability_stack`: MCP tools against live Prometheus, Loki and the API; the metrics and logs pipeline; Grafana provisioning.
- **Playwright** (`apps/web/tests/e2e`):
  - the same flagship flow through the UI;
  - degraded mode, with MCP and API outages intercepted;
  - read-only indicator, command palette and keyboard shortcuts;
  - security headers;
  - axe-core WCAG 2.1 A/AA scans of all six pages in all four palettes, light and dark.

System tests need the stack:

```bash
ENABLE_INCIDENT_LAB=true ENABLE_FAILURE_INJECTION=true docker compose up -d
make demo-prepare
make test-system
```

### Evaluation: are the answers right?

- `tests/evaluation/test_agent_evaluation.py`: 16 recorded incident scenarios.
  - They run through the real agent graph with simulated MCP and RAG results on a fixed clock.
  - Each scenario is its own test, so a regression names the incident type it broke.
  - A suite test enforces the aggregate thresholds: root cause and service accuracy at least 0.9, evidence grounding at least 0.9, tool selection 1.0, unsupported claims 0.
  - Results go to `tests/evaluation/results/latest.json`.
  - Current results: 16/16 correct, grounding 1.0, unsupported claims 0.
- The scenarios cover:
  - release + database regression, database-only slowness, dependency failures, release-induced and application errors;
  - an old release, a release after the onset;
  - a healthy service, an unknown service;
  - Loki, Prometheus or the knowledge base down;
  - a timeout cascade, poisoned knowledge;
  - the demo's latency case, with and without a recovered database incident in the window.
- `test_rag_quality.py`: retrieval quality with the real local embedding model (hit@k, MRR) on `tests/fixtures/rag_eval.yml`.
- A determinism test runs the same scenario twice and requires identical results.

**Caveat:** the agent scenarios were written together with the rules. A perfect
score shows the rules do what they claim; it does not show they generalise to
unseen incidents. Unseen behaviour is covered by the live system tests and by
the evaluation set growing from real incidents.

## Prompt injection is tested at every layer

| Layer | Test | What it proves |
|-------|------|----------------|
| Retrieval | `test_rag.py::TestPromptInjectionDefence` | Instruction-like text is flagged. Normal runbooks are not. The fenced context cannot be closed early. Retrieval executes nothing. |
| Agent | evaluation scenario `poisoned-knowledge`, `test_agent.py` | The diagnosis is unchanged, no forbidden tool is called, and a flagged passage earns no confidence and is never cited. |
| End to end | `integration/test_prompt_injection_e2e.py` | A hostile runbook goes through ingest, pgvector, the real retriever, the agent, the HTTP API and storage. It is retrieved and flagged, only allow-listed tools run, the diagnosis follows telemetry, and the flag is kept in the stored evidence. |
| UI | `apps/web/tests/unit/security.test.tsx` | Malicious HTML or Markdown in documents, logs, model text and tool output renders as inert text: no elements, no script, no action. |

## Deterministic fixtures

- **Agent scenarios:** `apps/api/app/agents/scenarios/cases.json` replays tool results on a fixed clock (`simulation.NOW`). No LLM is involved (`LLM_PROVIDER=none`).
- **Embeddings:** integration tests use the hashing embedder, so CI needs no model download. The real model is measured only in the evaluation tier.
- **Workloads:** `FAILURE_SEED` makes injected failures reproducible.
- **Frontend fixtures:** `apps/web/tests/fixtures/*.json` are real API payloads exported by `scripts/export_fixtures.py` (`make web-fixtures`). A backend shape change fails the zod contract tests.
- **Database:** a disposable `postgres-test` on tmpfs; every test is rolled back.

## Coverage

`make coverage` runs unit + integration with branch coverage:

- **Overall:** 88.4% (lines 89.9%, branches 79.5%).
- **Lowest on purpose:** the live-stack CLIs (`app/agents/run.py`, `app/rag/evaluate.py`), which are exercised by system and evaluation runs, not unit runs. Also `app/db/session.py`'s engine lifecycle, which runs in the app's lifespan.
- **Not measured:** frontend coverage (no Vitest coverage provider is installed).

Coverage is a map of what is untested, not a target. The tiers above are the
argument.

## What is not tested, honestly

- **LLM-written summaries** against a real provider: the tests use stubs, and the summary is labelled as model-written in the UI.
- **Load and soak behaviour:** Phase 17.
- **AWS deployment:** Phase 15.
- **Real third-party incident data:** the evaluation scenarios are synthetic.
