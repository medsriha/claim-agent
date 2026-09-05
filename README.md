# Damaged-in-Transit Claims Agent

A backend service that investigates ShipBob damaged-in-transit claims and hands a support
representative a structured report and a drafted merchant email. **The system recommends; a
representative decides.** Nothing is sent and no money moves without a person approving it.

This page is about running the demonstration. Everything runs in containers, so there is
nothing to install but Docker.

## What you need

- **Docker Desktop**, running. Nothing else — no Python, no Node.
- **An Anthropic API key**, to investigate a claim. Without one the service still starts and
  still screens claims; asking it to investigate one reports plainly that it cannot.

## Run it

```bash
cp .env.example .env      # then open .env and fill in ANTHROPIC_API_KEY
docker compose up --build
```

The first build takes a few minutes; after that it starts in seconds. When the three
containers report healthy, open the screen:

**<http://localhost:5173>**

Stop it with `Ctrl+C`, or `docker compose down` from another terminal.

## What is running

| | Address | What it is |
|---|---|---|
| **The screen** | <http://localhost:5173> | What a representative uses. Start here. |
| The service | <http://localhost:8000/docs> | The claims API, and its own documentation. |
| ShipBob stand-in | <http://localhost:8080/cases> | A small program holding the sample claims, so there is something to read without connecting to ShipBob. |

The screen forwards claim requests to the service itself, so a browser only ever talks to one
address.

## What to try

1. **Pick a sample claim.** The findings arrive one at a time, as the system works through
   them. Some claims are stopped by the quick eligibility checks — too old, insured, the wrong
   kind of claim — and end in a drafted email to the merchant explaining why. The rest are
   investigated properly: the system reads the photographs and the paperwork, prices the
   damage, and writes a report.
2. **Expect an investigation to take a minute or two**, longer when there are photographs to
   read. The messages on screen are the real stages, arriving as they finish.
3. **Read the report, then decide.** A representative can approve it or send it back with a
   note, and a report sent back is rewritten in light of that note.
4. **Change the rules.** The admin panel, from the header, holds the thresholds every later
   claim is judged by — the $100 cap, the age limit, and the rest. A change applies to the
   next claim screened. It is held in memory only, so restarting puts every value back.

## Starting again

What the service remembers — reports, decisions, past claims, and what a representative
corrected — is kept in a volume and survives a restart. To wipe it and start from nothing:

```bash
docker compose down -v
```

The admin panel has a control that does the same thing without stopping anything.

## Two optional extras

**Give the history panel something to show.** Nothing in the system writes a representative's
correction yet, so on a fresh machine every claim honestly reports none on file. This writes
one by hand, so the feature can be demonstrated. **Everything it writes is invented**, and
`--clear` takes it back out:

```bash
docker compose run --rm api python -m tools.seed_merchant_memory
docker compose run --rm api python -m tools.seed_merchant_memory --clear
```

**See what a slow ShipBob looks like.** This holds every answer back, so the waiting states —
and, if you set it high enough, the timeout a representative would see in a real outage —
can be seen on purpose:

```bash
SHIPBOB_MOCK_DELAY_SECONDS=3 docker compose up --build
```

## Running the tests

The test suite is in the image, so it needs nothing installed either:

```bash
docker compose run --rm api pytest
```

## Working on the code

The containers are for running the demonstration, not for writing code — an edit means a
rebuild. To work on it directly, with reload, you will want [uv](https://docs.astral.sh/uv/)
and Node. `make help` lists every command.
