# CLAUDE.md

Development guidance for Claude Code working in this repository.

## What this is

A **backend API agent**. It investigates damaged-in-transit claims for ShipBob support
reps: gathers the case, reads the evidence, applies the rules, and hands a rep a
structured report plus a drafted merchant email.

**The system recommends; a rep decides.** Nothing reaches a merchant, and no money moves,
without explicit human approval.

## Requirements

**[REQUIREMENTS.md](REQUIREMENTS.md) is the authoritative source of project requirements.**
Read it before implementing anything. Do not restate or summarise it here or in code —
reference requirement ids (`FR-1.14`, `NFR-3`) in docstrings, tests, and commit messages
instead, so behaviour stays traceable to the requirement that motivated it.

Do not invent product behaviour. If something is unspecified, ambiguous, or contradicted by
the data, ask rather than guess — the requirements themselves flag several such gaps.

Note: `shipbob-mock-api.md`, which REQUIREMENTS.md cites for full endpoint payloads, is not
in this repo. Work from the summary tables in REQUIREMENTS.md and ask before assuming a
payload shape it does not show.

## Stack

| Concern | Choice |
|---|---|
| Language | Python 3.11, fully type-hinted |
| API | FastAPI + Pydantic v2 |
| Agent orchestration | LangChain / LangGraph |
| Model | `claude-opus-5` via `langchain-anthropic` |
| Dependencies | uv (`pyproject.toml` + committed `uv.lock`) |
| Lint & format | ruff |
| Types | mypy, strict |
| Tests | pytest |
| Automation | pre-commit + GitHub Actions |

## Layout

```
src/claim_agent/
  settings.py     process config: env, credentials, endpoints
  policy.py       claim thresholds — the one named place (FR-0.7, NFR-7)
  errors.py       deliberate failures, each carrying its HTTP response
  observability.py structured logging
  app.py          FastAPI application factory
  api/            routes, dependencies, error translation
  domain/         pure models and rules — no I/O, no framework, no LLM
  shipbob/        client for the ShipBob mock API
  preflight/      Layer 0 — deterministic screening
  agent/          Layers 1a, 1b, R — the LangGraph agent
  execution/      Layer 3 — post-approval email and reimbursement
  storage/        reports, versions, feedback, merchant memory, audit trail
tests/unit/       fast, no I/O
tests/integration/ through the HTTP surface
```

Layer packages mirror REQUIREMENTS.md so a requirement maps to an obvious place.

## Architecture rules

These follow from the requirements and are not negotiable without changing them:

- **The agent has no write tools.** Sending email and submitting reimbursements live in
  `execution/` and must be unreachable from `agent/`. This is structural, not a prompt
  instruction (FR-1.2). Keep a test asserting the agent's tool registry contains no write
  tool.
- **No money from model output.** The agent identifies *what* was damaged; a deterministic
  function computes *how much* (FR-1.21, NFR-2). Never parse an amount out of generated text.
- **Deterministic layers use no AI.** Layers 0 and 3 must be pure rules (FR-0.6).
- **Constrain every model response to a schema** — Pydantic models, never free text (NFR-2).
- **Fail toward the human.** Timeouts, malformed responses, exhausted budgets all end in
  escalation, never in a silent approval or a dropped case (NFR-4).
- **Business logic goes in `domain/`**, testable without a network, a model, or a database.

## Engineering standards

- Type-hint everything; mypy runs strict over `src` and `tests`.
- Raise the errors in `errors.py` rather than returning error dicts or leaking upstream
  exceptions; each maps to its own API response. Never let an internal message reach a caller.
- Log with `structlog` key/value pairs (`case_id`, `claim_line_id`), never `print`.
- Read config through the `api/deps.py` dependencies, not module-level globals, so tests and
  alternate app instances can override it.
- Add dependencies with `uv add`; keep `uv.lock` committed. Prefer the standard library over
  a new dependency.
- Test behaviour, not implementation. Every requirement-driven branch needs a test naming its
  requirement id. Mock the ShipBob API with `respx` — the suite must never touch the network.
- Keep functions small and named for what they do. Avoid abstractions with one implementation.

## Commands

```bash
make install    # sync dependencies into .venv
make hooks      # install git hooks — do this once, before your first commit
make run        # uvicorn with reload
make test       # pytest with coverage
make lint       # ruff check + format check
make typecheck  # mypy
make check      # everything CI runs
```

## Quality gates

Pre-commit runs ruff and mypy on every commit and pytest on every push. **Use the hooks;
never bypass them with `--no-verify`.** CI (`.github/workflows/ci.yml`) runs lint, format,
types, and tests on every push to `main` and every pull request. Run `make check` before
pushing.

## Git

- Work directly against `main` and **push to `main` when changes are ready**.
- Keep commits small and logically focused.
- Write **short, natural commit messages a developer would actually write** — one line,
  imperative, describing the change. No multi-paragraph bodies, no bullet summaries, no
  emoji.
- Commit as the repository owner's git identity (`git config user.name` / `user.email`).
- **Never add Claude as an author, co-author, or contributor.** No `Co-authored-by: Claude`,
  no "Generated with Claude Code", no Claude attribution in commit messages, branch names, or
  any git metadata. Claude is a tool used by the developer, not a contributor to this project.
- Ensure `make check` passes before pushing.

## Decisions not yet made

Open engineering choices — decide with the user, then record the outcome here:

- **Persistence backend** for reports, versions, feedback, merchant memory, and the audit
  trail. Nothing is chosen; `storage/` is empty by design.
- **Provisional policy values.** Only the $100 cap comes from REQUIREMENTS.md. The age limit,
  high-value threshold, confidence threshold, and step budgets in `policy.py` are placeholders
  awaiting ShipBob sign-off.
- **Reimbursement cap semantics** — per claim line or per claim (REQUIREMENTS.md open
  question 2).
