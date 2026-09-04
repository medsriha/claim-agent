# Requirement tracker

Every requirement in [REQUIREMENTS.md](REQUIREMENTS.md) — all 83 — by id only.

There are no descriptions here on purpose: REQUIREMENTS.md already holds them, and a second
copy would drift out of step with the first. Look the id up there.

**The UI is tracked in [UI-TODO.md](UI-TODO.md), not here.** REQUIREMENTS.md puts the
reviewer-facing UI out of scope — "specified separately" — and that separate specification is
not in this repo, so UI work has no requirement id to trace to. It gets its own file and its own
ids rather than boxes in this one.

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

- [x] FR-0.1 — A reader for the three ShipBob records, and a gather step that fetches the case,
  then the shipment and order together.
  - **Conclusion:** the case is read first because it names the other two; those two run
    concurrently. Attachments are unreachable from here by construction, not by convention.
  - **Be aware:** the one rule not to break is that a 404 on the shipment or order becomes an
    empty record, while an upstream failure propagates. Widening that `except` would let a
    timeout close a good claim and email its merchant. There is a test that fails if you do.

- [x] FR-0.2 — The four gates, always all four, each recording what it looked at.
  - **Conclusion:** no short-circuiting, so a rep sees every reason a claim was stopped, not just
    the first one found. The claim-type match is exact after case and spacing are normalised —
    deliberately not a prefix, or `"Claim | Damaged in Transit - Insured"` would be let through.
  - **Be aware:** `missing_key_information` currently covers three different problems, including
    "neither record has a delivery date", which a merchant cannot fix. See DESIGN.md.

- [x] FR-0.3 — `PROCEED`, or `TERMINAL` with every reason, ranked.
  - **Conclusion:** reasons are ordered by a configurable ranking, never by iterating a set, so
    the same claim always reports them in the same order.
  - **Be aware:** the ranking (insured, too old, wrong type, missing information) is our
    judgement, not a ShipBob rule, and it decides which reason heads the merchant's email.

- [x] FR-0.4 — A stopped claim produces a rep-facing report and a drafted merchant email listing
  every reason it was declined.
  - **Conclusion:** written from fixed sentences with the claim's real numbers filled in — no AI,
    so an ineligible claim costs three reads and nothing more (NFR-8). The report carries all four
    gate results, so a rep can see what passed rather than infer it from silence.
  - **Be aware:** this report shape is scoped to Layer 0. Layer 2 has its own requirements
    (FR-2.1–FR-2.10) that nobody has built yet; the two will need reconciling rather than this one
    being extended. Nothing is stored and nothing is sent — the email is a draft on an object, and
    the word "draft" is deliberately absent from its text so a marker can never reach a merchant.

- [x] FR-0.5 — Order value, high-value flag, days since delivery, and the merchant's past
  corrections, computed once and passed on.
  - **Conclusion:** money is exact throughout — parsed off the wire as a decimal so `38.00` keeps
    its cents, and rendered as `"90.00"` rather than a float.
  - **Be aware:** `days_since_delivery` counts delivery to *case creation*, not to today, so the
    number matches the age gate and never goes stale. An unreadable order gives an unknown value,
    which is deliberately different from an order worth nothing. A store of corrections we cannot
    read stops the claim outright rather than screening without them — chosen so that an empty
    history always means "this merchant has none", never "we did not look".

- [x] FR-0.6 — The same claim always produces the same answer.
  - **Conclusion:** no clock is read anywhere in the layer — the timestamp is passed in from the
    HTTP edge — and the age check compares two dates that both come from ShipBob, so a claim that
    was 73 days old when filed is 73 days old forever. Proven by screening the same case with
    timestamps a decade apart and comparing the output byte for byte.
  - **Be aware:** the hazards that had to be designed around were float money, locale-dependent
    month names, and set iteration. All three are avoided deliberately and will look like
    over-engineering to someone who has not hit them.

- [x] FR-0.7 — Claim thresholds live in `policy.py`, apart from process settings in `settings.py`.
  - **Conclusion:** every threshold used to judge a claim is in one file and overridable by
    environment variable. Nothing is hardcoded anywhere else.
  - **Be aware:** only the $100 cap is a real ShipBob figure. The age limit and whether it is
    inclusive, the high-value threshold, the claim-type wording, the minimum description length,
    the reason ranking, the confidence threshold and the step budgets are placeholders we invented
    so the code runs — they need sign-off before production.

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
  - **Be aware:** now genuinely consumed, which was the open question here. Raising
    `POLICY_MAX_CLAIM_AGE_DAYS` to 90 turns CASE-1004 from stopped into carried-on, end to end
    over HTTP — that is the demonstration, not the unit test.
- [ ] NFR-8
