# Damaged-in-Transit Claims Agent

Backend API that investigates ShipBob damaged-in-transit claims and hands a support rep a
structured report and a drafted merchant email. The agent recommends; **a rep decides**, and
nothing is sent or paid without human approval.

- **What it must do:** [REQUIREMENTS.md](REQUIREMENTS.md) — the source of truth.
- **How it works:** [DESIGN.md](DESIGN.md) — the design in plain English, one section per
  feature. Start here if you are new.
- **How to work on it:** [CLAUDE.md](CLAUDE.md) — conventions and architecture rules.
- **What is done so far:** [TODO.md](TODO.md) — every requirement id, ticked as it lands.
- **The demo screen:** [UI-TODO.md](UI-TODO.md) — the UI in `web/`, tracked separately.

## Quickstart

Requires [uv](https://docs.astral.sh/uv/) and Python 3.11.

```bash
make install                 # create .venv and sync dependencies
make hooks                   # install the git hooks
cp .env.example .env         # then fill in ANTHROPIC_API_KEY
make run                     # http://127.0.0.1:8000  (docs at /docs)
```

```bash
curl localhost:8000/health
```

## Running the demo

Two one-off steps, then three things running side by side. The screen is at
<http://localhost:5173>.

```bash
make mock         # a stand-in for ShipBob, on :8080 — without it every claim fails
make seed         # once: sample past rep corrections, so the demo has some to show
make run          # the claims service, on :8000
make ui-install   # once: install the UI's dependencies
make ui-dev       # the screen, on :5173, forwarding claim requests to :8000
```

Try `CASE-1001` for a claim that carries on, `CASE-1004` for one stopped as too old, and
`CASE-9001` for one stopped as insured. Stop `make mock` and screen anything to see what a
rep sees when ShipBob cannot be read.

The UI is a demonstration: no sign-in, nothing stored, and nothing it shows can be sent or
approved. Its ShipBob colours and mark are our own approximation, not ShipBob's.

## Development

```bash
make test        # pytest with coverage
make lint        # ruff check + format check
make typecheck   # mypy (strict)
make format      # apply formatting and safe fixes
make check       # everything CI runs — run before pushing

make ui-lint     # the UI's lint and types
make ui-build    # build the UI for production
```

Pre-commit runs ruff and mypy on commit, pytest on push. CI repeats all of it on `main` and
on pull requests.

**The UI is deliberately outside all of that.** `make check`, CI and the hooks are Python only,
which keeps the push loop fast and CI free of Node. Nothing catches a broken UI for you — run
`make ui-lint` yourself before pushing a change to `web/`.

## Configuration

Process settings live in `src/claim_agent/settings.py`; claim policy thresholds live in
`src/claim_agent/policy.py` and nowhere else. Both are environment-overridable — see
[.env.example](.env.example). Most policy defaults are provisional placeholders pending
ShipBob sign-off; they are marked as such in the module.

## Layout

```
src/claim_agent/
  api/         HTTP surface        domain/     pure models and rules
  preflight/   Layer 0 (rules)     agent/      Layers 1a/1b/R (LangGraph)
  execution/   Layer 3 (post-approval)         storage/  reports, audit, memory
  shipbob/     ShipBob mock API client
tests/         unit/ (fast, no I/O) and integration/ (through HTTP)
tools/         development only — the ShipBob stand-in and demo data
web/           the demo screen (React + TypeScript, Vite)
```
