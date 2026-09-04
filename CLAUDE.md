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

## Design

**[DESIGN.md](DESIGN.md) records how the system actually works.** REQUIREMENTS.md says what must
happen; DESIGN.md says how we built it. Every feature adds a section, and those sections together
are the design of the project.

Update it as part of building a feature, not afterwards:

- **Before writing code**, add the feature's section using the template at the top of DESIGN.md.
  Writing the design first is how you find the holes in it.
- **After the code works**, correct the section so it describes what was actually built. A design
  that still describes an abandoned plan is worse than no design.
- **Update "How the pieces fit together"** whenever a feature changes how the parts connect, and
  keep "What exists today" honest about what is and is not built.
- Commit the DESIGN.md change in the **same commit** as the code it describes.

**Write it so anyone can read it.** Assume a new joiner, a support rep, or a manager — someone
who has never seen this codebase and may not be an engineer:

- Short sentences, everyday words. Explain a term the first time you use it, or don't use it.
- Write "the system reads the case from ShipBob", not "the client hydrates the case aggregate".
- No code, no class names, no library or framework names in the explanation. File paths appear
  only in the "Where the code is" line.
- Explain **why**, not just what. A reader should follow the reasoning, not just the steps.
- Say plainly what is still undecided, provisional, or invented rather than specified.
- If a sentence only makes sense to someone who already knows the project, rewrite it.
- Roughly a page per feature. Long is not the same as thorough.

**Record what is not production-ready.** This project is part of an interview process:
completeness is not expected, and cutting scope is fine. Cutting it *silently* is not. Keep the
**Future production** section at the end of DESIGN.md current, so every gap is a known
limitation rather than something a reader has to discover.

- Add an entry whenever you knowingly leave something out, simplify it, hardcode a value, or
  skip a case you would handle for real.
- Add an entry whenever you spot something that could break under real use — load, bad data, a
  slow or unavailable API, a model that answers differently on two runs, work lost on restart,
  an action that could fire twice.
- Add an entry for improvements worth making later, and say why they would matter.
- File each under **Not implemented**, **Could break**, or **Would improve**, and give the
  consequence, not just the label. "No retry on ShipBob calls" names a gap; "one timeout fails
  the claim and the rep gets an error with no way to resume" tells the reader why they should
  care.
- Never quietly work around a gap or leave a `TODO` comment in the code instead. Write it down
  here, where someone will actually read it.

## Progress

**[TODO.md](TODO.md) tracks which requirements are done.** It lists every requirement id in
REQUIREMENTS.md and nothing else — no descriptions, because REQUIREMENTS.md already holds them
and a second copy would drift out of step with the first.

When you finish a requirement, tick its box and write underneath it:

- **One line on what was actually built** — not what the requirement asked for, what you did.
- **A conclusion** — what someone picking this up later should take away.
- **Anything to be aware of** — a caveat, a decision made along the way, a value still
  provisional, a requirement this one interacts with. Leave this out only when there is
  genuinely nothing to flag.

Keep it to a few lines; the full explanation belongs in DESIGN.md. Tick a box only when the
requirement is genuinely done (see [Working on a feature](#working-on-a-feature)) — a tracker
that overstates progress is worse than no tracker.

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

## Working on a feature

REQUIREMENTS.md holds 83 numbered requirements and they interlock, so **work from a todo list
built out of the requirements themselves.** That is what stops a half-finished layer from
looking finished. TODO.md is the durable record; your working list is how you get through a
session.

1. **Read the requirements in scope, then create one todo item per requirement id** — `FR-0.2`,
   `FR-0.3`, each its own item. Never collapse them into a single "implement Layer 0"; the point
   is to see which specific requirements are still outstanding. Add items for the tests and the
   DESIGN.md section too.
2. **Write the DESIGN.md section before the code.** Explaining it in plain words is how you find
   the holes while they are still cheap.
3. **Work one item at a time.** Mark it in progress when you start and done the moment it is
   finished — never in a batch at the end. Exactly one item in progress at a time.
4. **A requirement is done only when** the behaviour is implemented, a test names the requirement
   id, and DESIGN.md explains it. Then tick it in TODO.md and write its note. If it is only
   partly satisfied, leave the box unticked and say what is missing. Never tick anything you
   have not actually run.
5. **Turn discovered work into new items** rather than dropping it silently. If a requirement is
   blocked, ambiguous, or larger than it looked, say so and ask — do not guess.
6. **Finish with `make check`**, then commit the code, its tests, and the DESIGN.md and TODO.md
   updates together.

Carry the requirement id into docstrings, test names, and commit messages, so any behaviour can
be traced back to the requirement that motivated it.

## Engineering standards

**Correctness.**

- Understand before you write. Read the requirement and the code around it, and follow the
  pattern already there instead of introducing a second way to do the same thing.
- Handle every failure path explicitly. No bare `except`, no swallowed exception, no empty error
  branch. If a call can fail, decide what happens when it does.
- Test the unhappy paths, not just the happy one — missing evidence, empty lists, upstream
  timeouts, malformed model output. Most of these requirements are about what happens when
  things are *not* clean.
- Verify rather than assume: run the code and the tests before calling something done, and report
  failures plainly instead of describing what you intended.
- Leave nothing behind — no dead code, no commented-out blocks, no debug prints, no unused
  imports or arguments.

**Readability.** Someone else reads this next; write for them.

- Names say what the thing is: `days_since_delivery`, not `d` or `tmp`. No abbreviations a
  newcomer would have to decode.
- Small functions that do one thing and are named for that thing. Prefer an early return to a
  nested `if`.
- Keep the main path a straight line down the page and push edge cases to the edges.
- Comment *why*, never *what*. If a line needs a comment to say what it does, rename or simplify
  it instead.
- Build the simplest thing that satisfies the requirement. No configuration, indirection, or
  extension points for needs nobody has yet — an abstraction with one implementation is a
  liability, not foresight.
- Keep modules focused. When a file starts covering two subjects, split it.

**Project conventions.**

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
