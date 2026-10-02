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

## Testing

```bash
make test          # All tests
make test-unit     # Unit tests only
make test-integration  # Integration tests
make test-system   # System / E2E tests
make test-evaluation   # Agent evaluation
make lint          # Linting
```

## Project Status

- [x] Phase 0: Project Bootstrap
- [ ] Phase 1: Database & Core Backend
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
