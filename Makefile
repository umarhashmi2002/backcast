# Retrace — developer workflow
# Run `make help` for the list of targets.

.DEFAULT_GOAL := help
SHELL := /bin/bash

.PHONY: help bootstrap sync lint format typecheck test test-integration \
        db-up db-down db-migrate seed demo race-demo deploy synth clean

help: ## Show this help
	@grep -E '^[a-zA-Z0-9_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| sort | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}'

bootstrap: ## Install uv-managed venv + dev deps + pre-commit
	uv sync --all-extras
	uv run pre-commit install || true

sync: ## Resolve and install dependencies from the lockfile
	uv sync

lint: ## Lint with ruff
	uv run ruff check src tests

format: ## Auto-format with ruff
	uv run ruff format src tests
	uv run ruff check --fix src tests

typecheck: ## Static type-check with mypy
	uv run mypy src

test: ## Run unit tests (excludes integration)
	uv run pytest -m "not integration"

test-integration: ## Run integration tests (requires local CockroachDB: make db-up)
	uv run pytest -m integration

db-up: ## Start a local single-node CockroachDB via docker-compose
	docker compose up -d crdb
	@echo "Waiting for CockroachDB..." && sleep 5
	$(MAKE) db-migrate

db-down: ## Stop and remove the local CockroachDB
	docker compose down -v

db-migrate: ## Apply the schema to the configured database
	uv run python -m retrace.db.migrate

seed: ## Load synthetic incident history for the demo
	uv run python scripts/load_seed_data.py

demo: ## Narrate all five memory mechanisms against the database
	uv run retrace demo

race-demo: ## Action-lease concurrency + crash-safety demo (25 workers, crash & resume)
	uv run python scripts/concurrency_demo.py

synth: ## Synthesize the CDK CloudFormation templates
	cd infra && uv run cdk synth

deploy: ## Deploy the AWS stacks via CDK
	cd infra && uv run cdk deploy --all --require-approval never

clean: ## Remove caches and build artifacts
	rm -rf .pytest_cache .mypy_cache .ruff_cache htmlcov .coverage build dist
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
