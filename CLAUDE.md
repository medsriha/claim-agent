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
  live_policy.py  the policy in force; swapped whole when an admin changes one
  errors.py       deliberate failures, each carrying its HTTP response
  observability.py structured logging
  app.py          FastAPI application factory
  api/            routes, dependencies, error translation
  domain/         pure models and rules — no I/O, no framework, no LLM
  shipbob/        client for the ShipBob mock API
  preflight/      Layer 0 — deterministic screening
  admin/          the policy panel's view of policy.py, and what it sends back
  agent/          Layers 1a, 1b, R — the LangGraph agent
  execution/      Layer 3 — post-approval email and reimbursement
  storage/        reports, versions, feedback, merchant memory, audit trail
tests/unit/       fast, no I/O
tests/integration/ through the HTTP surface

web/              React + TypeScript demo UI
  src/api/        typed client for the backend
  src/theme/      ShipBob colours and logo — provisional values
  src/chat/       the conversation: what to say, in what order, and how it appears
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
- **The agent decides the amount; code caps it.** The agent judges what the damage is worth
  from the photographs and from how comparable claims were settled, and a deterministic
  function holds that figure to the $100 cap (FR-1.21, FR-1.20). The cap is the only limit on
  it, so never remove or widen it without changing the requirement.
  **This rule was the opposite until it was reversed on purpose** — no figure could come from
  model output at all, and the amount was arithmetic a rep could check. It no longer is. Read
  FR-1.21 for what that cost before you rely on a figure being repeatable.
  Two things do survive: money is read as text into an exact decimal and never through a
  float, and **no figure the model wrote reaches a merchant** — the email carries a marker
  that code replaces after the cap, so what is sent is the figure that survived it.
- **Deterministic layers use no AI.** Layers 0 and 3 must be pure rules (FR-0.6).
- **Constrain every model response to a schema** — Pydantic models, never free text (NFR-2).
- **Fail toward the human.** Timeouts, malformed responses, exhausted budgets all end in
  escalation, never in a silent approval or a dropped case (NFR-4).
- **Business logic goes in `domain/`**, testable without a network, a model, or a database.

## The UI

A React and TypeScript screen in `web/`, served by Vite. It is a **demo**: no sign-in, no idea
who is using it, and nothing stored. A rep picks one of the sample claims, the UI calls
`POST /cases/{case_id}/preflight` (the case id in the path is the whole input) and lays the
answer out as a conversation: the findings appear one at a time, and a stopped claim ends in
its drafted email, which the rep can reword and send.

**A second screen is the admin panel**, reached from the header. It lists the thresholds in
`policy.py` that are meant to be changed while the service runs, and changes them:
`GET /admin/policy`, `PUT /admin/policy`, `POST /admin/policy/reset`. The panel is drawn from the
policy file itself — each value's label, explanation and control come from how the file declares
it — so a threshold added there appears on screen without the UI being touched.

**A value can be kept off the panel** by marking it `NOT_ON_PANEL` in `policy.py`. It stays a
policy value, still read and still set from the environment; the panel neither shows it nor
accepts a change to it, and the endpoint refuses one so the omission is a rule rather than a
choice of controls. Four values are marked today: the three the unbuilt AI investigation would
read, and the minimum description length.

**There is no sign-in on it**, and a change is held in memory only, so a restart silently puts
every value back. Both are deliberate demo choices, written up in DESIGN.md under "Future
production".

**The backend's rules do not stop at the browser:**

- **No business logic in the UI.** It renders what the API returned. It never works out a
  verdict, decides whether a check passed, or re-orders the reasons — the service decides their
  order, and the first one names the merchant email's subject line.
- **No money arithmetic in JavaScript.** Every figure arrives as a string and is shown as one:
  `"90.00"` must never become a float, and nothing on screen adds two figures together. The
  arithmetic — the cap, and the totals across a claim — happens in Python, and repeating it in
  a browser would be a second calculation that could disagree with the first (FR-1.21, NFR-3).
  The screen may show the steps; it may not perform them.
- **Fail toward the human** (NFR-4). Every failure renders something a rep can act on. The error
  shape is `{"error": {"code", "message", "details"}}`; from Layer 0 the codes are `not_found`
  (404) and `upstream_unavailable` (502). A blank screen is a bug.
- **The send is a simulation, and the screen does *not* say so.** `drafted_email.is_draft` is
  always true and the UI marks the draft as a draft before sending — the email's own words never
  say "draft". But the send button reaches nothing: no address is contacted, nothing is stored,
  and there is no endpoint behind it, because Layer 3 does not exist. Pressing it reports the
  email as sent anyway. **That was a deliberate product decision** — a demonstration should read
  as a working product rather than one apologising for itself — and the cost is that nothing a
  viewer can see reveals the send is not real. So the record lives in DESIGN.md instead, under
  **Not implemented**, and in the docstring of `chat/EmailComposer.tsx`. Keep both current: they
  are now the only warning anyone gets. A missing `drafted_email.to` still disables the send.
- **Show all four checks, always.** The service returns all four so a rep sees what passed rather
  than inferring it from silence. Each one is its own message, in the order the service evaluated
  them — never sorted, and never summarised into "3 of 4 passed".

- **The pacing is a replay, never a race.** The whole response is fetched first; only then are the
  findings played out — each one turning for a moment before it settles, and a check's spinner
  giving way to a tick or a cross in the same spot. Starting the reveal while the request is in
  flight would put a finished step on screen for work that had not finished, or had already
  failed. A failure therefore shows a failure and no findings at all. Keep it that way.

- **The spinners are an illusion and the docs must keep saying so.** A check that appears to be
  thinking was decided before the message existed. It is the one place this screen shows
  something that is not so, chosen because a page that fills in silently does not show that the
  system works in stages. There is deliberately no skip button — only `prefers-reduced-motion`
  settles the whole conversation at once — so a stopped claim takes about thirteen seconds every
  time. If you shorten, lengthen, or remove any of this, correct DESIGN.md's **Could break**
  entry in the same commit; an undocumented fake is the thing to avoid, not the fake itself.
- **Say as little as possible on screen.** Almost every sentence a rep reads should have come
  from the service. The UI adds labels, not commentary — it is a window onto the rules, and prose
  explaining itself is noise in front of them. The sentences the UI does own live in
  `web/src/chat/pageWords.ts` and nowhere else, marked on screen as the screen's own words rather
  than the service's, so the whole list is checkable in one place — it is down to one. Add to it
  only when the service genuinely cannot say the thing instead, and never to describe the demo
  itself: the screen is not the place to explain what has and has not been built.
- **Never invent data.** The screen shows what the endpoint returned and nothing else. An empty
  list is shown as empty. Never add a record from the UI, and never fake one in a component to
  make a panel look fuller — fabricated content on screen is indistinguishable from real history,
  and a reader has no way to tell. This applies to the service's own values too: a verdict, a
  check name or a stop reason is reshaped to read (`claim_too_old` becomes "Claim too old"),
  never swapped for wording of ours.

- **Seeding the store is a deliberate act with a name on it.** Merchant memory is the one panel
  with nothing to show, because nothing in the system writes a correction yet (FR-3.8), so
  `tools/seed_merchant_memory.py` writes one by hand for demonstrations. That is the *only*
  sanctioned way to put content behind a panel, and it earns that by being outside `src/`, saying
  in its own docstring that everything it writes is invented, writing through the real store
  rather than around it, and having a `--clear` that takes it back out. Ask the user before
  running it. Never reach for the shortcut it exists to prevent: seeding from a test, a fixture,
  a migration, or the UI.

**How it reaches the API.** Through the Vite dev proxy, which forwards `/cases` and `/health`.
No backend change, and no cross-origin policy opened on a service with no authentication. That
is a dev-server feature: a built UI served elsewhere would need it solved properly.

**Theme.** Every colour and font lives in one file under `web/src/theme/`. The brand blue
(`#175CFF`) and navy (`#09083A`) are sampled from ShipBob's logo artwork and the mark's outline
is traced from it, so both are the real thing; the greys and the pass/stop colours are ours. The
wordmark is set in the page's own typeface, which is not ShipBob's — swap both for the official
asset before this is seen outside the team.

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
make seed-memory  # write one invented rep correction, so the history panel shows something
make clear-memory # remove it again
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
  claim-type label, the minimum description length, the confidence threshold, and the step
  budgets — are placeholders awaiting ShipBob sign-off, and so is the fixed order the reasons
  are explained in. They are configurable so they can be corrected without a code change; that
  does not make the numbers right.
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
  same sample records the tests use so the two can never disagree, and the merchant-memory seeder
  that makes the past-corrections panel demonstrable.
- **The screen is a conversation, and its pacing is faked in the browser.** No streaming endpoint
  was added: the service still answers in one response, and the screen plays it back. This was a
  deliberate call to keep the change to the UI. The honest version — the service emitting each
  stage as it completes — is written up under **Would improve** in DESIGN.md.
- **The send is faked too**, for the same reason: Layer 3 is unbuilt, and building it was out of
  scope for a UI change. The screen reports it as sent regardless, which was asked for; the
  warning therefore lives only in DESIGN.md and in the component's docstring. Whoever builds
  Layer 3 replaces the simulation rather than adding to it.
- **The policy panel has no sign-in and keeps nothing.** Anyone who can reach the service can
  change what every later claim is judged by, and a restart loses the change. Chosen knowingly for
  a demo that is shown once, over a shared admin token and a SQLite table, both of which were
  offered. Neither is a defensible choice for anything longer-lived: see DESIGN.md.
- **The panel offers the values worth changing on a running service**, the stated $100 cap
  included, each shown with the service's own explanation of it. A value whose layer does not
  exist yet is kept off it: a control that changes nothing observable is worse than no control.
  Marking one is a single note beside the value in `policy.py`.
- **An insured claim is escalated, not explained.** FR-0.2 says insured shipments are "routed out,
  never processed here", so no merchant email is written about one, and the write-up is marked for
  escalation instead. A claim that is *also* too old still gets the email about its age, and the
  rep chooses. FR-0.4 says every ineligible claim is closed with an explanation to the merchant
  and does not except this case, so the two requirements can be read as conflicting; this is our
  reading, and DESIGN.md lists it among the questions for whoever owns them.
- **The order the reasons are explained in is fixed in code**, not a policy value. It sets the
  paragraph order and the subject line and nothing else, and nobody asked to tune it.
- **The policy is read once per request**, through the same dependency as before, and replaced
  whole rather than value by value. A claim being screened finishes on the values it started with;
  the next claim sees the change. That is what keeps Layer 0 deterministic (FR-0.6) while its
  thresholds are editable.
