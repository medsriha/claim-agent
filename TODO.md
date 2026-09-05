# Requirement tracker

Every requirement in [REQUIREMENTS.md](REQUIREMENTS.md) — all 105 — by id only.

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
  - **Be aware:** an insured parcel is now *routed out* rather than answered — the write-up asks
    the representative for clarification and no merchant email mentions insurance. FR-0.2 says insured shipments
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
  - **Be aware:** an insured claim is the exception — it requests rep clarification and has no email,
    because no email explains insurance. That action takes priority even when another gate also
    failed, so the report never combines a rep clarification request with merchant wording. Invalid
    action/email combinations are rejected on construction.
  - **Be aware:** this shape is still scoped to Layer 0 and was **not** extended. Layer 2
    reconciled the two by reading from it: a stopped claim's write-up is rendered into the same
    report a rep decides from, behind the same head, naming no product. The report is persisted;
    nothing is sent. Any email remains a draft, and the word "draft" is deliberately absent from
    its text so a marker can never reach a merchant.

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
    the email reason order, the deterministic matching thresholds and the step budgets are
    placeholders we invented
    so the code runs — they need sign-off before production. The cap is now the only limit on
    a payout at all, which makes it the one number here with money directly behind it: raise
    it and every claim above it is paid more.
  - **Be aware:** a change made through the panel is held in memory only and there is no sign-in
    on it. A restart silently puts every value back to what the environment says, and nothing
    records who changed what. Both were chosen knowingly for a demo — see DESIGN.md, "Future
    production".

## Layer 1a — Triage: splitting the claim into lines

**Read this before the ticks below.** Everything in Layer 1a, Layer 1b and Layer 1 is
built, tested, explained in DESIGN.md, and **now reachable**: `POST
/cases/{case_id}/investigate` screens a claim, investigates every damaged product on it,
and reports what it is doing as it happens rather than answering at the end. A claim the
screen turns away never reaches the agent and costs no AI at all.

The demo screen shows all of it: the quick checks, the similar past claims, then the
investigation reporting each step as it happens, then a report per damaged product with the
working behind its figure and a draft email. Proven end to end against the real model on
ShipBob's own photographs — it picked out the damaged collagen from four images and judged
what the damage was worth.

One caveat the ticks do not cover: **nothing is stored**, so a stream cannot be replayed and
a representative who reloads starts the investigation again. That is why NFR-3 and NFR-5 are
still unticked below.

- [x] FR-1a.1 — One agent pass over the whole claim that reads the description and the
  photographs and says which products are being claimed for.
  - **Conclusion:** the split cannot be made by a rule, which is why this is the first
    place any AI is involved. The pass chooses which images to look at for itself;
    nothing loops over the attachments for it.
  - **Be aware:** only the attachment *listing* is fetched up front, because the prompt
    has to name the images that exist. Deciding what any of them shows is the pass's own
    work.

- [x] FR-1a.2 — Every claimed product is matched against the order's line items, and
  carries that item's name, code and price.
  - **Conclusion:** matching is by product code first, then by name with capitals and
    spacing ignored — never by anything merely *starting* with the same letters, which
    would quietly pay out on the wrong product.
  - **Be aware:** a product the order does not hold is still a claim line and still
    reported, because FR-1a.2 calls that a finding rather than an error. A product
    matching *two* order lines is a third outcome again (`AMBIGUOUS`) and is what stops
    a payout being invented.

- [x] FR-1a.3 — The invoice, the customer's confirmation and the outer packaging photo
  are settled once for the whole claim and handed to every product.
  - **Conclusion:** partly a cost control — the invoice is not re-read per product — and
    mostly a consistency guarantee: two products in one claim can never disagree about
    whether the box was photographed.
  - **Be aware:** they are settled only from images the pass chose to look at. A pass
    that stops early can leave a kind "missing" when an unexamined image was it, which
    would ask a merchant for something they already sent. See DESIGN.md.

- [x] FR-1a.4 — An ambiguous split asks the party who can resolve it, and no split is guessed.
  - **Conclusion:** three different things produce it — the model saying so, no products
    named at all, and a product matching two order lines. All three stop every per-product
    run. Concrete merchant-answerable gaps produce `request_info` with the exact details and
    an email; internal or non-actionable ambiguity produces `request_rep_clarification`.
  - **Be aware:** the candidates are still listed so the reviewer can see the unresolved
    choice. They are deliberately not presented as a settled split.

- [x] FR-1a.5 — One damaged product is one claim line, through the same machinery as five.
  - **Conclusion:** there is no special case anywhere for a single-product claim, and a
    test proves the one-product path is the ordinary path.

## Layer 1b — Investigation, per claim line

- [x] FR-1b.1 — One agent run per damaged product, which assesses, recommends and drafts
  for that product alone.
  - **Conclusion:** the run chooses which photographs to look at and what to ask about
    them; the rules then settle the outcome and the amount in a fixed order that never
    depends on the model.

- [x] FR-1b.2 — Each run sees the whole claim: the full description, every image, every
  order line, and what the other products are.
  - **Conclusion:** it needs the wider view to read the evidence properly — a photograph
    showing two broken items matters to both. Scope of *responsibility* is one product;
    scope of *knowledge* is the claim.

- [x] FR-1b.3 — Products reach their outcomes independently, and are investigated at the
  same time as each other.
  - **Conclusion:** each has its own step allowance, so a complicated product cannot
    starve a simple one, and a weak product cannot drag down a well-evidenced one. A
    claim with two products spends three allowances: one for the split, one each.
  - **Be aware:** the whole-claim cap is the single exception, and it has to be — see
    FR-1.20.

- [x] FR-1b.4 — A product reaches the same answer whether it was claimed alone or beside
  five others.
  - **Conclusion:** this is structural rather than a hope about the prompt. Ambiguity is
    judged against the **order's** line items, which are the same however the claim was
    split, never against the sibling claim lines, which are not. The functions that
    decide the outcome and the amount are handed nothing at all about the neighbours.
  - **Be aware:** proven by investigating one product alone and then beside five others
    and comparing the evidence, the judgements, the recommendation and the amount. What
    that test cannot prove is anything about a real model — it is scripted. See DESIGN.md.

## Layer 1 — Shared agent requirements

- [x] FR-1.1 — A tool-use loop, not a fixed sequence: the agent chooses what to look at
  next and stops when it can justify a recommendation.
  - **Conclusion:** built as a LangGraph state graph — think, act, conclude — where every
    edge out of "think" is decided by what the model just said. A claim with no images
    concludes on its first move; one with six spends as many as it needs.
  - **Be aware:** two limits bound a run and only one may ever stop it. A state graph
    enforces its own move limit by *raising*, and a run that raises loses what it found,
    which FR-1.16 forbids — so the graph's limit is derived from the step allowance and
    kept deliberately looser. A test proves the step allowance is what trips.

- [x] FR-1.2 — Eleven read and reasoning tools: the four original investigation primitives and
  seven deterministic cross-checks over claim data.
  - **Conclusion:** structural, not an instruction. One function assembles the tools, and
    tests assert the names are exactly the eleven specified in REQUIREMENTS.md, that no agent
    module can even import the package where sending and paying will live, and that the only
    ShipBob client the agent holds has no method that writes.
  - **Be aware:** the case and shipment are bound when the tools are built, so the agent
    cannot ask to see another case's images or price an unrelated shipment.

- [x] FR-1.3 — Bounded steps and bounded retries per run, and it always terminates.
  - **Conclusion:** the allowance lives in the run's own budget object and is never
    written into the prompt — a limit the model can read is a limit it can argue with.
    Proven with a model scripted to ask for tools twenty times against a three-step
    allowance: it stopped at three with its findings intact.
  - **Be aware:** budgets are per run, so a claim with four products has five allowances
    rather than one divided five ways. Handing over a budget that has already spent a
    step is refused outright.

- [x] FR-1.4 — What each attachment actually is, decided by looking at it.
  - **Conclusion:** file names and content types are carried and never read. ShipBob's
    real data makes the case better than the requirements do: every attachment is a PNG
    or JPEG whatever it holds, and one image appears in two different cases under two
    different names on one signed URL.
  - **Be aware:** the media type is sniffed from the bytes too, so a JPEG served as
    `image/png` is still read as a JPEG.

- [x] FR-1.5 — An attachment too blurry, dark or cropped to rely on does not satisfy its
  requirement, and the reason is recorded.
  - **Conclusion:** there are **three** ways to not have a piece of evidence, not two.
    Missing, unusable, and unreadable-by-us are kept apart, because only the first two
    are things a merchant can fix.

- [x] FR-1.6 — Nothing is inferred, assumed or partly approved: a missing or unusable item
  means going back to the merchant.
  - **Conclusion:** enforced by a rule over the model's answer, not by asking the model
    to behave. Code can withhold an approval the requirements forbid and can never move a
    recommendation towards paying.

- [x] FR-1.7 — A request names the specific gap, never "more information".
  - **Conclusion:** the gaps are worked out in code from the evidence findings, so the
    list is never the model's invention; the wording for each of the four is in one file.
  - **Be aware:** that wording is ours and nobody at ShipBob has approved it. An image
    *we* could not read never produces a request, because the merchant cannot act on it.

- [x] FR-1.8 — Is the damage visible in the photographs.
- [x] FR-1.9 — Can the damaged product be identified.
- [x] FR-1.10 — Does that product appear on the invoice.
- [x] FR-1.11 — Is the outer packaging documented.
  - **Conclusion:** all four are reported whatever they found, in a fixed order, each with
    its own reasoning — so a rep can disagree with one without discarding the other three.
    FR-1.11 is about a photograph *existing*, not about the
    box being damaged: an intact box with a broken product inside is a good claim.
  - **Be aware:** FR-1.10 is judged against ShipBob's *generated* invoice, not the invoice
    image the merchant uploaded. Which document each rule means is our reading, and the
    real data shows the two genuinely disagree — see DESIGN.md's questions.

- [x] FR-1.12 — A failed judgement requests representative clarification, naming what is wrong.
  - **Be aware:** a question answered "no" and a question *never answered* are different
    problems and no longer share a label. An unanswered question is our unfinished work,
    so it goes to the representative. A genuine "no" also stays internal only after any
    concrete merchant-fillable gap has been separated into `request_info`.

- [x] FR-1.13 — Where the damaged item is ambiguous, the system asks instead of choosing.
  - **Conclusion:** CASE-1002 is the real example and the photographs bear it out — a
    broken CleanBoss bottle whose label does not say which of two 24oz products at
    different prices it is. A legible label, corrected document, product name, or quantity is
    a concrete merchant request, so this path returns `request_info` and an email. Only an
    ambiguity the merchant cannot resolve stays with the representative.

- [x] FR-1.14 — One of three next actions, and nothing else.
  - **Conclusion:** `approve`, `request_info`, or `request_rep_clarification`. Escalation and
    denial are not outcomes. The rules can withhold a payment the requirements forbid, and what
    the agent proposed is kept beside the result so a rep can see where the two differed.

- [x] FR-1.15 — Never recommend approval under uncertainty.
  - **Conclusion:** weak or conflicting evidence blocks approval. A concrete merchant-fillable
    gap remains `request_info`; otherwise the action is `request_rep_clarification`. The model is
    not asked for a subjective confidence score.

- [x] FR-1.16 — An exhausted budget requests rep clarification, carrying whatever was established.
  - **Conclusion:** exhaustion is an *answer*, not an error, which is why the budget is
    polled rather than raising — an exception would unwind the stack holding the findings.

- [x] FR-1.17 — Nothing is presented as settled, and the email is a draft.
  - **Conclusion:** `is_draft` cannot hold any other value, and the word "draft" is
    refused *inside* the wording, because a marker in the body is a marker that can reach
    a merchant. The subject is checked too.

- [x] FR-1.18 — The amount is priced from the invoice.
  - **Be aware:** a shipment ShipBob will not price requests rep clarification with that as the stated
    reason. It never falls back to the order's prices — they happen to be identical in the
    sample data, and silently swapping the source would put a figure in front of a rep
    that did not come from where the report says it came from.

- [x] FR-1.19 — Only the damaged items are covered, not the whole order.
  - **Conclusion:** the items a claim covers are read off the invoice for context — what
    the goods cost, shown beside what is being recommended for them. Nothing is worked out
    from the whole order.
  - **Be aware:** what an item cost is deliberately **not** a limit on what is recommended
    for it. A claim may reasonably come to less than the goods did, and nothing in the
    requirements says it may never come to more — so nothing clamps it. Whether it should is
    in DESIGN.md's questions rather than decided quietly.

- [x] FR-1.20 — The amount is capped, per product **and** across the claim.
  - **Conclusion:** the cap is now the *only* limit on a payout, which makes it the single
    most load-bearing number in the system. The claim-level check is still the point: three
    products at $50 are each fine and together are not, so a cap that only ever saw one
    product could be got round by splitting a claim into more of them. Over the cap nothing
    is trimmed and nothing is chosen between — every product recommended for payment goes to
    a person.
  - **Be aware:** whether the cap means per product or per claim is REQUIREMENTS open
    question 2, so which applies is a setting. This is the single place a product's outcome
    depends on what else was claimed beside it, which is why it sits apart from everything
    FR-1b.4 guarantees.

- [x] FR-1.21 — The agent decides the amount; code holds it to the cap.
  - **Conclusion:** the agent judges what the damage is worth from the photographs and from
    how comparable claims were settled, names a figure, and a pure function caps it. How
    badly a thing is broken is a judgement, and the fixed share this replaced could not tell
    a scuffed box from a smashed bottle.
  - **This reverses what the requirement used to say, and the cost is real.** No figure could
    come from model output at all before, and the number in front of a rep was arithmetic she
    could check. It is now an estimate to weigh: two investigations of one claim may propose
    different figures, and the cap is the only thing bounding either. REQUIREMENTS.md and
    CLAUDE.md were amended to match rather than left describing a system that no longer
    exists.
  - **Two guarantees survived, and they are the ones to defend.** Money is read as text into
    an exact decimal and never through a float — anything not exactly money is refused rather
    than interpreted, and the claim goes to a person. And **no figure the model wrote reaches
    a merchant**: the model leaves money out of the email and code appends the amount *after*
    the cap, so a proposal of $180 on a $100 cap sends $100 and never $180. New drafts contain
    no placeholder; the finalizer safely resolves the marker in older drafts.
  - **Be aware:** past claims' settled amounts are now shown to the agent, having been
    deliberately withheld before. That was the whole basis of "judge it against similar
    claims", and withholding them left the instruction with nothing behind it.

## Layer 2 — The report

**Read this first.** The agent returns two distinct outputs: one structured **claim report** and,
when the action is merchant-facing, one **email draft**. The backend persists the report fields and
conditional email separately within the report record, and the UI renders each once. There is no
second prose document and no Markdown to parse back into data.

Reports are written down by the investigation endpoint, including the claim-level report for a
claim stopped by screening. Asking for screening alone still keeps nothing.

- [x] FR-2.1 — the next action and any approved amount lead the report, worded as something a
  representative is deciding on rather than something that happened.
  - **Conclusion:** `request_info` reports also carry a structured list of the exact merchant
    details needed, which the UI shows before the supporting evidence.
  - **Conclusion:** a claim the quick checks stopped recommends **nothing** — the three
    actions are about a damaged product and it has none. `domain/decision.py` had already
    ruled this for a decision, so the report follows it rather than inventing a mapping.
  - **Be aware:** what the representative settled on is kept beside what was advised, so a report
    approved at a different figure never shows only the old one.
- [x] FR-2.2 — all four pieces of evidence, each naming the image it came from.
  - **Be aware:** a piece nobody found is written out as missing rather than left off, so a gap is
    seen rather than inferred from silence.
  - The structured report embeds every attachment URL and the UI renders the images with a
    full-size link, so a representative need not leave the report to inspect its evidence.
- [x] FR-2.3 — each question with its reasoning, without a subjective confidence percentage.
  - **Be aware:** a question **missing** from the structured list was never answered, which is not
    the same as answered no. The UI says so rather than making a reader infer it.
- [x] FR-2.4 — which items at which prices, from which document, and what the limit did.
  - **Be aware:** it is written even where nothing would be paid — "nothing, and here is why" is
    something a representative can act on. The figure is the AI's judgement of the damage, not the
    sum of the prices shown; the prices are there to weigh it against.
- [x] FR-2.5 — concerns, and never silence.
  - **Conclusion:** a report with nothing worrying says so rather than showing an empty heading.
    A stopped claim carries its own reasons and findings in screening content.
- [x] FR-2.5a — decidable at a glance, checkable below.
  - **Conclusion:** the default view leads with action and the approved amount,
    merchant requests, or a short rep clarification. Reasoning, concerns, images, evidence,
    questions, context, and amount working stay available in labelled expandable sections. The
    report has no inner scrollbar, and prompt/schema rules keep each field short and non-repetitive.
- [ ] FR-2.6 — the two things this asks for are already computed and already reach the model:
  the high-value flag and the merchant's past corrections. What is missing is a rep-facing
  report to put them on, and the third clause — *which* past correction influenced this
  recommendation — needs the decision record of FR-C.1 before there is anything to name.
  **Still unticked, and now for one reason only.** The high-value flag and the merchant's past
  corrections are both on the report. What is missing is the third clause: `corrections_considered`
  gives *which* past correction changed the conclusion and can never say *how*, because that is all
  the AI is asked for. Widening what it is asked for is the work left.
- [x] FR-2.7 — the conditional merchant email, in the exact wording that would be sent.
  - **Conclusion:** approval emails communicate the approved amount; information requests name
    the specific details the merchant must provide; rep-clarification reports carry no email.
  - **Be aware:** it is a separate structured field rendered once by the report card. A rewording
    replaces its subject and body, while its recipient always comes from the claim.
- [x] FR-2.8 — all three actions. Approving works, rewording the email before approving works
  (which is a flag on the approval, not an action of its own — FR-2.8 reads it that way and
  `RepAction` already said so), and sending a report back now records the note **and** gets the
  report reworked around it.
  - **Conclusion:** the third action was the one that had nothing behind it. It has Layer R
    behind it now, so the note reaches the agent that wrote the report and comes back as the
    next version of it.
  - **Be aware:** the substance/wording line the requirement draws is enforced by where each
    action goes, not by asking. A rewording only ever replaces the email's subject and body on
    an approval; anything about what the report *says* has to go through feedback.
- [x] FR-2.9 — approving is the only exit, and it is final.
  - **Conclusion:** written as an explicit state machine and tested transition by transition.
    `approved` is terminal: it cannot be sent back, and a *different* approval on it is refused
    rather than quietly replacing a decision a person took. Nothing else reaches `approved` — no
    time limit, no automated score, no number of rounds.
  - **Be aware:** the same approval arriving twice changes nothing and records nothing, so a
    double-click leaves one decision. Two *different* notes sent back are two decisions and both
    are kept.
- [x] FR-2.9a — the other products on the claim, beside each report.
  - **Conclusion:** looked up when a report is read, **never stored inside it**. A sibling's review
    state changes the moment somebody approves it, and a stored copy would say "waiting" beside a
    product approved ten minutes ago — which is the exact case the requirement's own example is
    about.
- [x] FR-2.9b — a claim-level view over the line reports.
  - **Be aware:** it shows each product at the version in force, never every version of every one.
    Layer R is unbuilt so every report is version 1 today, which is exactly why this was easy to
    get wrong.
- [x] FR-2.10 — the persisted report contains structured screening or investigation content. The
  UI lays out those fields directly; the investigation result does not also send a prose report or
  a second raw investigation object for the UI to render.

## Layer R — Revision

- [x] FR-R.1 — a rework runs when a representative sends a report back, and on nothing else.
  - **Conclusion:** there is one caller, `POST /reports/{id}/send-back`, and it records the note
    as a decision before it starts. Nothing schedules, retries or triggers a rework by itself.
  - **Be aware: every message reaches the agent, whatever the report is.** The first cut of this
    refused anything that was not an investigated product's report and answered with a canned
    sentence — which broke the one case that mattered most, a report whose whole purpose is to
    ask the representative a question refusing the answer to it. What a message may *change* is
    still decided by report kind, in `report/conversation.py`; whether it gets an answer is not.
- [ ] FR-R.1a — **half.** A rework touches one product's report and leaves its siblings alone,
  which is the first half. The second half — feedback about evidence the whole claim shares
  propagating to every line that relied on it — is **not built**. The agent flags such a note and
  the reworked report carries a concern naming the other products, so a representative knows to
  send each of them back by hand. Do not tick this until the propagation exists.
  - **Be aware:** there is now one case where a message *does* reach every product on a claim —
    a representative settling what an unsettled claim is for has the whole claim investigated
    again (FR-1a.4). That is a different mechanism and it does not satisfy this requirement:
    it redoes the claim from its evidence rather than propagating one corrected finding.
- [x] FR-R.2 — the rework starts from the report in full, not from zero.
  - **What was built:** the run is handed the report's findings, judgements, figure and working,
    concerns and email, the whole conversation so far, and the case re-read from ShipBob. It does
    not re-split the claim and does not touch the other products.
  - **Be aware:** the case is re-read rather than remembered, because a report stores no copy of
    it. That is three cheap reads and it means a rework is built from ShipBob's records now.
- [x] FR-R.3 — the earlier findings go in as observations of record, and the note is authoritative.
  - **Be aware:** this is a wording guarantee, not a structural one. `agent/prompts.py` frames the
    findings in the passive and says the representative is right about what is wrong; nothing
    measures whether the model actually stops defending itself. DESIGN.md lists it under **Could
    break**.
- [x] FR-R.4 — the rework holds the investigation's tools, so it can look again where the note
  points. Targeted by wording; nothing forces or forbids a second look.
- [x] FR-R.5 — undisputed findings carry forward, **and code is what carries them**.
  - **Conclusion:** the rework's answer is merged over the earlier report's before any rule runs,
    so an answer that mentions only the thing being corrected keeps everything else. Left to the
    wording alone this was the most dangerous case in the layer: an approval would have collapsed
    because somebody queried one sentence.
- [x] FR-R.6 — the same tool surface, tested by reading the tools the run was actually offered
  and comparing them with the whole enumerated list.
- [x] FR-R.7 — a reconsidered figure goes through the same controlled path as the first one.
  - **Conclusion:** it is literally the same function. `settle_conclusion` in
    `agent/investigate.py` settles a first answer and a reworked one alike, so the cap, the
    parsing and the rules cannot drift apart between the two.
  - **Be aware:** the per-claim cap is *not* reapplied across siblings on a rework. That check
    needs every product's figure at once, and a rework answers for one product.
- [x] FR-R.8 — the rules do not give way, and the agent says so rather than complying quietly.
  - **Conclusion:** for a claim the quick checks stopped, the *agent* says so, with the actual
    reason in front of it — "filed 73 days after delivery and the limit is 60" rather than a
    canned refusal. That is what the requirement asks for. The only thing it may change about
    such a claim is the merchant email's wording, and that is enforced by which fields the code
    reads rather than by the prompt.
  - **Be aware:** a claim that names no product can never be given an amount either, because
    nothing on it was ever priced. A representative asking for one gets a fresh investigation or
    an explanation, never a figure.
- [x] FR-R.9 — a complete revised report, in the same structure. The answer form is the
  investigation's form **subclassed**, with three fields added, so "same schema" is true in code
  rather than by intention.
- [x] FR-R.10 — what changed and what was left alone, both stated, both shown on screen.
- [x] FR-R.11 — the email is rewritten from the reworked answer, through the same builder, with
  the capped figure added by code afterwards.
- [x] FR-R.12 — every round carries the full history, and the agent is told that earlier
  corrections still stand.
- [x] FR-R.13 — every version is kept, with the note that prompted it and what changed.
  - **Be aware:** **every** note produces a version, including one whose rework failed — that
    version's findings are the previous ones and its round says so. A model that could not be
    reached must not be able to degrade a sound report.
- [x] FR-R.14 — the note is remembered against the merchant, so their next claim starts with it.
  - **Be aware:** it is stored in the representative's own words, unjudged. FR-C.2's rule that a
    correction comes from a *difference* governs approvals; a note is a correction by definition.
    The cost is that a merchant sent back four times over a typo accumulates four notes — see
    DESIGN.md's **Could break**.
  - **This also builds the writing half of FR-3.8**, which had a tested store and no caller. That
    requirement stays unticked because FR-C.2's other writer, from an approval that differed, is
    still missing.

## Layer 3 — Execution after approval

- [ ] FR-3.1
- [ ] FR-3.1a
- [ ] FR-3.2
- [ ] FR-3.3
- [ ] FR-3.4
- [ ] FR-3.5
- [ ] FR-3.6
- [ ] FR-3.7
- [ ] FR-3.8 — **most of it, but not all.** The reading half has always worked, and the writing
  half now has one caller: sending a report back writes the representative's note against the
  merchant (FR-R.14). What is still missing is FR-C.2's other writer — a correction derived from
  an approval that *differed* from the recommendation — so a representative who silently approves
  at a different figure still teaches the system nothing.

## Claim precedent — finding similar past claims

- [x] FR-S.1 — A record written only when a claim line is closed, named after that line so
  closing it again replaces its record rather than adding a second.
  - **Conclusion:** being in the store *means* a representative decided it. That is the whole
    guard against the feature going circular — an earlier version stored every investigated line
    and marked the unreviewed ones, which let the system be shown its own guess as precedent.
    Removing them at the source deleted the marking, the three tiers of authority, the ranking
    tie-break and the prompt wording that explained them all.
  - **Be aware:** nothing closes a claim yet, so nothing writes a record. Capture is a pure
    function in the domain and its only callers are the tests, exactly as merchant memory's
    writer was.

- [x] FR-S.2 — **Removed.** Required every record to carry what a representative did about it,
  so a decided outcome could be told from an unreviewed suggestion. FR-S.1 now keeps unreviewed
  lines out of the store, so there is nothing left to distinguish.

- [x] FR-S.3 — A record holds the merchant's words, the product and its price, the evidence
  pattern, the four judgements, the outcome it closed on, the amount paid, the cap, and any note
  the representative left.
  - **Conclusion:** the test applied was a human one — could somebody read this and say "yes,
    that is the same situation"? The whole record is stored as JSON in one column, because
    nothing queries inside it: the careful comparison happens in Python on a handful of rows.
  - **Be aware:** the amount and unit price are stored but never rendered into a prompt. A model
    forbidden to write a figure must not be shown one (FR-1.21); a test enforces that.

- [x] FR-S.4 — Similarity over five signals: the merchant's wording, the product name, the
  price, the evidence pattern, and how the product related to the order.
  - **Conclusion:** nothing is an equality test. Two claims resemble each other by degree and a
    signal that cannot be compared is dropped, with the remaining weights shared out again —
    otherwise a missing price would make a claim look unlike everything in the store.
  - **Be aware:** identifiers cannot contribute, because the tokeniser keeps letters only. The
    weights are ours and untuned; they are module constants rather than policy values because
    only their ratios mean anything. Adding a sixth signal is one entry in `_signals`.

- [x] FR-S.5 — One bounded retrieval per claim line, between triage and investigation, with
  both knobs in the policy file.
  - **Conclusion:** SQLite's own full-text index narrows the store cheaply, then the domain
    scores that handful. That is what keeps retrieval accurate without a vector database, an
    embedding model, or a second credential.
  - **Be aware:** `precedent_results_per_line` and `min_precedent_similarity` are provisional and
    marked off the admin panel, like the other values the unbuilt investigation reads. Both are
    now overridable per request on `POST /precedent/search`, which is the one place a caller can
    see the effect of changing them.
  - **Also exposed over HTTP.** `POST /precedent/search` runs the same comparison the
    investigation is given, and `GET /precedent/{id}` reads one record in full so a cited
    precedent can be checked. The search returns each record with its score and the reasons it
    was thought alike; an empty answer says whether the store was read or unreadable. No
    sign-in, like the policy panel.

- [x] FR-S.6 — Precedent arrives as starting context and is never a tool the model may call.
  - **Conclusion:** the rules for weighing it live in the fixed system wording; the records
    themselves go into the claim's own question, beside the merchant's description. If looking
    were optional, two runs of one claim could differ purely in whether the model thought to
    look — the variance NFR-1 forbids, caused by the feature meant to reduce it.
  - **Now actually connected.** `investigate_claim` takes a store, looks each product up after
    the split and before the runs fan out, and hands each run its own set; `investigate_line`
    passes it into the prompt. Until this, everything else worked and the investigation was
    still none the wiser.
  - **Be aware:** `build_investigation_messages` takes `precedent=None` by default, and that
    renders no section at all. "Nobody looked" and "we looked and found none" read differently.
  - **Be aware:** the lookup is one blocking read per product, done before the runs start so it
    does not hold up work that is meant to happen at once. The records go in the claim's own
    question, not the standing instructions — those are also sent when asking what a single
    photograph shows, where past claims would be paid for and read for nothing.

- [x] FR-S.7 — **Removed.** Required the agent to weigh a record by who decided it. Every record
  is now a decision somebody stood behind (FR-S.1), so they all count the same and there is
  nothing to weigh.

- [x] FR-S.8 — Precedent cannot stand in for evidence or override a rule.
  - **Conclusion:** this is structural rather than a prompt promise. Precedent reaches the model
    only as text; the amount is still arithmetic (FR-1.21); and `decide_outcome` still withholds
    approval on incomplete evidence whatever the model concluded. The prompt is the advisory
    half on top of that.
  - **Be aware:** the test naming this id checks the wording only. The guarantee is the existing
    override machinery, covered by the outcome tests.

- [ ] FR-S.9 — Not built. Retrieval records which precedents it used and why, but no report
  shows them to a rep, because the Layer 2 report does not exist.

- [ ] FR-S.10 — Partly. The prompt tells the model to say when it departs from how alike claims
  were handled, and a test covers that wording; nothing puts the departure on a report as a
  concern, which is what the requirement asks for.

- [ ] FR-S.11 — Not built. The retrieved set is returned as a value a run could pin, but nothing
  persists it against the run, so the same claim investigated twice can see a store that has
  grown. This is the requirement that keeps NFR-1 true, and it waits on the report and the audit
  trail.

- [ ] FR-S.12 — Partly. The system wording forbids mentioning another merchant's claim in the
  email and a test covers it, but nothing checks the written email for a leak the way
  money-shaped text is checked. Advisory only until there is a check.

- [x] FR-S.13 — Three distinct answers: records found, store read and holding nothing, store
  unreadable. Each renders differently, and a broken store never stops the claim.
  - **Conclusion:** deliberately the opposite of merchant memory, which fails loudly. Merchant
    memory has no way to say "unknown", so empty would be indistinguishable from a clean record;
    here the answer can say which happened, so it does.
  - **Be aware:** if you ever collapse "could not be read" into "none found", you tell a rep
    there is no comparable history when nobody actually looked.

- [x] FR-S.14 — A record can be withdrawn from retrieval without being destroyed.
  - **Conclusion:** withdrawal drops it from the search index and leaves the row; `get` still
    returns it, so a withdrawn record stays inspectable and the audit record survives (NFR-5).
  - **Be aware:** withdrawing is still not reachable over HTTP — it needs a console today. The
    read side is exposed: `GET /precedent/{id}` returns a withdrawn record, marked withdrawn, so
    a bad precedent can at least be found and inspected before somebody removes it. This matters
    more now than it did: with only closed claims stored, a wrong decision is the only kind of
    bad precedent there is, and withdrawal is the only way back out.

## Carry-forward — what a rep decided, and what the next claim knows

**Read this before starting.** FR-C.1 is built — a review action now leaves a durable record —
and FR-R.14 was finished on the back of it: a report sent back writes the representative's note
against the merchant. What is still missing is the rest, and in particular the two writers that
would close the loop: a correction derived from an approval that *differed* from the
recommendation (FR-C.2), and the closing of a claim line that would make it precedent (FR-C.3).
So FR-3.8 is most of the way there and FR-S.1's writer has no caller at all.

What already exists, so it is not rebuilt:

- **Merchant memory, read side.** `corrections_for(user_id)` → `preflight/service.py` →
  the computed context → the agent's prompt → the rep's screen. Done under FR-0.5.
- **Merchant memory, write side.** `MerchantMemory.record_correction` works and is tested, and
  it now has a real caller: the send-back route writes the representative's note against the
  merchant (FR-R.14). `tools/seed_merchant_memory.py` still writes invented data on purpose,
  beside it.
- **Precedent, read side.** Retrieval, similarity, the per-line lookup, and two HTTP routes. Done
  under FR-S.1–FR-S.8 and FR-S.13.
- **Precedent, write side.** `capture_closed_line` in `domain/precedent.py` and
  `PrecedentStore.record` both work and are tested. Their only callers are the tests, because
  nothing closes a claim line.
- **Execution.** `execution/` holds a docstring and nothing else. Layer 3 is unbuilt, so an
  approval has nowhere to take effect.

So the work is a capture point and two writes, not two stores. Suggested order: FR-C.1 first,
because FR-C.2 and FR-C.3 read it and neither can be built without it; then FR-C.4 alongside them,
since retry-safety is cheaper to build in than to add; then FR-C.5–FR-C.6; FR-C.8 last, since a
demonstration needs the rest to exist. FR-C.7 is a question for whoever owns the requirements and
should be asked, not answered here.

- [x] FR-C.1 — the decision record. Sits between FR-2.8 (what a rep may do) and FR-3.1 (what an
  approval releases), and belongs to neither: recording a decision sends nothing. Two things to
  design around: `decided_by` cannot be filled in, because there is no sign-in anywhere in this
  service, and a claim stopped in Layer 0 has no claim lines to key a decision to — it is never
  split. A record that insists on a line cannot hold the one decision that costs nothing to reach.
  - **Half of this now exists, and it is the half that stores.** The record and its store were
    built for the analysis screen (UI-33 onward in [UI-TODO.md](UI-TODO.md)):
    `domain/decision.py` in the shape this requirement describes, and a `rep_decisions` table
    beside merchant memory and precedent. Both design problems above are handled — `decided_by`
    is present and always empty, and `claim_line_id` is optional so a stopped claim has somewhere
    to sit.
  - **The other half exists now: the capture point.** Approving a report or sending one back
    writes exactly one record, in `report/review.py`, and the route that does it is the only
    caller in `src/`. `tools/seed_analysis_history.py` still invents history for demonstrations
    and still says so, so a machine can hold both — invented decisions and real ones.
  - **Be aware: repeating a decision is safe, and two different ones are never collapsed.** A
    decision is named from what it was about and *which* decision on that report it is, so the
    same approval twice writes over itself and two different notes sent back on one report stay
    two records. The decision is written **before** the report is moved on, so a failure between
    the two heals itself on the retry rather than losing what a person chose.
  - **Be aware:** the record carries fields this requirement does not mention — including a
    nullable legacy confidence field, what the order was worth, who carried the parcel, and what
    the merchant reported. They are copied off the report rather than joined to it, which was the
    plan when there was no report store; the join is still worth building, and now there is
    something to join to.
  - **Be aware: nothing measures how long a review took.** It is accepted from whoever calls and
    is nothing by default, so every saving worked out from it is an upper bound. Out of scope
    here, and written up in DESIGN.md.
- [ ] FR-C.2 — the merchant correction, written only where the decision differs from the
  recommendation. Store already exists; the difference test and the wording do not.
- [ ] FR-C.3 — the close event that writes precedent. FR-S.1 says when a record is written;
  this says what closes a line, and it is not the same thing as an approval being recorded — a
  failed send leaves the line open (FR-3.6).
- [ ] FR-C.4 — one correction and one precedent record however many times a decision is repeated,
  and a failed write that never fails the decision.
- [ ] FR-C.5 — a report naming the correction that influenced it, and a correction naming the
  decision it came from. The backwards half is what makes FR-C.6 safe to use.
- [ ] FR-C.6 — withdrawing a correction, as FR-S.14 already allows for a precedent record.
- [ ] FR-C.7 — **a question, not an implementation.** High value is computed, shown, and acted on
  by nothing. Ask which of the three readings in REQUIREMENTS.md is intended before building any
  of them; option 1 is what exists today, so "no change" is a legitimate answer that only needs
  writing down.
- [ ] FR-C.8 — the constructed data that makes any of this demonstrable. Five sample cases, five
  merchants, no two alike, so nothing carries forward on the real set. Follow the rules
  `tools/seed_merchant_memory.py` already sets: outside `src/`, invented in its own words,
  written through the real store, removable again.
  - **When that seeder can be deleted, so it does not linger by default.** Not when FR-C.1 and
    FR-C.2 land. Its seeding half becomes redundant only once three things hold together: the
    write exists (FR-C.1, FR-C.2), a rep can actually decide something (FR-2.1–FR-2.8), and the
    demo data holds a second case for a merchant who already has a decided one. Without the
    third, a real correction is written and no later claim ever sees it — invisible real history
    is a worse demonstration than visible invented history, not a better one.
  - **Be aware:** its `--clear` half has no replacement even then. `MerchantMemory` deliberately
    has no delete method, and FR-C.6 is *withdrawal*, which keeps the record and only hides it
    from later claims. Emptying the store between demonstrations still needs something.

## Non-functional requirements

- [ ] NFR-1 — Partly, and the part that is missing is the model itself. Everything around
  it is proven identical run to run: the arithmetic, the rules, the ordering of every
  list, the claim-line identifiers, the drafted email. The reading of a photograph is not,
  and cannot be with the tools available — temperature 0 asks for the most likely answer
  rather than a repeatable one, and a model can change behind its own name. Every result
  records the prompt version and the model id so two differing runs can at least be told
  apart. Do not tick this until there is either a pinned model or a recorded-and-replayed
  transcript.

- [x] NFR-2 — Every model answer is a form with named fields, and one that does not fit is
  refused rather than patched up.
  - **Conclusion:** the conclusion of each pass is a separate structured call rather than a
    twelfth "submit" tool, deliberately: FR-1.2 enumerates eleven read and reasoning tools, and a
    separate call is what guarantees the answer conforms.
  - **Be aware:** a malformed answer is not re-asked. The identical question asked the
    identical way is the least likely thing to come back differently, so the product goes
    to a person instead. A single reshaped retry would recover some of those — see DESIGN.md.

- [ ] NFR-3 — Partly, and closer than it was. Every conclusion traces to the observation that
  produced it, and **that now survives the connection**: a report is written down and can be
  fetched back, so "why this amount?" can be answered tomorrow as well as today. What is still
  missing is the run itself — what the investigation did and saw, in order, is not kept, and
  neither is which past claims it was shown. So a report can be re-read and the working behind
  how it was reached cannot.

- [x] NFR-4 — Every failure ends with a person, and none ends in a payment or a dropped case.
  - **Conclusion:** proven for an exhausted budget, a model that cannot be reached, a reply
    that will not fit its form, a plain timeout, an image that cannot be fetched, a tool
    that breaks, a shipment ShipBob will not price, and an email the model wrote money into.
    Each returns a result a rep can act on rather than raising.
  - **Be aware:** the honest distinction throughout is between what the merchant can fix and
    what only we can. An image we failed to download never produces a request to the
    merchant — the pre-flight screen has one label that makes exactly that mistake, and
    DESIGN.md records it as a fault rather than a pattern to copy.

- [ ] NFR-5 — Partly. **The human half is built:** every review action is a durable record, in
  order, saying what was chosen and what changed, and each round is written into the report
  itself under its own numbered heading. **The agent half is not:** each run keeps an ordered
  record of what it did and saw, it travels in the reply, and nothing stores it or fills in the
  times. Neither is what was ultimately sent, because nothing sends anything yet.

- [ ] NFR-5a — Not applicable yet. There is no revision loop to converge.

- [x] NFR-6 — Unavailable APIs, missing credentials and unreachable images are handled
  states with clear messages.
  - **Conclusion:** the service still starts with no model credentials; only a request that
    actually needs the model is turned away, and it says which setting is missing rather
    than blaming the provider. Attachment downloads are bounded by host, size and time, and
    refuse a lookalike host without making a request at all.
  - **Be aware:** the whole suite runs with no network and no key — the model is scripted
    and ShipBob is intercepted in-process — which is what makes the system demonstrable
    without live access. Images are the exception: they are fetched from real signed URLs
    the first time and cached locally after.
- [x] NFR-7 — Policy values are read from the environment with a `POLICY_` prefix.
  - **Conclusion:** changing a threshold needs no code change and no redeploy of logic.
  - **Be aware:** now genuinely consumed, which was the open question here. Raising
    `POLICY_MAX_CLAIM_AGE_DAYS` to 90 turns CASE-1004 from stopped into carried-on, end to end
    over HTTP — that is the demonstration, not the unit test.
- [x] NFR-8 — An ineligible claim costs no AI at all, and an image is looked at once per
  claim rather than once per damaged product.
  - **Conclusion:** the expensive work is reading photographs, so answers are memoised per
    claim behind a single-flight lock — two products asking the same question at the same
    moment share one analysis, and neither result depends on which got there first. The
    invoice and the attachment listing are fetched once for the whole claim too.
  - **Be aware:** CASE-1004 is the case that proves the first half. It has four attachments
    and dies on the age gate, so it is the only sample claim where images exist that must
    never be read.

---

## Work with no requirement id

Everything above traces to REQUIREMENTS.md. **The seven tools below do not.** They came from
reading ShipBob's mock API and the attachments on its five sample claims, and finding ways this
system could hand a representative a confident recommendation that was quietly wrong. Nobody at
ShipBob has agreed that any of them is right behaviour, so none of them can be ticked against a
requirement — they are listed here so the work is visible rather than invisible, and they are
explained in [DESIGN.md](DESIGN.md) under "Four tools that came from reading ShipBob's data, not
the requirements".

The investigation now holds **eleven** tools where it held four. Every one of them still only
reads or works something out; the guarantee that none of them writes is unchanged, and is still
checked by name and by import graph.

- [x] Currency — work out what money a claim is in, and convert it to dollars
  - **Built:** three clues (a symbol on the evidence, the country a tracking number ends in, the
    carrier) ranked and cross-checked, plus conversion from a fixed dated rate table in
    `policy.py`. Wired as the `check_currency` tool.
  - **Conclusion:** ShipBob's API has no currency field at all. CASE-1001 ships Royal Mail on a
    `GB` tracking number and its evidence reads `£55.95`, while its order totals a bare `90.00` —
    inside the $100 cap as dollars, over it as pounds. That claim was being measured against the
    wrong limit and nothing said so.
  - **Be aware:** the rates are invented and need sign-off. Two clues that disagree conclude
    nothing rather than picking a winner. **This should not be a tool** — it ought to be worked
    out before the run starts, the way precedent is, so two runs cannot differ over whether the
    model remembered to check.
- [x] Document arithmetic — read money off a photograph and check the paperwork adds up
  - **Built:** an exact reader for prices as documents write them, and a recomputation of a
    document's own totals. Wired as `check_document_totals`.
  - **Conclusion:** CASE-1002's sales order contradicts itself three ways — items summing to
    `46.93` under a printed subtotal of `49.85`, and a grand total of `49.42` matching neither.
  - **Be aware:** a figure it cannot read exactly comes back unread rather than guessed. The
    investigation still has to transcribe the totals in; nothing reads them off the image itself.
- [x] Case facts — read the facts buried in a claim's own description
  - **Built:** a deterministic parse of the description prose, and four contradiction checks
    against ShipBob's records. Wired as `read_case_facts`.
  - **Conclusion:** every description hides structured data in prose, and says `Carrier: Other`
    while the shipment record names a real carrier. CASE-1003 claims two affected orders while the
    case names one.
  - **Be aware:** CASE-1001's description is loose prose with no labels at all and names no
    carrier, so the carrier contradiction fires on four of the five sample claims, not all five.
- [x] Price reconciliation — compare ShipBob's prices with the customer's receipt
  - **Built:** per-line and whole-document comparison, wired as `compare_prices`.
  - **Conclusion:** the two disagree on **all four** sample claims that have evidence. CASE-1003
    is priced at `195.94` by ShipBob and was paid at `134.99` after a discount.
  - **Be aware:** it deliberately does **not** say which price is authoritative. Nobody has decided
    that, and until somebody does, a representative chooses on every claim where they differ.
- [x] Product matching — find which invoice lines could be the damaged product
  - **Built:** tiered scoring on codes and significant words, wired as `match_damaged_product`.
  - **Conclusion:** ShipBob and merchants write products differently — `Blue Razz Liquid Carnitine`
    against `liquid carnitine 3000` — so exact comparison fails on products that are obviously the
    same.
  - **Be aware:** two lines scoring alike are both reported and neither is chosen (FR-1.13).
- [x] Evidence sufficiency — say whether there is enough to recommend anything
  - **Built:** which kinds are missing, the exact sentence to ask the merchant for each, and a
    separate list of what only a person here can fix. Wired as `check_evidence_is_enough`, which
    also reports the same photograph attached twice.
  - **Conclusion:** CASE-1005 has zero attachments and is already waiting on the merchant. The
    right answer is a named request, not a priced verdict.
  - **Be aware:** it keeps "the merchant sent nothing usable" and "we could not read it" strictly
    apart, because only the first may be asked about.
- [x] Requested remedy — work out what the merchant actually asked for
  - **Built:** keyword rules over the merchant's own words, wired as `read_requested_remedy`.
  - **Conclusion:** CASE-1004's merchant asks for a replacement lid, on a claim filed as damage in
    transit, 73 days after delivery, on a case already closed. No reimbursement answers that.
  - **Be aware:** whoever built it recommends this **not** be a tool the model calls — it is a
    shallow reading of text the model already read more carefully, and feeding it back risks
    anchoring the model on the worse reading. It belongs on the representative's report as an
    independent cross-reference. It is wired as a tool anyway, which is a decision to revisit.

### Specified from the same review, not built

- [ ] Case state — whether a case is even answerable (`Closed`, `Waiting on Client`, an internal
  `@shipbob.com` contact address, a case opened before its own delivery date). The policy values
  it would read are already in `policy.py`; nothing reads them.
- [ ] Ambiguous dates — CASE-1001's evidence reads `Wed 11/02/2026`, which is 11 February read one
  way and a future date read the other. The 60-day age gate (FR-0.2) turns on which you believe.
- [ ] Order reference resolution — proving a document in a photograph belongs to this claim.
  Order numbers never match across systems: CASE-1003 is `337761802` to ShipBob, `#HS3449170` on
  screen and `Store Order # 344917` on its invoice. Reasoning over the wrong customer's invoice
  produces a confident, wrong recommendation.
- [ ] Related claims — the finding-claims half of `evidence_integrity.py` is built and tested but
  nothing calls it, because ShipBob's case listing returns a summary with no order, shipment or
  merchant on it, so relating claims means reading every case in full.
