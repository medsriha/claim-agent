# CLAUDE.md

Development guidance for Claude Code working in this repository.

## What this is

A **backend API agent**. It investigates damaged-in-transit claims for ShipBob support
reps: gathers the case, reads the evidence, applies the rules, and hands a rep a
structured report plus a drafted merchant email.

**The system recommends; a rep decides.** Nothing reaches a merchant, and no money moves,
without explicit human approval.

A **demo UI** in `web/` puts a screen in front of it. It shows a rep what the backend returned
and nothing more — there is no send button, because nothing the UI can reach is able to send. It
exists to show the system working, not to be run in production. See [The UI](#the-ui).

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

## Documenting the code

**The DESIGN.md rule applies inside the code too: write so someone who has never seen this
project can follow it.** A reader should understand what a piece of code is for without already
knowing the domain, the requirements, or the rest of the codebase. Assume the next person is
new here — because they are.

**Every module, class, and function gets a docstring.** Short ones included; a small function
still has to say what it is for.

- Open with one sentence in plain words saying what it does: "Work out how many days passed
  between delivery and the merchant opening the case." Not "Compute the delta."
- Say **why it exists** when that is not obvious, and name the requirement id it serves
  (`FR-0.2`) so the reader can look up the full rule.
- Explain a domain word the first time it appears. Nobody arrives knowing what a claim line, a
  terminal verdict, or shared evidence means.
- Tell the caller what they need: what goes in, what comes back, and what it raises. Say what an
  empty or missing value means — in this project that is usually the interesting case.
- Do not restate the signature. `"""Return the settings."""` on `get_settings()` earns its
  space back only by saying something the name does not, such as why it is cached.

**Comments explain why, never what.**

- Comment the reasoning, the trade-off, or the surprise. If a line needs a comment to say what
  it does, rename or simplify it instead.
- Anything that looks wrong but is deliberate needs a comment saying so, or the next person will
  helpfully "fix" it.
- Keep comments true. One that describes code which has since changed is worse than none —
  correct it in the same edit.
- No commented-out code, and no `TODO` comments. Gaps belong in DESIGN.md under **Future
  production**, where someone will actually read them.

**Plain language throughout.** Short sentences, everyday words, and spell an abbreviation out
the first time. This applies to docstrings, comments, log messages, error messages, and test
names alike — anything a human reads.

**None of this is about Python.** A React component and a TypeScript module get the same
treatment as a function in `src/` — a plain-words opening comment saying what it is for,
comments that explain why, and no `TODO`s.

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

**[UI-TODO.md](UI-TODO.md) tracks the UI.** REQUIREMENTS.md puts the reviewer-facing UI out of
scope — "specified separately" — and that separate specification is not in this repo, so UI work
has no requirement id to trace to. It is tracked under ids we made up (`UI-1`, `UI-2`) in their
own file, which is why TODO.md can go on holding REQUIREMENTS.md ids and nothing else. Same tick
discipline: a box goes green when the thing actually works, not when it is nearly done.

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
| UI | React + TypeScript on Vite, in `web/` |
| UI packages | npm (`package.json` + committed `package-lock.json`) |
| UI lint & types | eslint, `tsc --noEmit` |

No Prettier, no component library, no state-management library. A demo screen does not earn
them, and "prefer the standard library over a new dependency" applies to npm just as it does to
Python.

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

web/              React + TypeScript demo UI
  src/api/        typed client for the backend
  src/theme/      ShipBob colours and logo — provisional values
  src/components/ the pieces a screen is built from
  src/screens/    one screen per thing a rep does
tools/            development only — a ShipBob stand-in, and demo data
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

## The UI

A React and TypeScript screen in `web/`, served by Vite. It is a **demo**: no sign-in, no idea
who is using it, and nothing stored. One screen — a rep types a case id, the UI calls
`POST /cases/{case_id}/preflight` (the case id in the path is the whole input) and renders the
answer.

**The backend's rules do not stop at the browser:**

- **No business logic in the UI.** It renders what the API returned. It never works out a
  verdict, decides whether a check passed, or re-orders the reasons — the service ranks them and
  the first one heads the merchant's email.
- **No money arithmetic in JavaScript.** The browser half of "no money from model output"
  (FR-1.21, NFR-2). A line item carries `quantity` and a string `unit_price`; the totals behind
  them are computed in Python and are **not** in the JSON. Show `context.order_value_usd`. Money
  is a string (`"90.00"`) so it never becomes a float — keep it one.
- **Fail toward the human** (NFR-4). Every failure renders something a rep can act on. The error
  shape is `{"error": {"code", "message", "details"}}`; from Layer 0 the codes are `not_found`
  (404) and `upstream_unavailable` (502). A blank screen is a bug.
- **A draft is never a send.** `drafted_email.is_draft` is always true and the UI is what makes
  that visible — the email's own words never say "draft". There is no send action and no endpoint
  behind one.
- **Show all four checks, always.** The service returns all four so a rep sees what passed rather
  than inferring it from silence.
- **Say as little as possible on screen.** Almost every sentence a rep reads should have come
  from the service. The UI adds labels, not commentary — it is a window onto the rules, and prose
  explaining itself is noise in front of them.

**How it reaches the API.** Through the Vite dev proxy, which forwards `/cases` and `/health`.
No backend change, and no cross-origin policy opened on a service with no authentication. That
is a dev-server feature: a built UI served elsewhere would need it solved properly.

**Theme.** Every colour, font and the logo live in one file under `web/src/theme/`. The values
are our approximation of ShipBob's public branding, not values ShipBob gave us — the file says
so, the same way `policy.py` marks its provisional thresholds. The logo is a stand-in.

**Writing it.** [Documenting the code](#documenting-the-code) applies, in proportion: the UI is a
demo, so a component gets a short docstring saying what it is for, not an essay. TypeScript is
strict and `any` is not allowed, for the same reason mypy is.

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

**UI work runs the same loop** — one item at a time, in progress then done — against
[UI-TODO.md](UI-TODO.md) instead, and a UI feature still writes its DESIGN.md section before the
code like everything else. There is no requirement id to carry, so carry the `UI-` id.

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
- Docstrings and comments follow [Documenting the code](#documenting-the-code) — plain words,
  readable by someone new to the project.
- Build the simplest thing that satisfies the requirement. No indirection or extension points
  for needs nobody has yet — an abstraction with one implementation is a liability, not
  foresight.
- **Configuration is different.** A value used to judge a claim belongs in `policy.py` even if
  only one place reads it. Judgement calls have to be visible and changeable, not buried in a
  branch (FR-0.7, NFR-7).
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
make mock       # the ShipBob stand-in on port 8080
make seed       # sample past rep corrections, so the demo has some to show
make test       # pytest with coverage
make lint       # ruff check + format check
make typecheck  # mypy
make check      # everything CI runs

make ui-install # npm install in web/
make ui-dev     # vite dev server, proxying the API
make ui-build   # production build
make ui-lint    # eslint + tsc --noEmit
```

## Quality gates

Pre-commit runs ruff and mypy on every commit and pytest on every push. **Use the hooks;
never bypass them with `--no-verify`.** CI (`.github/workflows/ci.yml`) runs lint, format,
types, and tests on every push to `main` and every pull request. Run `make check` before
pushing.

**The UI is not gated, deliberately.** `make check` and CI are Python only — they do not lint,
typecheck or build `web/`, and the pre-commit hooks are scoped to Python files so they will not
fire on a change that only touches the UI. That is the trade we took for a demo artifact: the
push loop stays fast and CI needs no Node. It means **nothing catches a broken UI for you** —
run `make ui-lint` yourself before pushing UI changes.

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

- **Provisional policy values.** Only the $100 cap comes from REQUIREMENTS.md. Everything else
  in `policy.py` — the age limit and whether it is inclusive, the high-value threshold, the
  claim-type label, the minimum description length, the order terminal reasons are ranked in,
  the confidence threshold, and the step budgets — are placeholders awaiting ShipBob sign-off.
  They are configurable so they can be corrected without a code change; that does not make the
  numbers right.
- **Reimbursement cap semantics** — per claim line or per claim (REQUIREMENTS.md open
  question 2).
- **How a built UI would reach the API.** Solved for development by the dev-server proxy, and
  not solved at all for anything else. A UI served from a real address would need either
  cross-origin middleware or the same origin as the service, and that decision waits until there
  is somewhere to deploy either of them.
- **How the Layer 0 report and the Layer 2 report reconcile.** The report shape the UI renders
  today is scoped to Layer 0. Layer 2 has its own requirements (FR-2.1–FR-2.10) that nobody has
  built; TODO.md's FR-0.4 note says the two will need reconciling rather than one being extended.
  A UI written tightly against today's shape will need rework then.

Decided:

- **Persistence backend: SQLite**, one file, path from `DATABASE_PATH`. Chosen for merchant
  memory in Layer 0. Reports, versions, feedback, and the audit trail still have no schema.
- **The UI lives in `web/`**, React and TypeScript on Vite, in this repo. Demo-grade on purpose,
  and outside the quality gates — see [The UI](#the-ui) and [Quality gates](#quality-gates).
- **ShipBob's colours and logo are provisional**, kept in one theme file and marked as our
  approximation, so correcting them later is one edit rather than a hunt.
- **The browser reaches the API through the Vite dev proxy**, not through cross-origin middleware.
  No backend change, and nothing opened up on a service with no sign-in.
- **`tools/` holds development-only programs**, typechecked and linted like everything else but
  unreachable from `src/`. It has the ShipBob stand-in the demo reads from, which serves the very
  same sample records the tests use so the two can never disagree.
