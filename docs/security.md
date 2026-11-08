# Security

OpsPilot investigates production systems, so the question is not only "is the
code safe" but "what could an attacker make the agent do". The core design
choice answers most of it: **OpsPilot is read-only.** It has no endpoint, tool
or credential that can change a monitored system. Everything below either keeps
it that way or limits what a read-only system can still leak or waste.

Status as of 8 November 2026 (Phase 11). "Implemented" means it exists and is
tested; "planned" names the phase that adds it.

## Threat model

| Threat | Attack surface | Risk | Mitigation (implemented) | Residual risk |
|--------|----------------|------|--------------------------|---------------|
| **Prompt injection** | Retrieved runbooks and postmortems, log lines, any text that reaches the agent | An instruction in data is treated as a command | The agent's decisions are deterministic rules over typed signals, not free-text instructions. Retrieved text never selects tools. The optional LLM only writes a labelled summary, and gets data inside a fence it cannot close. Instruction-like chunks are flagged, earn no confidence and are never cited. Tested at four layers (see `docs/testing.md`). | Rules can't cover every phrasing. A future LLM-driven planner would need the same allow-list and approval guarantees re-proven. |
| **Malicious RAG content** | `docs/knowledge` and anything ingested into pgvector | A poisoned document steers the diagnosis | The same flagging. The diagnosis follows telemetry, not documents: knowledge support is capped at +0.10 and lost when flagged. The end-to-end test ingests a hostile runbook through the real pipeline. | Someone with write access to the knowledge base can still add subtly wrong but un-flagged advice. Knowledge changes should go through review, like code. |
| **Tool abuse / excessive agent permissions** | The agent's MCP client | The agent calls something destructive | A client-side allow-list of six read-only tools (`ToolNotAllowed` otherwise). The MCP server itself exposes only those six, each with typed, bounded inputs: PromQL ≤ 2,000 characters, time range and point budgets, log line limits. There are no write tools anywhere. Bounds: 15 graph steps, 2 rounds, 16 tool calls, 120 s timeout. | Read-only PromQL can still be expensive. The bounds limit it, but a deliberately heavy query inside them could load Prometheus. |
| **Compromised MCP server** | MCP over Streamable HTTP on the internal network | A rogue server returns false data or tries to escalate | Results are typed (pydantic) and treated as data. A tool error or timeout becomes "unavailable" and lowers confidence; it never crashes the agent or becomes an instruction. The server is optionally protected by a bearer token. | A compromised server can lie, which would mislead a diagnosis. The UI shows every fact's tool call so a human can check. The token is optional locally; production (Phase 15) should require it. |
| **Unauthorized remediation** | Any path from a recommendation to an action | The agent changes production | No remediation endpoint exists, so recommendations are text. The UI's approval flow ends in copyable instructions marked as manual. The read-only status is shown in the UI and in `/api/config`. The incident lab can only reach the demo workloads in `LAB_TARGETS`; a monitored external project is never in that list. | If remediation is added later, it needs authentication, an approval record and an audit trail first. That is a design rule, not code yet. |
| **API abuse** | The HTTP API | Unauthenticated callers start costly investigations or toggle lab failures | `API_KEY` is enforced on every `/api/*` route (constant-time compare), and production refuses to start without it. The web UI adds the key server-side, so it never reaches the browser. At most 4 concurrent agent runs (configurable); more get 429. Every input is validated by pydantic (lengths, patterns, ranges). Errors never leak internals. | One shared key, not per-user identities or roles: proper authentication is planned with the AWS deployment (Phase 15). There is no per-client rate limit, only the concurrency cap. Locally the key is optional, and the API is open on 127.0.0.1. |
| **Credential leakage** | Settings, logs, error responses, the UI, the repository | Keys or passwords are exposed | Secrets are `SecretStr` settings from the environment only, so they never appear in `repr`, logs or tracebacks. Structlog redaction masks secret-named fields and credentials inside strings (API and MCP). Error bodies are type-only and never echo upstream responses. LLM errors never include the key (tested). The UI redacts credential-looking text in logs and tool output. `scripts/secret_scan.py` and a test fail on committed secrets. No `.env` is tracked. | Pattern-based scanning misses secrets in unusual formats. A dedicated scanner in CI is planned for Phase 13. |
| **Exposed database** | PostgreSQL | Direct access to incidents and the knowledge base | Postgres is on a dedicated `backend` network that only `migrate` and `api` join. Its published port binds to 127.0.0.1. Credentials come from the environment, and the test database refuses any name not ending in `_test`. | The local default password (`opspilot_dev`) is a convenience for development only. Production uses RDS with a managed secret (Phase 14/15). |
| **Container vulnerabilities** | Images and their dependencies | A known CVE in a base image or library | All four images run as non-root with health checks. Compose adds `cap_drop: [ALL]` and `no-new-privileges` to every OpsPilot container. Dependencies are scanned (`make audit`, `make scan`, see results below). | Base images age, so scans must run in CI on every build (Phase 13). One accepted dependency finding (Pillow, below). |
| **Browser-side attacks** | The web UI | XSS through retrieved or model text; clickjacking | Untrusted text renders as React text nodes only, and `react/no-danger` is an ESLint error. Content-Security-Policy is `default-src 'self'`, `connect-src 'self'`, `frame-ancestors 'none'`. Also `X-Frame-Options: DENY` and `nosniff`. CORS is closed by default because the browser only talks to its own origin. | The CSP allows `'unsafe-inline'` scripts and styles, which Next.js needs without a nonce pipeline. Nonces are a possible improvement. |
| **Arbitrary shell access** | Service code | Command execution | No service calls a shell, `eval`, `exec` or unsafe deserialisation; a static test enforces it. Containers have no added capabilities. | None known in OpsPilot code; dependencies are covered by scanning. |

## Controls by area

| Area | Implemented | Planned |
|------|-------------|---------|
| Authentication | Shared API key on `/api/*`, required in production; added server-side by the web proxy | Per-user identity (OIDC) and roles: Phase 15 |
| Authorization | Read-only by construction; incident lab limited to an allow-list of demo targets; agent tool allow-list | Role-based access if write actions ever exist |
| Secrets | Environment only, `SecretStr`, log redaction, secret scan, nothing in the image | AWS Secrets Manager / SSM: Phase 14 |
| Input validation | Pydantic on every request body, query and path; bounded MCP tool inputs; request IDs accepted only if short and URL-safe | |
| Network | Every port on 127.0.0.1; database on its own network; web → API through a same-origin proxy | Private subnets and security groups: Phase 14 |
| Containers | Non-root users, health checks, `cap_drop: [ALL]`, `no-new-privileges`, OS security updates at build, no compiler in the API image, no npm in the web image | Read-only root filesystems where the runtime allows it |
| IAM | Not applicable locally | Least-privilege task roles, one per service, no wildcard actions: Phase 14 |
| Supply chain | Pinned version ranges, unused dependencies removed, test tools kept out of runtime images, `make audit`, `make scan`, npm lockfile | Scans and secret scanning in CI: Phase 13 |
| Logging | Structured JSON, correlation IDs, redaction, no request bodies logged | |
| Human approval | Recommendations are proposals; the UI states execution is manual | An approval record and audit trail before any write action |

## Scan results (8 November 2026)

| Scan | Before Phase 11 | After |
|------|-----------------|-------|
| `pip-audit`: API | Starlette 0.46.2: 7 advisories (multipart, Range header, Host-header URL reconstruction, StaticFiles on Windows, HTTPEndpoint method lookup, form limits, path validation); Pillow 11.3.0 | Starlette fixed by FastAPI 0.162 / Starlette 1.10. **Pillow 11.3.0 remains** (6 advisories; see accepted risks). |
| `pip-audit`: MCP, workloads | Starlette (workloads) | No known vulnerabilities |
| `npm audit --omit=dev` | PostCSS 8.4.31 bundled in Next.js (1 high, 1 moderate) | 0 vulnerabilities (npm `overrides` pins PostCSS 8.5.32) |
| Trivy, API image (HIGH/CRITICAL, fixable) | 44: Pillow 41, zlib 2, langchain-core, langgraph-sdk, wheel, jaraco.context | 41, all Pillow. The LangChain packages were removed, LangGraph upgraded, OS and packaging tools updated. One setuptools 70.3.0 report remains; it comes from a base-image layer whose files are deleted (setuptools 84.2.1 is what is installed; verified no 70.3.0 metadata in the final filesystem). |
| Trivy, MCP and workload images | 2 each (zlib) + wheel, jaraco.context | 1 each: the same stale setuptools layer report |
| Trivy, web image | 7 OS (OpenSSL, musl), plus 22 in the base image's bundled npm | 0. `apk upgrade`, and npm, Yarn and Corepack removed from the runtime image. |
| Secret scan | n/a | 0 findings across 270+ tracked files |

### Accepted risks

- **Pillow 11.3.0** (API image).
  - `fastembed` requires Pillow < 12, and imports it at module load, so it can't be removed.
  - The advisories are in image decoders (TIFF, FlashPix, JPEG and others). OpsPilot embeds text only and never opens an image, so that code is unreachable from any input.
  - Revisit when fastembed allows Pillow 13, or replace the embedder.
- **setuptools 70.3.0 (Trivy only):** a scanner false positive from a deleted base-image layer, as above.

## How to check

```bash
make secret-scan   # before every push
make audit         # Python + npm known vulnerabilities (pip-audit must be installed)
make scan          # Trivy on the four local images, via Docker
pytest tests/security apps/api/tests/unit/test_security.py   # the controls above, as tests
```
