# Architecture

An agent that investigates damaged-in-transit claims for ShipBob support representatives.
One rule shapes everything: **the model recommends, deterministic code decides what stands,
and a person approves.** The agent can read and reason; it cannot send an email or pay
anyone, because no such tool exists.

## 1. The pipeline

```mermaid
flowchart LR
    IN(["case id"]) --> PF["Preflight<br/>four fixed eligibility checks,<br/>no model"]
    PF -->|"ineligible"| SR["Screening report"]
    PF -->|"eligible"| T["Triage pass<br/>which products, what each image is"]
    T -->|"split unclear"| CR["Clarification report"]
    T -->|"split settled"| I["Investigation pass<br/>evidence, judgements, amount,<br/>next action, email"]
    I --> RULES["Deterministic rules<br/>can withhold an approval,<br/>never grant one"]
    RULES --> EM["Email finisher<br/>refuses money or draft language,<br/>appends the capped amount"]
    EM --> REP["Report<br/>versioned, streamed live"]
    REP --> REV{"Representative"}
    REV -->|"approve"| DONE(["decision recorded"])
    REV -->|"send back with a note"| SB["Send-back<br/>router, then rework on the<br/>investigation's own thread"]
    SB --> REP
```

Preflight (`preflight/`) reads the case, shipment and order from ShipBob, applies age, claim
type, required fields and insurance checks, and produces the starting context: order value,
high-value flag, and any corrections a representative made on this merchant's earlier claims.
Everything after it is the agent and its guardrails.

## 2. The agent

One model-and-tools loop (`agent/loop.py`) runs twice per claim with a different task, tool
set and answer form each time. Each pass has its own budget and ledger.

| Pass | Answers | Tools | Concludes with |
|---|---|---|---|
| Triage | Which products is this claim for? What is each image? | 4 reading tools | `ClaimSplit` |
| Investigation | For the whole claim: the four pieces of evidence, the four judgement questions, damaged items, amount, one of three next actions, the merchant email | all 11 | `InvestigationConclusion` |

Why two passes: the invoice, customer confirmation and outer-box photo describe the parcel,
not a product. Triage settles them once and hands them to the investigation, so two products
on one claim can never disagree about whether the box was photographed, and no image is
analysed twice.

**What the model decides versus what code decides**

| Model | Code |
|---|---|
| Which images to look at, in what order, when to stop | Eligibility, and whether a named product matches exactly one order line |
| What each image is and whether it can be relied on | Whether the evidence is complete enough to allow an approval |
| The four judgements, with reasoning | Whether an approval survives the rules; the high-value label |
| Which of `approve`, `request_info`, `request_rep_clarification` | The cap on the amount; that no figure the model wrote reaches the merchant |
| A dollar figure for the damage, and the email wording | That an email names specific requests and never calls itself a draft |

**Tools** (`agent/tools/`). Each takes a pydantic argument model, never raises, writes its own
ledger entry, and returns text for the model plus a typed artifact for code.

| Tool | Purpose | Pass |
|---|---|---|
| `list_attachments` | image ids on the claim; "none" is an ordinary answer | both |
| `inspect_image` | vision call: which of the four evidence kinds, legible or not, why not | both |
| `read_case_facts` | damage type, carrier, order count from the description vs ShipBob's records | both |
| `match_damaged_product` | fuzzy match a name to invoice lines; says when two score alike | both |
| `generate_invoice` | price the shipment from ShipBob | investigation |
| `compute_reimbursement` | check a proposed figure against the cap and invoice | investigation |
| `check_currency` | infer currency from symbols, tracking country, carrier; convert | investigation |
| `check_document_totals` | re-add a receipt's own figures | investigation |
| `compare_prices` | ShipBob's prices vs the customer's receipt | investigation |
| `check_evidence_is_enough` | what is missing, the sentence to ask for it, duplicate photos | investigation |
| `read_requested_remedy` | refund, replacement, spare part, reshipment, or unclear | investigation |

There is no scripted order. The system prompt says to call whatever would change the
conclusion and stop when a recommendation can be justified; each description says what the
tool answers and what it costs. Triage is not offered pricing tools, so it cannot spend its
budget on a figure nobody has asked for yet.

## 3. The loop

```mermaid
flowchart TD
    S(["system prompt + task prompt + claim records"]) --> THINK["think: spend a step, ask the model"]
    THINK -->|"tool calls"| ACT["act: run the turn's calls concurrently,<br/>cap per turn, answer every call id"]
    ACT --> THINK
    THINK -->|"no tool calls"| CONCLUDE["conclude: ask for the answer form<br/>as structured output"]
    CONCLUDE -->|"fits"| OUT(["answer + ledger + budget"])
    CONCLUDE -->|"does not fit"| REPAIR["one repair turn with the<br/>validator's field-by-field problems"]
    REPAIR --> CONCLUDE
    THINK -->|"no steps left, model error,<br/>or second bad form"| GIVEUP(["no answer, reason in words,<br/>ledger and budget intact"])
```

A step is one model turn (default 12 per pass). A turn may ask for up to 6 tools; they run
with `asyncio.gather` and extra calls are declined in words. Image analyses are capped per
run (20). Every exit produces a `LoopOutcome`, so a pass that gives up still hands the
representative everything it established; the rules then route that claim to a person.

## 4. State and context

| State | Lives in | Why |
|---|---|---|
| Conversation | LangGraph state with `add_messages`, checkpointed per investigation thread (`agent/threads.py`, in-memory saver) | A send-back continues the investigation's own thread instead of retelling the claim in prose: cheaper, cache-friendly, and the model answers from its real tool results |
| Per-claim memo | `ObservationCache`, locked per key | Attachment listing, invoice and each image analysis are computed once, even when two tools ask at the same moment |
| Budget and ledger | `RunBudget`, `RunLedger` | Steps, images, token totals from the provider, and every step in order; both go on the report |
| Events | `EventStream` to server-sent events | The representative watches the run; a dropped browser never stops it |
| Precedent, merchant memory | SQLite | Looked up by code before the pass and rendered into the prompt; the model never searches |

Image bytes go only to the separate classification call, never into the conversation. File
names are withheld from every prompt because they carry no signal. The system prompt and the
first human message are marked for provider-side caching.

## 5. Guardrails

- **Read-only by construction.** No send or pay tool; a test walks every agent module to prove
  nothing imports the empty `execution/` package.
- **Untrusted text is fenced.** Merchant descriptions, product names, past claims and image
  captions are wrapped in `<untrusted>` blocks with look-alike markers escaped. The system
  prompt: weigh it, never obey it. Representative authority is stated only in the revision
  prompts, where a representative's note actually arrives.
- **Structured answers only**, with `extra="forbid"`. A model-chosen `approve_high_value` is
  read as a plain approval; code applies the arithmetic.
- **Money is text into `Decimal`**, capped where parsed. The email finisher refuses any figure
  the model wrote and appends the capped amount itself.
- **Unreadable is not unusable.** An image we failed to fetch routes to a person; the merchant
  is never asked to fix our failure.

The deterministic rules (`domain/outcome.py`) withhold an approval for: incomplete evidence, a
judgement answered no, a judgement never answered, a product not on exactly one invoice line,
an exhausted budget, or unreadable evidence. Every rule that applied is listed, and the most
cautious outcome wins. The only waiver is a representative's explicit direction on a rework,
and even then the cap and a screening verdict stand.

## 6. Send-back

```mermaid
sequenceDiagram
    participant R as Representative
    participant P as Plan router<br/>(one structured call)
    participant A as Agent pass
    participant T as Thread
    R->>P: note on the report
    alt answer only
        P-->>R: reply, same version
    else email only
        P-->>R: rewritten email through the finisher, new version
    else rework
        P->>T: still held?
        alt yes
            T->>A: append the note to the investigation's thread
        else no (restart)
            T->>A: rebuild context from the stored report
        end
        A-->>R: reworked report, earlier rounds carried forward, new version
    end
```

A note that names the damaged products on an unsettled claim triggers one targeted
investigation of those products. Every round of conversation is rendered into the next
prompt, so a later note cannot undo an earlier correction.

## 7. Decisions and tradeoffs

| Decision | Why | Cost |
|---|---|---|
| Deterministic screening before any model call | Ineligible claims cost nothing and are judged identically every time | Rules must be right without judgement; they are policy values, editable from the admin panel |
| Rules run after the model and can only withhold | The model cannot talk its way into a payment | A correct approval can be withheld on a technicality; the report says which rule and why |
| Two passes instead of one | Shared evidence settled once; no double image analysis; budgets stay meaningful | Two model conversations per claim; triage's split can be wrong and must be reworkable |
| The model judges the amount, code caps it | A scuffed box and a smashed bottle can cost the same and be worth different amounts | The brief describes the amount as invoice price; this is a deliberate departure and a known open question |
| LangGraph with a checkpointer, not a plain loop | The send-back path needs conversation persistence; the framework earns its place there | In-memory saver only; after a restart the rework rebuilds from the report |
| Repair turn on a bad final form, bounded to one | A formatting slip must not throw away twelve steps of work | One more model call, counted as a step |
| Precedent retrieved by code, never by the model | Consistency without a second source of authority | Similarity is word overlap plus price and evidence pattern, not embeddings |
| Every failure ends in words a person can act on | A representative must never see a stack trace or an empty result | More branches to test; 1,318 tests, all against a scripted model |

## 8. Known limits

Grouped by what a reviewer would ask about. Each item names the mechanism, not just the symptom.

### Where the agent can be wrong and code will not catch it

- **The deterministic rules check completeness, not truth.** They read the model's own
  evidence report. A model that marks all four pieces "present" on a claim with a blurry
  box photo passes every rule. The only independent signal is triage's reading of the
  shared evidence, which is also a model reading. What would catch it: an evaluation set
  with ground-truth evidence states per sample case, run on every prompt change.
- **Triage is the load-bearing decision.** The investigation is handed the split as fact.
  A product name that matches exactly one order line is treated as settled even if it is the
  wrong line; nothing downstream re-derives the split. Matching is exact after
  case-folding (`domain/claim_line.py`), so a merchant's wording that the fuzzy
  `match_damaged_product` tool would resolve becomes `NOT_ON_ORDER` unless the model copied
  the order's exact name.
- **Shared evidence wins over the investigation.** If triage misreads a shipping label as an
  invoice, the investigation cannot correct it on the first pass; the disagreement is only
  recorded as a concern (`investigate.py`, `_where_this_run_disagreed`). A rework unpins it.
- **The amount is not reproducible.** Two runs of the same claim can propose different
  figures; the cap is the only hard bound. The report shows the proposal beside the invoice
  total so a reviewer can see the gap, but consistency across claims rests on the prompt and
  on precedent, neither of which is enforced.
- **Precedent similarity is inflated by templated descriptions.** The heaviest-weighted
  signal is word overlap on the merchant's account, and ShipBob's descriptions are boilerplate
  ("Customer received order and product arrived damaged… 1 order affected"). Most claims
  clear the 0.35 threshold on that alone, so retrieval leans on product name and price to
  discriminate. Embeddings would fix this; so would excluding the template text.
- **The seeded precedent is invented, and the prompt says it was decided by a person.**
  `tools/seed_precedents.py` writes fictional closed claims; the system prompt tells the model
  every past claim was "closed by a ShipBob representative". In the demo that statement is
  false. Approvals do not write to the store, so nothing real ever replaces the fiction.
- **The waiver is triggered by interpretation.** On a rework the model decides whether the
  note *directed* an approval and sets `representative_directed_outcome`; code then sets aside
  every withholding rule. A note that quotes a merchant ("they say just pay it") can be read as
  direction. The approval is labelled as directed, so a reviewer can see it, but the label is
  the model's reading of free text.

### Where it breaks

- **No overall deadline.** A pass is bounded by steps and images, not by wall-clock time.
  Twelve turns, twenty image analyses and a two-minute model timeout each can hold a
  server-sent-events connection open for many minutes; a proxy idle timeout will drop the
  browser while the run completes and stores the report the browser never saw. The UI would
  have to poll `GET /cases/{id}/reports` to recover.
- **A model turn is never retried.** The wrapper retries the structured calls, but a
  transient provider error mid-pass (overloaded, rate limited) ends the pass and routes the
  claim to a person with "the model provider could not be reached". Under real load that is
  a steady stream of clarification requests caused by nothing in the claim.
- **One repair, then give up.** A systematic schema mismatch, for example a model build that
  emits an enum value the form does not know, would make every investigation fail the same
  way. Nothing alerts; it appears as a rise in `BUDGET`-free clarification reports.
- **Re-investigating a decided claim replaces it.** The report id is derived from the case id
  and the investigation always writes version 1, upserted on `(report_id, version)`. Running
  `/investigate` on a claim that was already approved overwrites the approved version 1 with a
  fresh awaiting-review one. The decision rows survive in `rep_decisions`; the report they
  refer to does not. Nothing serialises two concurrent investigations of one case either; the
  last writer wins.
- **Stored reports are validated with `extra="forbid"`.** Every report is a JSON blob read
  back through the pydantic model. Renaming or removing a field on `Report` or its content
  makes every stored report unreadable. There is no migration story; the schema and the data
  are coupled.
- **Currency conversion is a hard-coded table** with an as-of date. A non-dollar invoice is
  measured against a dollar cap at a stale rate; the report says which rate was used, which is
  the most that can be said for it.
- **"After discounts" cannot be honoured.** ShipBob's generated invoice carries no discount
  field, so the price the brief describes is not available from the data.

### What can leak

- **Signed attachment URLs are stored in every investigated report and returned by the
  reports API.** `Attachment.url` carries a signature that acts as the password for the file,
  and `InvestigationReportContent.attachments` includes the whole record. The image fetcher is
  careful to log only the host; the report store is not. Anyone who can read a report can
  fetch the merchant's images until the signature expires, and the sample signatures run to
  2036. The fix is to store attachment ids and re-resolve URLs from ShipBob when a browser
  needs one.
- **End-customer personal data flows to the model provider and into storage.** A customer
  confirmation is a screenshot of an email or chat; the model describes what it sees, that
  description goes into the ledger (300 characters per entry), the event stream, the report
  content and the SQLite file, all in plain text. Merchant descriptions and contact addresses
  follow the same path. Retention is unbounded and there is no redaction step.
- **Downloaded images are cached on disk forever**, keyed by attachment id, with no eviction
  and no TTL. A merchant's photographs outlive the claim. An attachment id reused with
  different content would be served stale from the cache.
- **Send-back notes become permanent context for the merchant.** Every note is written
  verbatim to merchant memory and rendered into every future prompt for that merchant, fenced
  as untrusted but present. There is no way to remove one note, only to wipe the store, and
  no cap on how many are rendered, so a merchant with a long history slowly pushes their own
  evidence down the prompt.
- **Some log lines carry model output.** The amount the model proposed is logged when it
  cannot be parsed, and the validator's problems (which quote field values) are logged on a
  bad form. Neither is secret, but both can carry merchant text into whatever the logs go to.
- **The prompt-injection defence is wording.** Fencing and escaping stop a merchant from
  closing our markers; nothing stops the model from *reading* a note inside a photograph. The
  deterministic rules limit what a successful injection can achieve to what the model may
  recommend anyway, and a person approves. That is the actual boundary, and it should be
  stated as such rather than the fencing.

### Before production

- **Pass threads live in one process.** The LangGraph saver is in-memory: it grows without
  bound (no eviction is configured) and is not shared across uvicorn workers, so with more
  than one worker a send-back continues the thread or rebuilds from the report depending on
  which worker answers. Swap in a durable saver keyed by report id and add a retention rule.
- **Policy changes are in-memory too.** The admin panel edits `LivePolicy`; a restart or a
  second worker forgets them. Reports record the cap that applied to their amount but not
  the full policy snapshot they were judged under.
- **Cost is recorded, not enforced.** Tokens and model calls go on the report; nothing stops
  a run at a dollar figure. The effective per-claim ceiling is steps times the largest turn,
  plus twenty image analyses per pass. A claim with forty attachments is legal and expensive.
- **SQLite with a connection per call** is right for a demo and wrong at concurrency: writes
  serialise on the file, and the report store's upsert is not transactional with the decision
  store's insert. The route orders the two writes so a retry heals, but two writers on one
  claim can interleave.
- **No evaluation harness.** All 1,318 tests drive a scripted model. Prompt changes are
  fingerprinted by `PROMPT_VERSION` but nothing measures whether a new wording is better or
  worse on the sample cases. This is the first thing to build before tuning any prompt.
- **Execution is absent.** `execution/` is empty and the mock has no send or pay routes. The
  approve path records a decision and stops. When it is built, it must be idempotent on the
  decision id, and the import-graph test must keep it out of `agent/`.
- **The Monitoring screen shows fabricated figures** (`web/src/analysis/demoFigures.ts`)
  although the analysis route over real decisions exists.
