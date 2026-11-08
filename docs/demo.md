# Flagship demo

A 30–60 second walk-through of what OpsPilot is for: a service gets slow, and
OpsPilot explains why from live telemetry and the runbooks. It never touches
the service itself.

```
inject latency → traffic → Prometheus/Loki capture it → "Why is checkout latency high?"
  → agent (RAG + read-only MCP tools) → evidence → diagnosis → recommendation
```

## Before you present (about 3 minutes)

```bash
ENABLE_INCIDENT_LAB=true ENABLE_FAILURE_INJECTION=true docker compose up -d
docker compose exec api python -m app.rag.ingest   # once, or after editing docs/knowledge
make demo-prepare                                  # healthy services + a fresh baseline
```

`make demo-prepare` resets every demo service to healthy and keeps sending
normal traffic until checkout's p95 has been healthy for a minute. A step
change can only be seen against a baseline, and the 1-minute p95 only forgets a
previous incident while new requests keep arriving.

## The demo in the UI

Open http://localhost:3001/incident-lab.

| Step | What to do | What the audience sees |
|------|------------|------------------------|
| 1 | Choose **Inject checkout latency**, then confirm. | The confirmation names the target, the blast radius (demo checkout only) and how to revert. |
| 2 | Choose **Send traffic** (60 requests). | The activity log records both actions with correlation IDs. |
| 3 | Wait for the **p95 latency** chart to rise, usually 15–35 s. | checkout turns Degraded. That status comes from Prometheus, not from the button press. |
| 4 | Choose **Open in Investigation**, then **Investigate**. | The question is pre-filled: "Why is checkout latency high?" |
| 5 | Walk through the result. | See below. |
| 6 | Choose **Reset to healthy**. | Run `make demo-prepare` before presenting it again. |

What the investigation shows:

- **Observed facts:**
  - checkout p95 rose from about 200 ms to about 2 s at a specific minute;
  - database query p95 stayed flat since then;
  - payments and users are healthy;
  - there are `request_slow` warnings with no slow queries.
- **Retrieved evidence:** the latency troubleshooting guide, and why the time is inside the service.
- **Hypothesis:** application latency, supported. Database and dependency causes don't fire, because their evidence is measured healthy.
- **Diagnosis:** "checkout's own request handling became slow (its database and dependencies are healthy)", at 65% estimated confidence.
  - It is a diagnosis by elimination, so it stays below the 95% a release-plus-slow-query case reaches.
  - The breakdown shows exactly why.
- **Recommendation:** profile the request path and check recent config or feature-flag changes; scale out if users are affected. This is manual: OpsPilot runs read-only.

## The same path from the command line

```bash
make demo          # inject, traffic, wait for Prometheus, ask, verify, reset
make demo-reset    # back to healthy at any time
```

`make demo` prints each stage with its duration and the diagnosis, plus a link
to the investigation in the UI. It exits non-zero if any stage fails or the
diagnosis is not the expected one.

It refuses to start unless checkout has been healthy for the last minute
(normal p95, no 5xx). It only counts metric points measured after its own
injection. Together these stop an earlier incident from being mistaken for the
new one.

Other failure modes: `python scripts/demo.py run --mode db` (expects database
degradation) and `--mode errors` (expects application errors).

## Measured on the development laptop (8 November 2026)

- **Repeatability:** 7 consecutive `prepare` + `run` cycles, 6 passed.
  - Injection to diagnosis took 14–36 s; the investigation itself took 0.5–9 s.
  - The one failure happened while a payments-errors injection from the Incident Lab was still in effect. The baseline check now also requires no recent 5xx errors.
- **Other modes**, one run each:
  - `--mode db`: database degradation at 90%, 35 s injection to diagnosis.
  - `--mode errors`: application errors at 90%, 36 s.
- **Spec scenario before this phase:** the same scenario was diagnosed as "database queries became slow" (40%). Two causes:
  - slow-query logs from an earlier database test still sat in the agent's lookback window;
  - no rule covered latency inside the service.

## Troubleshooting

| Symptom | Cause and fix |
|---------|---------------|
| `not at a healthy, recent baseline` | A previous incident is still in the 1-minute window, or there has been no recent traffic. Run `make demo-prepare`. |
| `incident lab disabled` | Start the API with `ENABLE_INCIDENT_LAB=true`. |
| Inject does nothing, or checkout stays Healthy | Start the workloads with `ENABLE_FAILURE_INJECTION=true`. |
| p95 never rises | Check that traffic is flowing (the activity log) and that Prometheus is up (System Status). |
| Unexpected diagnosis | Another service may be degraded, for example a payments injection left on. Choose **Reset to healthy** and run `make demo-prepare`. |
