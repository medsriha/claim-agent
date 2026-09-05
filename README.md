# Damaged-in-Transit Claims Agent

Backend service that investigates ShipBob damaged-in-transit claims and returns a structured
report plus a drafted merchant email. The system recommends; a representative decides — nothing
is sent and no money moves without human approval.

## Run it

Requires Docker. `ANTHROPIC_API_KEY` is needed to investigate a claim; without one the service
still starts and still screens them.

```bash
cp .env.example .env      # add ANTHROPIC_API_KEY
docker compose up --build
```

| | |
|---|---|
| Screen | <http://localhost:5173> |
| API and its docs | <http://localhost:8000/docs> |
| ShipBob stand-in | <http://localhost:8080/cases> |

The screen forwards API requests to the service, so the browser sees one origin. First build
takes a few minutes; after that it starts in seconds.

## Stop it

```bash
docker compose down       # add -v to drop what the service remembered
```

Reports, decisions, past claims and merchant corrections live in a volume and survive a
restart. The admin panel has the same reset.

## Tests

```bash
docker compose run --rm api pytest
```

## Working on the code

The containers run the demo; an edit means a rebuild. Working on it directly needs
[uv](https://docs.astral.sh/uv/) and Node:

```bash
uv sync                                       # dependencies
uv run uvicorn claim_agent.app:app --reload   # the API
uv run uvicorn tools.shipbob_mock:app --port 8080 --reload   # the ShipBob stand-in
cd web && npm install && npm run dev          # the screen
```

Before pushing, run what CI runs — `uv run ruff check .`, `uv run ruff format --check .`,
`uv run mypy` and `uv run pytest` — and, for a change to `web/`, `npm run lint` and
`npm run typecheck` in there, which nothing else checks for you.
