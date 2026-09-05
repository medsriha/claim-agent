.DEFAULT_GOAL := help
.PHONY: help up down logs install hooks run mock seed-memory clear-memory seed-analysis clear-analysis \
        analysis-figures test lint format typecheck check ui-install ui-dev ui-build ui-lint

help: ## Show available commands
	@grep -E '^[a-z-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN{FS=":.*?## "}{printf "  %-14s %s\n", $$1, $$2}'

# The demonstration, in containers. Everything below this block runs on the machine
# itself instead, which is what you want while writing code — the reload is faster than
# a rebuild.
up: ## Build and run the whole demo in containers — the screen is on :5173
	docker compose up --build

down: ## Stop the demo. Add `-v` by hand to throw away what it remembered
	docker compose down

logs: ## Follow the containers' logs
	docker compose logs -f

install: ## Install dependencies into .venv
	uv sync

hooks: ## Install git pre-commit hooks
	uv run pre-commit install --install-hooks --hook-type pre-commit --hook-type pre-push

run: ## Run the API with reload
	uv run uvicorn claim_agent.app:app --reload

mock: ## Run the ShipBob stand-in on port 8080
	uv run uvicorn tools.shipbob_mock:app --port 8080 --reload

seed-memory: ## Write one invented rep correction, so the demo has history to show
	uv run python -m tools.seed_merchant_memory

clear-memory: ## Remove every rep correction again
	uv run python -m tools.seed_merchant_memory --clear

seed-analysis: ## Invent a year of rep decisions, so the analysis screen has something to show
	uv run python -m tools.seed_analysis_history

clear-analysis: ## Remove every invented decision again
	uv run python -m tools.seed_analysis_history --clear

analysis-figures: ## Remake the invented figures the analysis screen shows
	uv run python -m tools.seed_analysis_history --figures web/src/analysis/demoFigures.json

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

# The UI is deliberately outside `check` and outside CI. It is a demo artifact, and
# keeping Node out of the push loop keeps that loop fast. Nothing catches a broken UI
# for you — run `make ui-lint` yourself before pushing a change to `web/`.
ui-install: ## Install the UI's dependencies
	cd web && npm install

ui-dev: ## Run the UI, proxying the API on port 8000
	cd web && npm run dev

ui-build: ## Build the UI for production
	cd web && npm run build

ui-lint: ## Check the UI's lint and types
	cd web && npm run lint && npm run typecheck
