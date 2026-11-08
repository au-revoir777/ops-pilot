# =============================================================================
# OpsPilot â€” Makefile
# =============================================================================
.PHONY: help setup dev up down build test test-unit test-integration test-system \
        test-evaluation test-db-up test-db-down migrate lint scan ingest incident cloud-up cloud-down clean

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
ingest: ## Ingest documents into RAG knowledge base
	$(PYTHON) -m app.rag.ingest

# ---------------------------------------------------------------------------
# Incident Lab
# ---------------------------------------------------------------------------
incident: ## Inject a test incident (default: latency)
	@echo "Injecting checkout latency incident..."
	curl -s -X POST http://localhost:8080/admin/failure -H "Content-Type: application/json" \
		-d '{"mode": "latency"}' | python -m json.tool

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
