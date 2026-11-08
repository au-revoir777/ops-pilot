# =============================================================================
# OpsPilot â€” Makefile
# =============================================================================
.PHONY: help setup dev up down build test test-unit test-integration test-system \
        test-evaluation test-db-up test-db-down migrate lint scan ingest ingest-docker rag-eval incident traffic cloud-up cloud-down clean

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
	pip install -r apps/api/requirements.txt
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
test: ## Run all tests
	pytest

test-unit: ## Run unit tests only
	pytest -m unit -v

test-integration: ## Run integration tests (needs: make test-db-up)
	pytest -m integration -v

test-db-up: ## Start the disposable integration-test database (127.0.0.1:5433)
	$(COMPOSE) --profile test up -d --wait postgres-test

test-db-down: ## Stop and discard the integration-test database
	$(COMPOSE) --profile test rm -sf postgres-test

migrate: ## Apply database migrations (uses DATABASE_URL)
	cd apps/api && alembic upgrade head

test-system: ## Run system / E2E tests
	pytest -m system -v

test-evaluation: ## Run agent evaluation tests
	pytest -m evaluation -v

# ---------------------------------------------------------------------------
# Quality
# ---------------------------------------------------------------------------
lint: ## Lint with Ruff
	ruff check .
	ruff format --check .

lint-fix: ## Auto-fix lint issues
	ruff check --fix .
	ruff format .

scan: ## Security scan Docker images with Trivy
	trivy image opspilot-api:latest
	trivy image opspilot-mcp:latest
	trivy image opspilot-web:latest

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
