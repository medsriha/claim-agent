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
  - **The refund percentage is editable from the panel**, deliberately, because it is the
    value most likely to need changing and its effect is immediately visible in the next
    claim's figures. It needed no UI change at all: the panel is generated from the policy
    file, and a whole number already had a control.
  - **Not every value is on the panel.** Marking one `NOT_ON_PANEL` in `policy.py` keeps it a
    policy value — read as always, still set from the environment — while the panel neither shows
    it nor accepts a change to it. Four are marked: the minimum description length, and the three
    the unbuilt AI investigation would read, where a control would change nothing observable.
  - **Be aware:** only the $100 cap is a real ShipBob figure. The age limit and whether it is
    inclusive, the high-value threshold, the claim-type wording, the minimum description length,
    the email reason order, the confidence threshold, the step budgets and the refund
    percentage are placeholders we
    invented
    so the code runs — they need sign-off before production. The refund percentage is the
    one with money directly behind it: at 60% a $52.00 item pays $31.20, and changing that
    number changes every payout after it.
  - **Be aware:** a change made through the panel is held in memory only and there is no sign-in
    on it. A restart silently puts every value back to what the environment says, and nothing
    records who changed what. Both were chosen knowingly for a demo — see DESIGN.md, "Future
    production".

## Layer 1a — Triage: splitting the claim into lines

**Read this before the ticks below.** Everything in Layer 1a, Layer 1b and Layer 1 is
built, tested and explained in DESIGN.md — but **none of it is reachable over HTTP yet**.
There is no route, so no representative can actually investigate a claim; the endpoint
and its wiring are the next piece of work. The ticks mean the behaviour exists and is
proven, not that the system can be used.

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

- [x] FR-1a.4 — An ambiguous split is handed to a representative, and no split is guessed.
  - **Conclusion:** three different things produce it — the model saying so, no products
    named at all, and a product matching two order lines. All three stop every
    per-product run, because nothing may be investigated until somebody has said what is
    being claimed for.
  - **Be aware:** the candidates are still listed so a rep can settle it in seconds. They
    are deliberately not presented as a settled split.

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

- [x] FR-1.2 — Read and reasoning tools only: list attachments, inspect an image,
  generate an invoice, compute an amount.
  - **Conclusion:** structural, not an instruction. One function assembles the tools, and
    tests assert the names are exactly those four, that no agent module can even import
    the package where sending and paying will live, and that the only ShipBob client the
    agent holds has no method that writes.
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
    its own reasoning and its own confidence — so a rep can disagree with one without
    discarding the other three. FR-1.11 is about a photograph *existing*, not about the
    box being damaged: an intact box with a broken product inside is a good claim.
  - **Be aware:** FR-1.10 is judged against ShipBob's *generated* invoice, not the invoice
    image the merchant uploaded. Which document each rule means is our reading, and the
    real data shows the two genuinely disagree — see DESIGN.md's questions.

- [x] FR-1.12 — A failed judgement produces a recommendation to go back to the merchant,
  naming the reason.
  - **Be aware:** a question answered "no" and a question *never answered* are different
    problems and no longer share a label. An unanswered question is our unfinished work,
    so it goes to a person; only a genuine "no" reaches the merchant.

- [x] FR-1.13 — Where the damaged item is ambiguous, the system asks instead of choosing.
  - **Conclusion:** CASE-1002 is the real example and the photographs bear it out — a
    broken CleanBoss bottle whose label does not say which of two 24oz products at
    different prices it is.

- [x] FR-1.14 — One of four outcomes, and nothing else.
  - **Conclusion:** the agent picks it, including refusing a claim. The rules only ever
    withhold a payment the requirements forbid, and what the agent recommended is kept
    beside the result so a rep can see where the two differed.

- [x] FR-1.15 — Never recommend approval under uncertainty.
  - **Be aware:** the confidence figure is the model's own opinion of itself, nothing has
    ever checked it against what turned out to be true, and the threshold is a number we
    invented. It now withholds real payments. This is the weakest link in the layer.

- [x] FR-1.16 — An exhausted budget escalates, carrying whatever was established.
  - **Conclusion:** exhaustion is an *answer*, not an error, which is why the budget is
    polled rather than raising — an exception would unwind the stack holding the findings.

- [x] FR-1.17 — Nothing is presented as settled, and the email is a draft.
  - **Conclusion:** `is_draft` cannot hold any other value, and the word "draft" is
    refused *inside* the wording, because a marker in the body is a marker that can reach
    a merchant. The subject is checked too.

- [x] FR-1.18 — The amount is priced from the invoice.
  - **Be aware:** a shipment ShipBob will not price escalates with that as the stated
    reason. It never falls back to the order's prices — they happen to be identical in the
    sample data, and silently swapping the source would put a figure in front of a rep
    that did not come from where the report says it came from.

- [x] FR-1.19 — Only the damaged items are covered, not the whole order — and only a
  share of what each one cost.
  - **Conclusion:** ShipBob refunds a percentage of a damaged item's price on an
    uninsured shipment, not the whole of it, and that percentage is a policy value
    because it is a commercial judgement rather than arithmetic. Both figures are kept
    on every result — what the item cost and what is refunded for it — so a rep sees the
    step between them rather than one unexplained number (FR-2.4).
  - **Be aware:** each item's share is rounded to cents *before* the items are added up,
    so the lines a rep reads add up to the total beside them. 60% of $49.99 is $29.994
    and becomes $29.99, in exact decimals throughout.
  - **Be aware:** the percentage says "if not insured", and nothing checks insurance here
    because nothing needs to: an insured shipment is routed out by the pre-flight screen
    and never reaches pricing (FR-0.2). If insured claims are ever priced here, this needs
    a second value and an explicit check.

- [x] FR-1.20 — The amount is capped, per product **and** across the claim.
  - **Conclusion:** the claim-level check is the point. Three products at $50 are each
    fine and together are not, so a cap that only ever saw one product could be got round
    by splitting a claim into more of them. Over the cap, nothing is trimmed and nothing
    is chosen between: every product recommended for payment goes to a person.
  - **Be aware of the order of operations.** The refund share is taken first and the cap
    is checked against the result, because the cap limits what is *paid*. Goods worth more
    than $100 therefore need not breach it — $179.97 of whey refunds $107.98 at 60% and
    is capped, while the same goods at 40% refund $71.99 and are not capped at all.
    Checking the cap against the price instead would trim figures that were never over
    the limit.
  - **Be aware:** whether the cap means per product or per claim is REQUIREMENTS open
    question 2, so which applies is a setting. This is the single place a product's
    outcome depends on what else was claimed beside it, which is why it sits apart from
    everything FR-1b.4 guarantees.

- [x] FR-1.21 — The agent says *what* was damaged; code works out *how much*.
  - **Conclusion:** structural three times over. No form the model fills in has anywhere
    to put an amount; the tool that computes one tells the model only *whether* a figure
    could be worked out, never the figure; and the email carries `{{amount}}` for code to
    substitute. The real product costs $52.00 and nothing money-shaped reaches the model.
  - **Be aware:** a validator refuses any other money-shaped text the model writes, and a
    refused email escalates the product. It deliberately allows quantities, dates, order
    numbers and SKUs — both directions are tested, and where the line was drawn is in
    DESIGN.md.

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
    fifth "submit" tool, deliberately: FR-1.2 enumerates exactly four tools, and a separate
    call is what guarantees the answer conforms.
  - **Be aware:** a malformed answer is not re-asked. The identical question asked the
    identical way is the least likely thing to come back differently, so the product goes
    to a person instead. A single reshaped retry would recover some of those — see DESIGN.md.

- [ ] NFR-3 — Partly. Every conclusion traces to the observation that produced it inside a
  single reply: each finding names the attachment it came from, each judgement carries its
  reasoning, and the amount carries its full working. What is missing is that none of it is
  kept — close the connection and the record is gone, so "why this amount?" can be answered
  now and not tomorrow. Waits on somewhere to store a report.

- [x] NFR-4 — Every failure ends with a person, and none ends in a payment or a dropped case.
  - **Conclusion:** proven for an exhausted budget, a model that cannot be reached, a reply
    that will not fit its form, a plain timeout, an image that cannot be fetched, a tool
    that breaks, a shipment ShipBob will not price, and an email the model wrote money into.
    Each returns a result a rep can act on rather than raising.
  - **Be aware:** the honest distinction throughout is between what the merchant can fix and
    what only we can. An image we failed to download never produces a request to the
    merchant — the pre-flight screen has one label that makes exactly that mistake, and
    DESIGN.md records it as a fault rather than a pattern to copy.

- [ ] NFR-5 — Not built. Each run keeps an ordered record of what it did and saw, and it
  travels in the reply, but nothing stores it and nothing fills in the times. There is no
  per-case history, so the requirement is met inside one request and not at all across two.

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
