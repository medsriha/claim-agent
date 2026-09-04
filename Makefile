.DEFAULT_GOAL := help
.PHONY: help install hooks run test lint format typecheck check

help: ## Show available commands
	@grep -E '^[a-z-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN{FS=":.*?## "}{printf "  %-12s %s\n", $$1, $$2}'

install: ## Install dependencies into .venv
	uv sync

hooks: ## Install git pre-commit hooks
	uv run pre-commit install --install-hooks --hook-type pre-commit --hook-type pre-push

run: ## Run the API with reload
	uv run uvicorn claim_agent.app:app --reload

test: ## Run the test suite
	uv run pytest

lint: ## Check lint and formatting
	uv run ruff check .
	uv run ruff format --check .

format: ## Apply formatting and safe lint fixes
	uv run ruff format .
	uv run ruff check --fix .

typecheck: ## Run mypy
	uv run mypy

check: lint typecheck test ## Everything CI runs
