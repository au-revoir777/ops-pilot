# =============================================================================
# OpsPilot â€” Makefile
# =============================================================================
.PHONY: help setup dev up down build test test-unit test-integration test-system \
        test-evaluation test-db-up test-db-down test-web test-web-e2e coverage demo demo-prepare demo-reset lint lint-web scan audit secret-scan ingest ingest-docker rag-eval incident traffic cloud-up cloud-down clean

COMPOSE := docker compose
PYTHON  := python

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2}'

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------
setup: ## Initial project setup
	@echo "==> Copying .env.example â†’ .env (if missing)"
	@if not exist .env copy .env.example .env
	@echo "==> Installing Python dependencies"
	pip install -r requirements-dev.txt
	@echo "==> Setup complete"

# ---------------------------------------------------------------------------
# Development
# ---------------------------------------------------------------------------
dev: ## Start API in development mode
	cd apps/api && uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# ---------------------------------------------------------------------------
# Docker
# ---------------------------------------------------------------------------
up: ## Start full stack via Docker Compose
	$(COMPOSE) up -d --build

down: ## Stop all containers
	$(COMPOSE) down -v

build: ## Build Docker images
	$(COMPOSE) build

# ---------------------------------------------------------------------------
# Testing
# ---------------------------------------------------------------------------
test: ## Unit + integration tests, Python and frontend (needs: make test-db-up)
	$(PYTHON) scripts/run_tests.py all

test-unit: ## Unit tier: pytest -m unit, Vitest, contrast check (no services needed)
	$(PYTHON) scripts/run_tests.py unit

test-integration: ## Integration tier: real PostgreSQL + in-process servers (needs: make test-db-up)
	$(PYTHON) scripts/run_tests.py integration

test-db-up: ## Start the disposable integration-test database (127.0.0.1:5433)
	$(COMPOSE) --profile test up -d --wait postgres-test

test-db-down: ## Stop and discard the integration-test database
	$(COMPOSE) --profile test rm -sf postgres-test

migrate: ## Apply database migrations (uses DATABASE_URL)
	cd apps/api && alembic upgrade head

test-system: ## System tier: pytest -m system + Playwright against the running stack
	$(PYTHON) scripts/run_tests.py system

test-evaluation: ## Evaluation tier: 16 agent scenarios + retrieval quality
	$(PYTHON) scripts/run_tests.py evaluation

coverage: ## Unit + integration with a coverage report (coverage.xml)
	$(PYTHON) scripts/run_tests.py coverage --no-web

test-web: ## Frontend: type-check, unit/component/security tests, contrast check
	cd apps/web && npm run typecheck && npm test && npm run contrast

test-web-e2e: ## Frontend: Playwright e2e + axe against the running stack (web on :3001)
	cd apps/web && npx playwright test

web-fixtures: ## Re-export real API payloads as frontend test fixtures
	cd apps/api && PYTHONPATH=. $(PYTHON) ../web/scripts/export_fixtures.py

# ---------------------------------------------------------------------------
# Quality
# ---------------------------------------------------------------------------
lint: ## Lint with Ruff
	ruff check .
	ruff format --check .

lint-web: ## Lint the frontend with ESLint
	cd apps/web && npm run lint

lint-fix: ## Auto-fix lint issues
	ruff check --fix .
	ruff format .

TRIVY := docker run --rm -v /var/run/docker.sock:/var/run/docker.sock -v trivy-cache:/root/.cache aquasec/trivy:0.58.1

scan: ## Scan the local images for HIGH/CRITICAL vulnerabilities (Trivy, via Docker)
	$(TRIVY) image --severity HIGH,CRITICAL --ignore-unfixed opspilot-api:local
	$(TRIVY) image --severity HIGH,CRITICAL --ignore-unfixed opspilot-mcp:local
	$(TRIVY) image --severity HIGH,CRITICAL --ignore-unfixed opspilot-workloads:local
	$(TRIVY) image --severity HIGH,CRITICAL --ignore-unfixed opspilot-web:local

audit: ## Known-vulnerability check of Python and npm dependencies
	$(PYTHON) -m pip_audit -r apps/api/requirements.txt -r mcp/requirements.txt -r workloads/requirements.txt
	cd apps/web && npm audit --omit=dev

secret-scan: ## Fail if a tracked file looks like it contains a secret (run before pushing)
	$(PYTHON) scripts/secret_scan.py

# ---------------------------------------------------------------------------
# RAG
# ---------------------------------------------------------------------------
ingest: ## Ingest docs/knowledge into pgvector (uses DATABASE_URL; idempotent)
	cd apps/api && $(PYTHON) -m app.rag.ingest --path ../../docs/knowledge

ingest-docker: ## Ingest the knowledge base from inside the running API container
	$(COMPOSE) exec api python -m app.rag.ingest

rag-eval: ## Measure retrieval quality (hit@k, MRR) against tests/fixtures/rag_eval.yml
	cd apps/api && $(PYTHON) -m app.rag.evaluate --dataset ../../tests/fixtures/rag_eval.yml

# ---------------------------------------------------------------------------
# Incident Lab
# ---------------------------------------------------------------------------
CHECKOUT_URL ?= http://localhost:8080
MODE ?= db
incident: ## Inject a checkout incident: make incident MODE=db|latency|errors|none (needs ENABLE_FAILURE_INJECTION=true)
	curl -s -X POST $(CHECKOUT_URL)/admin/failure -H "Content-Type: application/json" -d '{"mode": "$(MODE)"}'

traffic: ## Send 50 checkout requests (baseline / incident traffic)
	$(PYTHON) workloads/scripts/traffic.py --url $(CHECKOUT_URL) --requests 50

API_URL ?= http://127.0.0.1:8000

demo-prepare: ## Flagship demo, step 1: healthy services + fresh baseline (~3 min, before presenting)
	$(PYTHON) scripts/demo.py prepare --api-url $(API_URL)

demo: ## Flagship demo: inject latency, traffic, ask "Why is checkout latency high?", verify, reset
	$(PYTHON) scripts/demo.py run --api-url $(API_URL)

demo-reset: ## Reset every demo service to healthy
	$(PYTHON) scripts/demo.py reset --api-url $(API_URL)

# ---------------------------------------------------------------------------
# Cloud (AWS)
# ---------------------------------------------------------------------------
cloud-up: ## Deploy to AWS via Terraform
	cd infra/terraform && terraform init && terraform apply -auto-approve

cloud-down: ## Destroy AWS infrastructure
	cd infra/terraform && terraform destroy -auto-approve

# ---------------------------------------------------------------------------
# Cleanup
# ---------------------------------------------------------------------------
clean: ## Remove build artifacts and caches
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .pytest_cache -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .mypy_cache -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name node_modules -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .next -exec rm -rf {} + 2>/dev/null || true
