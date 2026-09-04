# Requirement tracker

Every requirement in [REQUIREMENTS.md](REQUIREMENTS.md) — all 97 — by id only.

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
  - **Be aware:** an insured parcel is now *routed out* rather than answered — the write-up is
    marked for escalation and no merchant email mentions insurance. FR-0.2 says insured shipments
    are "routed out, never processed here"; FR-0.4 says every ineligible claim is closed with an
    explanation to the merchant and does not except this one. Reading the two together is our
    interpretation, and it is listed among DESIGN.md's questions.

- [x] FR-0.3 — `PROCEED`, or `TERMINAL` with every reason, in a set order.
  - **Conclusion:** reasons are put in a fixed order, never left to the order a set
    happens to iterate in, so
    the same claim always reports them in the same order.
  - **Be aware:** the order is our judgement, not a ShipBob rule, and it lives in `gates.py`
    rather than in the claim policy — it decides emphasis only, and nobody asked to tune it.
    Being insured leads the reasons, because it is what routes the claim out; the other three
    follow in the order the merchant's email explains them. Every reason is reported whatever the
    order, and whether the claim is stopped does not depend on it.

- [x] FR-0.4 — A stopped claim produces a rep-facing report and a drafted merchant email listing
  every reason it was declined.
  - **Conclusion:** written from fixed sentences with the claim's real numbers filled in — no AI,
    so an ineligible claim costs three reads and nothing more (NFR-8). The report carries all four
    gate results, so a rep can see what passed rather than infer it from silence.
  - **Be aware:** an insured claim is the exception — it carries an escalation and no email,
    because no email explains insurance. A claim that is insured *and* stopped for another reason
    carries both, and the rep chooses which to act on. The report refuses to exist in any other
    combination: an email with nothing to say, or a reason the merchant could be told with no
    email, is a mistake in our own code and is rejected on construction.
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
  - **Also now changeable while the service runs.** An admin panel reads and writes them over
    HTTP (`/admin/policy`), and the change reaches the very next claim screened — no restart. The
    values in force are held in `live_policy.py` and replaced whole; a claim already being
    screened finishes on the ones it started with, so FR-0.6 still holds. The panel is generated
    from `policy.py`, so a threshold added there needs no other change to be editable.
  - **Not every value is on the panel.** Marking one `NOT_ON_PANEL` in `policy.py` keeps it a
    policy value — read as always, still set from the environment — while the panel neither shows
    it nor accepts a change to it. Four are marked: the minimum description length, and the three
    the unbuilt AI investigation would read, where a control would change nothing observable.
  - **Be aware:** only the $100 cap is a real ShipBob figure. The age limit and whether it is
    inclusive, the high-value threshold, the claim-type wording, the minimum description length,
    the email reason order, the confidence threshold and the step budgets are placeholders we
    invented
    so the code runs — they need sign-off before production.
  - **Be aware:** a change made through the panel is held in memory only and there is no sign-in
    on it. A restart silently puts every value back to what the environment says, and nothing
    records who changed what. Both were chosen knowingly for a demo — see DESIGN.md, "Future
    production".

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

## Claim precedent — finding similar past claims

- [ ] FR-S.1
- [ ] FR-S.2
- [ ] FR-S.3
- [ ] FR-S.4
- [ ] FR-S.5
- [ ] FR-S.6
- [ ] FR-S.7
- [ ] FR-S.8
- [ ] FR-S.9
- [ ] FR-S.10
- [ ] FR-S.11
- [ ] FR-S.12
- [ ] FR-S.13
- [ ] FR-S.14

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
