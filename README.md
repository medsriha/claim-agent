# Damaged-in-Transit Claims Agent

Backend service that investigates ShipBob damaged-in-transit claims and returns a structured
report plus a drafted merchant email. The agent recommends and a representative decides.

How it is built, and how the agent thinks and decides, is in [ARCHITECTURE.md](ARCHITECTURE.md).

## Run it

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

## Tests

```bash
docker compose run --rm api pytest
```

## Demo

<img src="media/demo.webp" alt="Walkthrough of a claim moving from investigation to a representative's decision" width="800">
