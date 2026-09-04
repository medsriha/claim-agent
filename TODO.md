# Requirement tracker

Every requirement in [REQUIREMENTS.md](REQUIREMENTS.md) — all 83 — by id only.

There are no descriptions here on purpose: REQUIREMENTS.md already holds them, and a second
copy would drift out of step with the first. Look the id up there.

**Tick a box only when the requirement is genuinely done** — implemented, covered by a test
that names the id, and explained in [DESIGN.md](DESIGN.md). Then write, underneath it, what
was built, what a future reader should take away, and anything they need to be aware of. A
tracker that overstates progress is worse than no tracker.

Format for a finished requirement:

```markdown
- [x] FR-X.Y — one line on what was actually built
  - **Conclusion:** what someone picking this up later should take away.
  - **Be aware:** a caveat, a decision made along the way, a value still provisional, or a
    requirement this one interacts with. Leave this out only if there is truly nothing.
```

Keep it to a few lines — the full explanation belongs in DESIGN.md.

## Layer 0 — Deterministic pre-flight

- [ ] FR-0.1
- [ ] FR-0.2
- [ ] FR-0.3
- [ ] FR-0.4
- [ ] FR-0.5
- [ ] FR-0.6
- [x] FR-0.7 — Claim thresholds live in `policy.py`, apart from process settings in `settings.py`.
  - **Conclusion:** every threshold used to judge a claim is in one file and overridable by
    environment variable. Nothing is hardcoded anywhere else.
  - **Be aware:** only the $100 cap is a real ShipBob figure. The age limit, high-value
    threshold, confidence threshold and step budgets are placeholders we invented so the code runs
    — they need sign-off before production.

## Layer 1a — Triage: splitting the claim into lines

- [ ] FR-1a.1
- [ ] FR-1a.2
- [ ] FR-1a.3
- [ ] FR-1a.4
- [ ] FR-1a.5

## Layer 1b — Investigation, per claim line

- [ ] FR-1b.1
- [ ] FR-1b.2
- [ ] FR-1b.3
- [ ] FR-1b.4

## Layer 1 — Shared agent requirements

- [ ] FR-1.1
- [ ] FR-1.2
- [ ] FR-1.3
- [ ] FR-1.4
- [ ] FR-1.5
- [ ] FR-1.6
- [ ] FR-1.7
- [ ] FR-1.8
- [ ] FR-1.9
- [ ] FR-1.10
- [ ] FR-1.11
- [ ] FR-1.12
- [ ] FR-1.13
- [ ] FR-1.14
- [ ] FR-1.15
- [ ] FR-1.16
- [ ] FR-1.17
- [ ] FR-1.18
- [ ] FR-1.19
- [ ] FR-1.20
- [ ] FR-1.21

## Layer 2 — The report

- [ ] FR-2.1
- [ ] FR-2.2
- [ ] FR-2.3
- [ ] FR-2.4
- [ ] FR-2.5
- [ ] FR-2.5a
- [ ] FR-2.6
- [ ] FR-2.7
- [ ] FR-2.8
- [ ] FR-2.9
- [ ] FR-2.9a
- [ ] FR-2.9b
- [ ] FR-2.10

## Layer R — Revision

- [ ] FR-R.1
- [ ] FR-R.1a
- [ ] FR-R.2
- [ ] FR-R.3
- [ ] FR-R.4
- [ ] FR-R.5
- [ ] FR-R.6
- [ ] FR-R.7
- [ ] FR-R.8
- [ ] FR-R.9
- [ ] FR-R.10
- [ ] FR-R.11
- [ ] FR-R.12
- [ ] FR-R.13
- [ ] FR-R.14

## Layer 3 — Execution after approval

- [ ] FR-3.1
- [ ] FR-3.1a
- [ ] FR-3.2
- [ ] FR-3.3
- [ ] FR-3.4
- [ ] FR-3.5
- [ ] FR-3.6
- [ ] FR-3.7
- [ ] FR-3.8

## Non-functional requirements

- [ ] NFR-1
- [ ] NFR-2
- [ ] NFR-3
- [ ] NFR-4
- [ ] NFR-5
- [ ] NFR-5a
- [ ] NFR-6
- [x] NFR-7 — Policy values are read from the environment with a `POLICY_` prefix.
  - **Conclusion:** changing a threshold needs no code change and no redeploy of logic.
  - **Be aware:** the values are wired up but nothing consumes them yet, so this is proven only
    by its own tests. Re-check it when Layer 0 lands.
- [ ] NFR-8
