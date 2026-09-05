# Damaged-in-Transit Claims Agent — Backend Requirements

## Background

ShipBob is a third-party logistics company. Merchants send their inventory to ShipBob's
warehouses; ShipBob picks, packs, and ships orders to those merchants' end customers.

Sometimes a package arrives crushed, a product arrives broken, or contents are missing.
When that happens the merchant opens a support case with ShipBob, and a ShipBob support
representative decides whether to reimburse the merchant for the damaged goods. This is
called a **damaged-in-transit claim**.

Today a rep does all of it by hand: opens the case, reads the merchant's description,
looks at the photos the merchant attached, checks whether the claim qualifies, works out
how much to pay, writes an email, and sends it. It is slow, it does not scale, and — the
part that matters most — it is **inconsistent**. The same situation can get two different
answers from two different reps, or from the same rep on two different days.

This system automates that work. It investigates a claim, establishes the facts, and hands
the rep a finished report and a drafted merchant email.

**The system does not decide claims. The rep does.** The agent's job is to do the
gathering, reading, checking and drafting — the slow, repetitive part — and to present
what it found so that a decision takes seconds instead of many minutes. The judgement of
whether to pay, refuse, or ask for more remains a person's, and nothing reaches the
merchant until that person says so.

This split is what delivers both goals at once. **Consistency** comes from the agent
performing the same investigation the same way on every claim, so two identical claims
arrive at the rep looking identical. **Ease** comes from the rep receiving a complete,
legible report rather than a case to work from scratch.

**Scope of this document:** the backend only — the deterministic checks, the AI agent, its
tools, the report it produces, and what happens after approval. The reviewer-facing UI is
specified separately.

---

## Key terms

| Term | Meaning |
|---|---|
| **Case** | A merchant's claim, already created in ShipBob's system. This system reads cases; it does not create them. |
| **Merchant** | ShipBob's customer — the brand whose goods were damaged. The only party the system communicates with. |
| **End customer** | The person who received the package. ShipBob never contacts them directly. |
| **Rep** | The ShipBob support representative who reviews and approves the system's work. The only human user. |
| **Attachment** | An image the merchant uploaded to the case — photos, screenshots of emails, pictures of invoices. |
| **Agent** | The AI component that investigates a case by choosing and calling tools. |
| **Claim line** | One claimed product within a case. A claim for two damaged items is two claim lines. The unit of investigation, reporting, approval, and payment. |
| **Report** | The structured output the agent produces for the rep to act on — one per claim line. |
| **Precedent** | A record of a claim line this system investigated before, kept so a later claim like it can be handled the same way. |
| **Precedent store** | Where those records are kept and searched. The system writes it itself; no ShipBob endpoint supplies it. |
| **Merchant memory** | What a rep has already corrected on a merchant's earlier claims, found by that merchant's id. The system keeps this itself too. |
| **Decision record** | What a rep did with a report — approved it, edited it, sent it back, overrode it. The system's own record of the moment a recommendation became a decision. |

## Available data

The system reads from a mock ShipBob API offering: a list of cases, case details, case
attachments, shipment details, order details, and invoice generation. It can also send an
email on a case and submit a reimbursement.

There is **no endpoint for merchant history**, **no endpoint for reading merchant replies**,
and **no way to ask how comparable past claims were handled**. Anything the system needs to
remember, it stores itself — including its own record of every claim line it has investigated
(FR-S.1).

The full endpoint surface, with example payloads, is in `shipbob-mock-api.md`. Summarised:

| Endpoint | Purpose |
|---|---|
| `GET /cases` | List all cases (id, number, status, subject, created date) |
| `GET /cases/:case_id` | Full case record |
| `GET /cases/:case_id/attachments` | The merchant's uploaded images |
| `GET /shipments/:shipment_id` | Carrier, tracking, delivery date, insurance flag |
| `GET /orders/:order_id` | Order line items with prices |
| `POST /invoices/generate` | Priced invoice for a shipment |
| `POST /reimbursements` | Submit a payout — one product per call |
| `POST /cases/:case_id/email` | Send an email on the case |

Five test cases exist: `CASE-1001` through `CASE-1005`. Each represents a different
scenario, and they are referenced throughout this document as concrete examples.

---

## The four layers

```
Layer 0   Pre-flight       deterministic  →  screens out claims that cannot be processed
Layer 1a  Triage           AI agent       →  identifies which products are being claimed for
   └── precedent retrieval  →  the most similar past claim lines, fetched per line
Layer 1b  Investigation    AI agent       →  one run per claimed product
Layer 2   Report           structured     →  one report per product; the rep decides each
   ├── rep gives feedback →  Layer R  same agent, re-run  →  revised report, back to Layer 2
   └── rep approves       →  Layer 3
Layer 3   Execution        deterministic  →  one email and one reimbursement per product
   └── what the rep decided   →  merchant memory + the precedent store  →  the next claim
```

A claim can cover more than one damaged product. Everything from Layer 1b onward operates
on a **claim line** — one claimed product — not on the claim as a whole.

Layer 2 is a loop, not a step. The rep reviews, and either sends the report back with
feedback — which a second agent acts on, producing a revised report for another review —
or approves it, which is the only way out of the loop and into execution.

The principle behind the split: **rules where there is a right answer, the agent where
there is ambiguity, the human where there is a decision to make.**

Precedent is not a fifth layer. It is a store the system keeps for itself: every claim line
Layer 1b investigates is written into it, and every later line that resembles one is given it to
read. It exists because the layers above make each claim *internally* consistent and cannot make
two separate claims agree with each other. See **Claim precedent** below.

Both stores are read on the way in and written on the way out, and the write is triggered by a
rep deciding a claim line rather than by any layer finishing. That step is specified in
**Carry-forward** below, after the precedent section it depends on.

Note the distinction between a proposed next action and a decision. The agent returns its
confidence and a claim report that proposes one of three next actions. When that action is
merchant-facing, it also returns a separate email draft. The proposal is not an act: nothing
takes effect until a rep approves it.

---

# Layer 0 — Deterministic pre-flight

Runs before the agent. Uses no AI. Its job is to answer one question cheaply: *can this
claim be processed at all?*

Some claims are dead on arrival regardless of how good the evidence is. Checking those
first means an unprocessable case costs a few API reads instead of a full AI
investigation.

**FR-0.1 — Gather the case record.**
Retrieve the case, its shipment, its order, and any stored history for that merchant.
These are inexpensive data reads. Do not download or analyse attachments at this stage.

> **Reference — `GET /cases/CASE-1001`**
> ```json
> {
>   "case_id": "CASE-1001",
>   "status": "New",
>   "sub_category": "Claim | Damaged in Transit",
>   "description": "Shipment ID: 342578703. Customer received order and product arrived damaged. Both product and shipping box damaged. Damage due to poor/bad packaging. 1 order affected.",
>   "order_id": "334291211",
>   "user_id": "334430",
>   "shipment_id": "342578703",
>   "delivered_date": "2026-02-11T11:36:14.000+0000",
>   "contact_email": "sakukreja@shipbob.com",
>   "account_name": "Best Paw Nutrition",
>   "created_date": "2026-02-19T14:20:16.000+0000"
> }
> ```
> The case gives the ids needed for every subsequent read. `description` is free text and
> is the merchant's own account of what happened.

**FR-0.2 — Check the claim is eligible.**
Four conditions, all of which must hold:

1. **The shipment is not too old.** ShipBob cannot reimburse past a certain age.
2. **The claim is the right type.** Only damaged-in-transit claims are handled here.
3. **Key information is present.** Missing the shipment, the order, or a description means
   there is nothing to investigate.
4. **The shipment is not insured.** Insured shipments follow a completely different
   process and must be routed out, never processed here.

> **Reference — where each gate reads from**
>
> | Gate | Field | Source |
> |---|---|---|
> | Age | `delivered_date` vs `created_date` | case, or `GET /shipments/:id` |
> | Claim type | `sub_category` | case |
> | Key info | `shipment_id`, `order_id`, `description` | case |
> | Insurance | `is_insured` | `GET /shipments/:id` |
>
> **`GET /shipments/342578703`**
> ```json
> {
>   "shipment_id": "342578703",
>   "order_id": "334291211",
>   "carrier": "Royal Mail Tracked 48",
>   "tracking_number": "XQ607930599GB",
>   "status": "Delivered",
>   "delivered_date": "2026-02-11T11:36:14.000+0000",
>   "is_insured": false
> }
> ```
> All five test shipments are `is_insured: false`, so the insurance gate cannot be
> demonstrated on real data — a constructed case is needed to show it firing.
>
> Every test case has `sub_category: "Claim | Damaged in Transit"`, so the claim-type
> gate likewise never fires on the sample set.

**FR-0.3 — Emit a verdict.**
Either `PROCEED`, meaning the agent runs, or `TERMINAL` with a reason, meaning it does not.

**FR-0.4 — A terminal case still produces a report.**
An ineligible claim gets closed *with an explanation to the merchant*. That explanation is
an email, and every email needs rep approval. So a terminal case skips the agent but still
produces a report (Layer 2) containing the reason and a drafted merchant email.

> **Reference — `CASE-1004`, the age-gate example**
> ```json
> {
>   "case_id": "CASE-1004",
>   "status": "Closed",
>   "account_name": "Catalyze-X",
>   "delivered_date": "2025-12-26T12:13:36.000+0000",
>   "created_date": "2026-03-09T18:51:42.000+0000"
> }
> ```
> Delivered 26 Dec, filed 9 Mar — **73 days**. Every other test case was filed within 8
> days of delivery. This case has four attachments, and the correct behaviour is to never
> look at any of them.

**FR-0.5 — Compute the facts the agent should not have to work out.**
Order value, whether this counts as a high-value shipment, days elapsed since delivery, and
any corrections the rep has previously made on this merchant's claims. Pass these to the
agent as starting context so it does not spend reasoning steps rediscovering them.

> **Reference — `GET /orders/334291211`**
> ```json
> {
>   "order_id": "334291211",
>   "user_id": "334430",
>   "line_items": [
>     { "product_id": "1374243085", "name": "Additional Collagen Ampoule Duo", "sku": "AMP1", "quantity": 1, "unit_price": 38.00 },
>     { "product_id": "1309112104", "name": "Liposomal Tripeptide Collagen", "sku": "COLLAGEN1", "quantity": 1, "unit_price": 52.00 }
>   ],
>   "created_date": "2026-02-07T07:42:48.000+0000"
> }
> ```
> Order value is derived from `unit_price × quantity` across line items. There is no
> subtotal, tax, shipping, or discount field anywhere in the schema.

**FR-0.6 — Be fully deterministic.**
The same case must always produce the same verdict. No AI is involved in this layer. These
are rules with correct answers; a model can only introduce variance.

**FR-0.7 — Keep policy values in one named place.**
The age limit, the high-value threshold, the reimbursement cap, and confidence thresholds
belong in a single readable configuration, not scattered through the code. Several of these
values are not specified by ShipBob and represent judgement calls, so they must be visible
and changeable rather than buried.

---

# Layer 1a — Triage: splitting the claim into lines

A merchant opens **one case** for a shipment, but that case may cover several damaged
products. The reimbursement API accepts one product per call, and a rep may well want to
pay for one item while asking for more evidence on another. So the claim is split before it
is investigated.

The split cannot be made deterministically. The case description does not name products —
it says things like "1 order affected" or "Number of affected orders: 2" — so working out
which products are being claimed for requires reading the description and looking at the
photos. This is a single agent pass over the whole claim.

**FR-1a.1 — Identify the claimed products.**
From the case description, the attachments, and the order's line items, determine which
products the merchant is claiming for. The output is a set of claim lines, each naming one
product from the order.

**FR-1a.2 — Match each claim line to an order line item.**
A claim line must correspond to a real product on the order, carrying its name, SKU, and
unit price. A claimed product that does not appear on the order cannot be reimbursed, and
that is itself a finding.

**FR-1a.3 — Classify the shared evidence once.**
The invoice, the outer packaging photo, and the customer confirmation apply to the whole
shipment, not to any one product. Classify them once at this stage and make the result
available to every claim line. Only the damaged-product photos are product-specific.

This is both a cost control — the invoice is not re-read once per line — and a consistency
guarantee: every line in a claim sees the same verdict on the shared evidence.

**FR-1a.4 — Ask the representative when the split is ambiguous.**
If it cannot be established which products are being claimed for, no meaningful per-product
investigation is possible. Return a claim-level report with
`request_rep_clarification`, state what is ambiguous, include the confidence, and do not
generate a merchant email or guess a split. A rep who is told "the photos show a damaged 24oz
bottle, but the order contains two different 24oz bottles at different prices" can resolve
it in seconds; a wrong split is silent and expensive.

**FR-1a.5 — Treat a single-product claim as one claim line.**
There is no special case for single-product claims. One damaged product is one claim line
and goes through exactly the same machinery.

---

# Layer 1b — Investigation, per claim line

One agent run per claim line. Each run receives the context from FR-0.5, the shared
evidence findings from FR-1a.3, and the claim line it is responsible for. It investigates
that one product and produces a recommendation for the rep.

The agent's authority ends at recommending. It establishes what the evidence shows, what
the policy implies, and what it would suggest — and stops there.

**FR-1b.1 — Investigate one product per run.**
Each run assesses, recommends, and drafts for its own claim line only. It does not decide
anything about the other lines.

**FR-1b.2 — See the whole claim regardless.**
The run receives the full case: the merchant's complete description, every attachment, all
order line items, and the other claim lines in the claim. It needs this context to read the
evidence correctly — a photo showing two damaged items is relevant to both lines, and a
description covering the whole shipment is the only account of what happened.

The distinction is scope of responsibility, not scope of knowledge. The agent knows about
the whole claim and answers for one line of it.

**FR-1b.3 — Reach outcomes independently.**
One line may be recommended for approval while another is recommended for a request for
information. A weak line must not drag down a well-evidenced one, and a strong line must
not carry a poorly evidenced one.

**FR-1b.4 — Produce the same result for a line regardless of its siblings.**
A product with a given set of evidence must reach the same recommendation whether it was
claimed alone or alongside five others. This is what per-line isolation buys, and it is a
direct contribution to NFR-1.

---

# Layer 1 — Shared agent requirements

These apply to both the triage pass and every per-line run.

## How it operates

**FR-1.1 — Work as a tool-use loop, not a fixed sequence.**
The agent chooses what to look at next based on what it has found so far, and stops when it
can justify a recommendation. A case with no attachments should not require the same steps
as a case with six. This autonomy is over *how it investigates*, not over what happens to
the claim.

**FR-1.2 — Operate with read and reasoning tools only.**
The agent's available tools are: list a case's attachments, inspect an image and answer a
question about it, generate an invoice for a shipment, and compute a reimbursement amount.

**The agent has no ability to send email or submit a reimbursement.** Those tools are not
in its surface at all. This is a structural guarantee rather than an instruction the model
is asked to follow — the agent cannot take an irreversible action because no such action is
available to it.

> **Reference — endpoint access by layer**
>
> | Endpoint | Layer 0 | Agent | Layer 3 |
> |---|:---:|:---:|:---:|
> | `GET /cases/:id` | ✅ | | |
> | `GET /shipments/:id` | ✅ | | |
> | `GET /orders/:id` | ✅ | | |
> | `GET /cases/:id/attachments` | | ✅ | |
> | `POST /invoices/generate` | | ✅ | |
> | `POST /cases/:id/email` | | ❌ | ✅ |
> | `POST /reimbursements` | | ❌ | ✅ |

**FR-1.3 — Guarantee termination.**
The agent runs within a bounded number of steps with bounded retries. It always terminates.
Budgets apply per run, so a claim with four lines has four budgets rather than one shared
between them.

## Evidence gathering

Before any reimbursement decision, four pieces of evidence must be present:

1. **Proof of what was ordered and at what price** — an invoice
2. **Confirmation from the end customer that the damage happened** — supplied by the
   merchant, since ShipBob does not contact end customers
3. **Photos of the damaged product** — specific to a claim line
4. **Photos of the outer packaging the order arrived in**

Items 1, 2 and 4 describe the shipment and are assessed once for the whole claim
(FR-1a.3). Item 3 is assessed per claim line: a claim covering two products needs photos
showing damage to each of them.

**FR-1.4 — Identify what each attachment actually is.**
Attachments arrive as images with unhelpful names. An invoice may be a photograph of a
paper invoice or a screenshot of a billing page; customer confirmation is typically a
screenshot of an email. The system must determine each attachment's content by looking at
it. Filenames and file types are not reliable indicators.

> **Reference — `GET /cases/CASE-1003/attachments`**
> ```json
> {
>   "attachments": [
>     { "attachment_id": "ATT-CASE-1003-01", "file_name": "Inv.png", "content_type": "image/png", "url": "https://...blob.core.windows.net/shipbob-fde-mock/case-1003/01_Inv.png?se=2036-07-26T20:59:50Z&..." },
>     { "attachment_id": "ATT-CASE-1003-02", "file_name": "Screenshot_at_Feb_26_20-45-24.png", "content_type": "image/png", "url": "https://..." },
>     { "attachment_id": "ATT-CASE-1003-03", "file_name": "Screenshot_at_Feb_26_20-45-11.png", "content_type": "image/png", "url": "https://..." }
>   ]
> }
> ```
> Every attachment in every test case is an image. `content_type` is always `image/png` or
> `image/jpeg` and therefore carries no signal about content. Two files here share a
> near-identical name but are different kinds of evidence. Names across the set include
> `kgray1.png`, `IMG_9726.jpeg`, and `329233.png` — none of which indicate content.
>
> Attachment URLs are Azure blob links with signatures valid until 2036, so they can be
> cached locally for offline development.

**FR-1.5 — Treat unusable evidence as missing.**
An attachment that is present but too blurry, too dark, or too cropped to support a
conclusion does not satisfy its requirement. Record *why* it was unusable, so the merchant
can be asked for something specific.

**FR-1.6 — Never guess at missing evidence.**
If any of the four items is absent or unusable, the outcome is a request for information.
The system does not infer, assume, or approve partially. It asks and waits.

> **Reference — `GET /cases/CASE-1005/attachments`**
> ```json
> { "attachments": [] }
> ```
> `CASE-1005` has no attachments at all, and its case status is already
> `"Waiting on Client"`. All four evidence items are missing; the only valid outcome is a
> request for information. An empty attachment list must not cause an error.

**FR-1.7 — Ask for exactly what is missing.**
A request must name the specific gaps — "a photo of the outer shipping box" rather than
"more information." A merchant who receives a vague request sends the wrong thing, and the
claim takes another round trip.

## Judgment

Once all four evidence items are present and usable, four questions must be answered. These
are assessments the agent reports, each with its reasoning, not verdicts that settle the
claim:

**FR-1.8 — Is the damage actually visible in the photos?**

**FR-1.9 — Can the damaged product be identified?**

**FR-1.10 — Does that product appear on the invoice?**
A claim for something that was not in the order cannot be reimbursed.

**FR-1.11 — Is the outer packaging documented?**
It needs to be *photographed*, not damaged. Intact packaging with a damaged product inside
is a legitimate claim.

**FR-1.12 — A failed assessment requests representative clarification.**
It means something appears wrong or conflicts with the claim, rather than that a specific
merchant-supplied detail is absent. The report names the failed assessment and no email is made.

**FR-1.13 — Ask rather than pick when the damaged item is ambiguous.**
Orders can contain several similar products at different prices. If photos do not
distinguish which one was damaged, the amount cannot be determined, and the system must
ask instead of choosing the most likely candidate. If the merchant can supply a specific
missing detail, use `request_info` and name that detail in the email. If records conflict or
something appears incorrect, use `request_rep_clarification` and generate no email.

> **Reference — `GET /orders/336431771` (CASE-1002, CleanBoss)**
> ```json
> {
>   "line_items": [
>     { "name": "CleanBoss Botanical Disinfectant & Cleaner 24oz 2 Pack", "sku": "A00360", "quantity": 1, "unit_price": 24.99 },
>     { "name": "CleanBoss Multi Surface Cleaner 24oz", "sku": "A00300", "quantity": 2, "unit_price": 12.99 },
>     { "name": "CleanBoss Foaming Cleaning Wipes 70 pack", "sku": "A00299", "quantity": 1, "unit_price": 14.99 }
>   ]
> }
> ```
> Three similarly branded cleaning products at three different prices, two of them 24oz
> bottles. A photo of a damaged bottle does not by itself determine whether the payout is
> $24.99 or $12.99. The case description says "1 order affected" without naming the item.

## Recommending

**FR-1.14 — Return confidence and one of three next actions.**
`approve` (with an amount), `request_info`, or `request_rep_clarification`. Nothing else.
There is no separate escalation or denial outcome. Each action is a proposal to the rep,
and none takes effect on its own.

**FR-1.15 — Never recommend approval under uncertainty.**
Where the overall action confidence or any supporting assessment confidence is low, or
evidence is weak, the action must be
`request_rep_clarification`, with the uncertainty and the clarification needed stated. The
agent may recommend paying only when it can show why.

**FR-1.16 — Request representative clarification when the step budget is exhausted**,
carrying forward whatever was established, so the rep is not handed an empty result. This
path produces a report and no merchant email.

**FR-1.17 — Never present a recommendation as settled.**
The report states what the agent recommends and why. It does not report an outcome as
though it were already reached, and its drafted email is a draft — unsent, and marked as
such — regardless of how confident the recommendation is.

## Reimbursement amount

**FR-1.18 — Read the invoice for what the items cost** — the price at time of
fulfilment, after discounts.

> **Reference — `POST /invoices/generate`**
> ```json
> // request
> { "shipment_id": "342578703", "user_id": "334430" }
>
> // response
> {
>   "invoice_id": "INV-342578703",
>   "shipment_id": "342578703",
>   "line_items": [
>     { "name": "Additional Collagen Ampoule Duo", "sku": "AMP1", "quantity": 1, "unit_price": 38.00 },
>     { "name": "Liposomal Tripeptide Collagen", "sku": "COLLAGEN1", "quantity": 1, "unit_price": 52.00 }
>   ],
>   "generated_at": "2026-03-21T10:00:00.000+0000"
> }
> ```
> **Two discrepancies to be aware of.** The returned line items are identical to
> `GET /orders/334291211` — this endpoint applies no discount and has no discount field.
> And `generated_at` is the same fixed timestamp on every invoice in the set, postdating
> every delivery date, so it is a claim-time snapshot rather than a record frozen at
> fulfilment. Neither "after discounts" nor "at time of fulfilment" is literally satisfied
> by this endpoint. See open question 3.
>
> It can also return `422 invoice_unavailable`, which must be handled.

**FR-1.19 — Cover only the damaged items.** Not the whole order. A crushed bottle in a
six-item order reimburses one bottle.

**FR-1.20 — Cap the amount at $100.**

Per-line processing makes the cap's meaning unavoidable rather than theoretical: three
lines at $50 each are either three payments of $50 or a claim capped at $100. Whichever
reading is chosen, it must be applied at the claim level as well as the line level —
otherwise the cap can be exceeded simply by splitting a claim into more lines. See open
question 2.

> **Reference — `GET /orders/337761802` (CASE-1003, Huge Supplements)**
> ```json
> {
>   "line_items": [
>     { "name": "Bomb Popsicle Wrecked Pre-Workout", "sku": "0041", "quantity": 1, "unit_price": 49.99 },
>     { "name": "Blue Razz Liquid Carnitine", "sku": "0199", "quantity": 1, "unit_price": 34.99 },
>     { "name": "Red/Black HUGE Shaker", "sku": "0157", "quantity": 1, "unit_price": 12.99 },
>     { "name": "2.5LBS White Chocolate Raspberry Huge Whey", "sku": "0159", "quantity": 1, "unit_price": 59.99 },
>     { "name": "Green Apple Wrecked Core Sample", "sku": "0180", "quantity": 1, "unit_price": 9.99 },
>     { "name": "Unflavored Liquid Glycerol", "sku": "0179", "quantity": 1, "unit_price": 27.99 }
>   ]
> }
> ```
> The largest single line item across all five test cases is $59.99, so **no single-item
> claim can reach the cap**. This case is the only one that can: its description says
> "Number of affected orders: 2," and the two most expensive items together are $109.98.
> Demonstrating the cap otherwise requires a constructed case.

**FR-1.21 — The agent decides the amount; code holds it to the cap.**
The agent determines both *what* the claim covers and *how much* it is worth, judging the
damage against the photographs and against how comparable claims were actually settled. How
badly a thing is broken is a judgement, and a rule that paid a fixed share of the price
could not tell a scuffed box from a smashed bottle.

A deterministic function then holds that figure to the cap of FR-1.20, which is the only
limit on it. The figure is read as exact money — text into an exact decimal, never through a
floating point number — and every recommendation carries what was proposed, what the items
cost on the invoice, whether the cap changed the answer, and the agent's own reasoning for
the number.

**This is a deliberate reversal of an earlier requirement, and the cost is stated here so
nobody has to rediscover it.** Until this revision, no monetary figure could come from model
output at all: a deterministic function priced the damaged items and the number in front of
the rep was arithmetic she could check. That made the same claim yield the same figure every
time. It no longer does. The amount is now an estimate to weigh rather than a sum to verify,
two investigations of one claim may propose different figures, and the cap is the only thing
that bounds either. What is bought for that is judgement about damage the arithmetic could
not express.

---

# Layer 2 — The report and email draft

The agent returns a claim report and, only when applicable, a separate merchant email draft.
Together they are the handoff to the rep. **This is where the decision
is actually made**, so the report must contain everything needed to make it — the rep
should never have to go hunting through raw data, and should never have to take a
conclusion on trust.

**There is one report per claim line.** A claim covering two damaged products produces two
reports, each approved or sent back independently.

**FR-2.1 — State confidence, next action, and the amount when approved.**
The report states one of the three actions and the agent's confidence. For `approve`, it
states the approved amount. For `request_info`, it lists the specific additional details
required from the merchant. It is worded as a proposal the rep is deciding on, not as an
action already taken.

**FR-2.2 — Show each evidence item and where it was found.**
All four items, marked present or missing, each linked to the specific attachment it came
from and what was observed in it. The rep must be able to look at the same photo the system
looked at.

> **Reference — attachment identity**
> Each attachment carries a stable `attachment_id` (e.g. `ATT-CASE-1001-02`) and a `url`.
> Findings should reference the `attachment_id`, and the UI renders the image from `url`,
> so a finding is always traceable to the exact image that produced it.

**FR-2.3 — Show each assessment and its reasoning.**
All four assessments, each with what the agent concluded and why — enough for the rep to
disagree with any single one without discarding the rest.

**FR-2.4 — Show how the amount was derived.**
Which items, at which prices, from which document, and how the cap was applied. "$52.00"
alone is not reviewable. "$52.00 — one Liposomal Tripeptide Collagen, invoice price,
under cap" is.

**FR-2.5 — State concerns explicitly.**
Ambiguities, weak evidence, low-confidence assessments, anything that conflicts. A rep who
cannot tell why the system is unsure will either rubber-stamp or redo the work — and both
defeat the purpose. Silence here is a defect, not a clean result.

**FR-2.5a — Make the report decidable at a glance, and checkable in depth.**
The recommendation, the amount, and the concerns must be readable immediately. The evidence
behind them must be one step away. A rep who agrees should be able to approve quickly; a
rep who doubts should be able to verify without leaving the report.

**FR-2.6 — Surface context the rep should know before approving.**
Whether this is a high-value shipment, relevant history for this merchant, and — if a past
correction from the rep influenced this recommendation — which one and how.

**FR-2.7 — Return the merchant email as a conditional second output**, in the exact wording
that would be sent.

- `approve`: draft an email that communicates the exact approved amount.
- `request_info`: draft an email that requests every specific detail needed from the merchant.
- `request_rep_clarification`: return no email draft.

**FR-2.8 — Support the rep's review actions.**
A report is presented to the rep, who may:

1. **Approve it.** The report and its email are accepted as they stand. This releases the
   case to Layer 3, which sends the email and submits any reimbursement.
2. **Send it back with feedback.** The rep describes what is wrong or missing in their own
   words. The agent re-runs with that feedback (Layer R), reworks the report and the email
   accordingly, and returns it for another review.
3. **Edit the email directly.** The rep changes the wording themselves before approving.
   Direct edits are for wording; feedback is for substance.

**FR-2.9 — Approval is the only exit.**
A report leaves the review loop in exactly one way: a rep approves it. There is no
timeout, no confidence threshold, and no volume of revisions that results in automatic
approval. A case may cycle through revision any number of times and still requires a human
to release it.

**FR-2.9a — Show the claim context on every report.**
Each report states which claim it belongs to, which product it covers, and what the other
lines in the same claim are recommending. A rep approving one line should be able to see
that the second line is waiting on evidence, without opening it.

**FR-2.9b — Provide a claim-level view over the line reports.**
The rep works from a case, not from a list of disconnected products. The claim view shows
every line, its recommendation, its amount, and its review state, and allows each to be
approved or sent back individually. It is a view over the line reports, not a separate
decision surface — approval always happens per line.

**FR-2.10 — Be structured data, not prose.**
The report is rendered by a UI and read by a person under time pressure. A block of
narrative text does not meet this requirement.

---

# Layer R — Revision

Not a separate agent. **The same agent from Layer 1**, re-invoked with additional context:
the report it produced, the rep's feedback, and the findings behind it.

Feedback is how the rep exercises judgement without doing the work by hand. She says what
is wrong; the agent reworks the report and the email around it. The decision still waits
for her.

**Why one agent rather than two.** Revision is the same task as investigation — read the
evidence, apply the policy, recommend, draft — with one more input. The tools are the same,
the report schema is the same, and the rules are the same. A second agent would need its
own copy of every policy, and any drift between the two would surface as a rep's correction
silently changing how a rule is applied. One agent, one interpretation.

**The tradeoff, stated plainly.** An agent shown its own prior conclusion may anchor on it
and defend what the rep just rejected. FR-R.3 and FR-R.10 exist to counter that: prior
findings enter as observations of record rather than as the agent's own verdicts, and the
agent must state what it changed, which makes an unchanged conclusion visible rather than
quietly persistent. This is a real weakness worth naming rather than hiding.

**FR-R.1 — Run only on rep feedback.**
Revision is triggered by a rep sending a report back, never automatically and never on any
other signal.

**FR-R.1a — Revise one claim line at a time.**
Feedback applies to the report it was given on. Revising one line leaves the other lines in
the claim untouched, unless the feedback concerns shared evidence (FR-1a.3) — in which case
the change propagates to every line that relied on it, and each affected report returns to
the rep for review. Correcting the packaging photo once should not require correcting it
per line.

**FR-R.2 — Start from the existing work, not from zero.**
The agent receives the current report in full, the rep's feedback, the findings and
reasoning behind the report, and the case data already gathered. It does not re-run the
whole investigation.

**FR-R.3 — Interpret what the feedback means.**
Feedback arrives as a rep's own words — "the packaging photo is the box, not the product,"
"this merchant had the same issue last month," "the amount looks wrong." The agent must
work out which findings, assessments, or amounts that implies changing. This is the
reasoning the layer exists for.

Prior findings are supplied as observations of record — what was seen in which attachment —
rather than as the agent's own conclusions to defend. The rep's feedback is authoritative
about what is wrong; the agent's task is to work out what follows from it, not to argue
with it.

**FR-R.4 — Re-examine evidence when the feedback calls for it.**
It may look again at a specific attachment, or reconsider a specific judgment, where the
feedback points there. Targeted re-examination, not a fresh investigation.

**FR-R.5 — Change only what the feedback bears on.**
Findings and assessments the rep did not dispute carry forward unchanged. A rep correcting
one thing must not have to re-check everything else.

**FR-R.6 — Use the same tool surface, with no write tools.**
Revision adds no capabilities. The agent still cannot send email or submit a reimbursement
in either mode; those remain in Layer 3, behind approval.

**FR-R.7 — Never compute the amount itself.**
If the recommendation or the damaged items change, the amount is recomputed by the same
deterministic function used on the first pass. A revision cannot introduce a figure the
code did not produce.

**FR-R.8 — Not override deterministic rules.**
Feedback cannot make an ineligible claim eligible, exceed the cap, or bypass a required
evidence item. Where feedback asks for something the rules forbid, the agent must say so
plainly in the revised report rather than silently complying or silently ignoring it. That
disagreement goes back to the rep, who remains free to seek further review outside the system.

This is the one place the agent does not defer. The rep decides the claim; she does not
decide the policy, and the agent will not quietly write a payout that the rules do not
support.

**FR-R.9 — Produce a complete revised report.**
The output is a full report in the same structure as the first one — same schema, same
requirements — not a diff or a patch. It is reviewed exactly as the original was.

**FR-R.10 — Show what changed and why.**
The revised report states which findings, judgments, amounts, or wording changed in
response to the feedback, and which were left alone. A rep must be able to confirm their
feedback was understood without re-reading the whole report.

**FR-R.11 — Regenerate the email to match.**
The merchant email is rewritten to reflect the revised report. A revised recommendation
with a stale email is an inconsistent state.

**FR-R.12 — Support repeated revision.**
A report may go around the loop more than once. Each cycle carries the full feedback
history, so the agent does not undo an earlier correction while addressing a later one.
Because the same agent handles every cycle, that history is the only thing distinguishing
one pass from the next.

**FR-R.13 — Retain every version.**
All report versions, the feedback that prompted each revision, and what changed are kept.
This is the record of how a decision was reached and where a human intervened.

**FR-R.14 — Feed corrections into merchant memory.**
Feedback is not only applied to the current case. It is persisted against the merchant
(FR-3.8) so it informs the agent's first pass on that merchant's next case — the system
should be better on the next claim, not just this one. Since it is the same agent in both
places, a correction learned during revision applies directly to future investigation.

---

# Layer 3 — Execution after approval

Deterministic. Runs only once a human has approved.

**FR-3.1 — Execute nothing without explicit rep approval.**
No email, no reimbursement, under any circumstance, at any confidence level. This is a hard
invariant. Execution is triggered by a rep approving a report (FR-2.8, action 1) and by
nothing else.

**FR-3.1a — Execute per claim line.**
Approval is per line, and so is execution: each approved line produces its own
reimbursement submission and its own merchant email. Lines still under review are
unaffected by a sibling's approval.

**FR-3.2 — Send the approved email to the merchant.**

> **Reference — `POST /cases/CASE-1001/email`**
> ```json
> // request
> { "to": "sakukreja@shipbob.com", "subject": "Hello", "body": "Hello Case1001" }
>
> // response
> { "success": true, "message": "Email queued", "case_id": "CASE-xxxx" }
> ```
> The recipient comes from the case's `contact_email`. The response confirms queueing
> only — it echoes a placeholder `case_id` and returns no message identifier, so it cannot
> be used to detect a duplicate send. Deduplication is the caller's responsibility
> (FR-3.5). There is no endpoint for reading replies.

**FR-3.3 — Submit one reimbursement per claim line.**
The reimbursement endpoint accepts a single product per call, which is exactly the claim
line boundary. Each approved line is one call, tracked against that line. There is no
multi-item payload to sequence or partially fail — the API's shape and the system's unit of
work are the same.

> **Reference — `POST /reimbursements`**
> ```json
> // request — note the singular product_name
> {
>   "case_id": "CASE-1001",
>   "order_id": "334291211",
>   "user_id": "334430",
>   "shipment_id": "342578703",
>   "product_name": "Liposomal Tripeptide Collagen",
>   "amount": 52.00
> }
>
> // response
> { "reimbursement_id": "RMB-00101", "status": "approved", "created_at": "2026-03-21T10:00:00.000+0000" }
> ```
> The product is identified by `product_name`, a free-text string, not by `product_id` or
> `sku` — so the name must be carried through exactly as it appears on the order.
> Missing fields return `400 invalid_request`.

**FR-3.4 — Verify what is sent against what was approved.**
The reimbursement API confirms success for any well-formed request, including claims the
system did not approve. Its response is therefore not evidence of correctness. The payload
must be checked against the approved report before being sent, so that an edited draft
cannot result in a different amount than the rep signed off on.

> **Reference — the mock approves everything**
> The collection stores a `201 {"status": "approved"}` example for **all five test cases**,
> including `CASE-1004` (73 days old, closed) and `CASE-1005` (no evidence at all). The
> endpoint performs no validation of eligibility, evidence, or amount. A successful
> response means the request was well-formed and nothing more.

**FR-3.5 — Be safe to retry.**
A double-click, a page refresh, or a retry after a network error must not send a second
email or issue a second reimbursement.

**FR-3.6 — Leave partial failures visible and recoverable.**
If a line's email sends and its reimbursement fails, that line must end in a state showing
exactly what happened, resumable without re-sending the email. A failure on one line leaves
the other lines in the claim unaffected, and the claim view must show a mixed state
honestly rather than reporting the claim as complete.

**FR-3.7 — Record what was actually sent**, including exact payloads and timestamps.

**FR-3.8 — Persist rep corrections against the merchant.**
When a rep edits or overrides a recommendation, store what changed and why, keyed to the
merchant's stable identifier. That correction must be available to the agent the next time
that merchant files a claim — the system should improve on the next case, not just this one.

> **Reference — which field identifies a merchant**
> Key on `user_id` (e.g. `"334430"`), which is stable and appears on both the case and the
> order. Do not key on `account_name` (`"Best Paw Nutrition"`), which is display text.
>
> All five test cases belong to five different `user_id`s — `334430`, `283959`, `373103`,
> `374167`, `398045` — so no repeat merchant exists in the sample data. Demonstrating
> carry-forward requires a constructed second case sharing a `user_id` with an existing one.

---

# Claim precedent — finding similar past claims

Consistency is the problem this system exists to solve, and Layers 0 to 2 solve only half of
it. They make every claim reach the rep examined the same way, against the same rules, in the
same shape. They do nothing to make today's claim agree with a materially identical claim that
was handled three weeks ago, because nothing in the system remembers that claim. Two reps can
still disagree, the same rep can still disagree with herself, and nobody finds out.

The precedent store is that missing memory. Every claim line the agent investigates is written
down: what was claimed, what the evidence showed, what was recommended, and what the rep did
about it. When a new claim line is investigated, the most similar past lines are pulled back out
and handed to the agent as context. The recommendation is then made with sight of how comparable
claims actually went, and one that departs from them is visible as a departure rather than
passing unnoticed.

**Precedent informs; it never decides.** A retrieved record is an observation about a different
claim. It cannot supply evidence this claim lacks, lift the cap, or change a Layer 0 verdict. Its
job is to make the agent's reasoning consistent and its disagreements visible — not to give the
agent a second source of authority alongside the evidence.

**Where it sits.** Retrieval runs after triage (FR-1a) and before each per-line investigation
(FR-1b). Deliberately not inside Layer 0: judging whether two claims are alike means comparing
meaning rather than matching fields, and that is not the kind of rule Layer 0 is allowed to
contain (FR-0.6). Keeping it out also keeps ineligible claims free of the cost (NFR-8) — a claim
stopped at the gates is never searched against the store and never written to it.

**How this differs from merchant memory (FR-3.8).** Merchant memory answers "what has *this
merchant* been told before?" and is found by `user_id` — an exact match on identity. Precedent
answers "how has a claim *like this one* been handled?" and is found by what happened, across
every merchant. A claim may have both, one, or neither. They are two lookups over two questions
and must reach the rep as two things: merged into one list, a single past case can read as two
independent confirmations of the same point.

**FR-S.1 — Record a claim line only once it is closed.**
A precedent record is written when a claim line reaches its end: a representative decided it,
and that decision took effect. Nothing is recorded before then.

Precedent exists to make recommendations consistent, and only a decided claim says anything
about how ShipBob actually handles a situation. A line still sitting in review has no outcome —
the system suggested something and nobody has agreed or disagreed yet. Showing that to a later
investigation would teach it what this system already guessed, which is not consistency but
repetition: the first guess about a kind of claim becomes the reason to guess the same way
again, and every claim then agrees with the last one while nobody has checked any of them.

So being in the store *means* the claim was closed. There is no record with an unsettled
outcome, and therefore nothing to weigh differently.

**FR-S.2 — Removed.** This required every record to carry what a representative did about it, so
that a decided outcome could be told apart from an unreviewed suggestion. FR-S.1 now keeps
unreviewed lines out of the store altogether, so there is nothing left to distinguish.

**FR-S.3 — Record enough to judge whether two claims are really alike.**
A record holds what the merchant said happened, which product was claimed and what kind of thing
it is, which of the four evidence items were present and what each assessment concluded, the
outcome the claim closed on, the amount paid and whether the cap bound it, and any note the
representative left explaining the decision. The test is a human one: someone reading a record should be able to say
"yes, that is the same situation" or "no, it is not". A precedent nobody can check is worse than
no precedent, because it still carries weight.

**FR-S.4 — Retrieve on what happened, not on who it happened to.**
Similarity is over the substance of the claim: the kind of damage, the kind of product, the
pattern of evidence present and missing, the shape of the merchant's account of it. Not the
merchant, the case number, the carrier, or the date. A claim's closest precedent will usually
belong to a different merchant, and that is the intent — a rule applied to one merchant and not
another is the inconsistency, not the fix for it.

**FR-S.5 — Retrieve once per claim line, between triage and investigation.**
Each line gets its own retrieval and its own set of records, because from Layer 1b onward each
line is its own claim (FR-1b.1). How many records come back, and how close a record must be to
come back at all, are policy values (FR-0.7). Records that are not close enough are not returned:
a small set, or an empty one, is a correct answer rather than a failure.

**FR-S.6 — Give precedent to the agent as starting context, not as a tool.**
Precedent arrives with the case, the same way the computed facts of FR-0.5 do. It is not
something the agent may choose to look up. If it were, two runs of the same claim could differ
purely in whether the agent thought to search — precisely the run-to-run variance NFR-1 forbids,
introduced by the feature meant to reduce it.

**FR-S.7 — Removed.** This required the agent to weigh a record according to who decided it,
because the store held both settled outcomes and the system's own unreviewed suggestions. FR-S.1
now admits only closed claims, so every record carries a decision somebody stood behind and they
all count the same.

**FR-S.8 — Never let precedent stand in for evidence, or override a rule.**
A claim with no photographs does not become approvable because a comparable claim that had
photographs was approved. Precedent cannot raise the $100 cap, satisfy a missing evidence item,
reverse a Layer 0 terminal verdict, or push a figure past the cap FR-1.21 applies. Where
precedent and the evidence in front of the agent point different ways, the evidence governs and
the disagreement is reported (FR-S.10).

**FR-S.9 — Say when precedent influenced the recommendation, and which records did.**
The report names the records relied on and what each one contributed (NFR-3). "Approval is
recommended" and "approval is recommended partly because four comparable claims were approved"
are different statements, and the rep is the one deciding, so she is owed the second. She must be
able to open a cited precedent and disagree with the comparison.

**FR-S.10 — Report a departure from precedent as a concern.**
When the recommendation differs from how comparable claims were handled, the report says so under
FR-2.5, naming the records it differs from. This is the most valuable thing the store produces:
it is the moment an inconsistency becomes visible while it can still be fixed — before a merchant
is told anything — rather than months later, when two merchants compare the answers they got.

**FR-S.11 — Pin the retrieved set to the run that used it.**
The report and the audit record (NFR-5) hold exactly which records a run was given. Re-running a
stored investigation replays that pinned set, and a Layer R revision reuses the set from the run
it revises rather than retrieving afresh.

Without this the store quietly breaks NFR-1. The store grows between runs, so the same claim
investigated twice would see different precedent and could produce a different report; and a
revision could change its recommendation because the store had moved rather than because the rep
said anything. Pinning is what keeps a report reproducible from the case alone, and what keeps a
revision answering the feedback it was given (NFR-5a).

**FR-S.12 — Keep precedent out of the merchant email.**
Precedent is internal. No other merchant's name, product, amount, case, or wording may appear in
the drafted email, and the email must never offer a past claim as a reason for this one. The rep
sees precedent; the merchant sees only their own claim.

**FR-S.13 — Treat an empty or unavailable store as an ordinary state.**
"No similar claims" is the normal answer for the first claim ever filed, and stays the normal
answer for an unusual one. The investigation proceeds without precedent, and the report says that
is what happened. If retrieval itself fails, the claim still proceeds (NFR-4) and the report
distinguishes "no precedent exists" from "precedent could not be read" — reporting the second as
the first would tell a rep there is no comparable history when in fact nobody looked.

**FR-S.14 — Allow a record to be withdrawn from retrieval.**
An approval can be wrong, and once it is precedent it is repeated. There must be a way to take a
record out of retrieval. Withdrawal affects future searches only: the claim's own audit record is
untouched (NFR-5), and a report that already cited the record still shows what that run was
given (FR-S.11).

> **Reference — what a record holds, and why none exist yet**
> Every record is a *closed* claim: there is no field saying whether anybody reviewed it,
> because an unreviewed line is never written (FR-S.1).
> ```json
> {
>   "precedent_id": "PREC-CASE-1001-COLLAGEN1",
>   "case_id": "CASE-1001",
>   "user_id": "334430",
>   "product": { "name": "Liposomal Tripeptide Collagen", "sku": "COLLAGEN1", "unit_price": 52.00 },
>   "merchant_account": "Product arrived damaged. Both product and shipping box damaged. Damage due to poor/bad packaging.",
>   "evidence_present": ["invoice", "damaged_product_photo", "outer_packaging_photo"],
>   "evidence_missing": ["customer_confirmation"],
>   "outcome": "request_info",
>   "amount_usd": null,
>   "rep_note": null,
>   "withdrawn": false
> }
> ```
> Illustrative, not specified. No endpoint returns this shape, because no endpoint knows about
> it — the system writes these records itself, as it does merchant memory (FR-3.8).
>
> **The sample data cannot demonstrate this feature.** Five cases exist, each a different
> scenario for a different `user_id`, so no two of them are alike and the store is empty on the
> first run of any of them. Showing retrieval working needs constructed history, exactly as
> FR-3.8's carry-forward does.

**Not specified by ShipBob.** How close two claims must be to count as similar, how many records
a run should see, how much weight an approved outcome carries against fresh evidence, and how
long a record stays relevant before a policy change makes it misleading are all judgement calls
that nobody has ruled on. They belong in the single policy place (FR-0.7) so they can be
corrected once real guidance exists, and no starting value for any of them should be read as
ShipBob's position.

---

# Carry-forward — what a rep decided, and what the next claim knows

Two things in this system are meant to get better with use. Merchant memory remembers what a rep
has already corrected for a particular merchant (FR-3.8). The precedent store remembers how a
claim like this one was handled, whoever it belonged to (FR-S.1). Both are read on the way in:
memory arrives with the facts computed before the agent runs (FR-0.5), and precedent arrives
before each per-line investigation (FR-S.6).

Both are written on the way out, and that half is the one nothing so far specifies. Every write is
caused by the same event — **a rep deciding a claim line** — and no requirement says that event is
written down anywhere. FR-2.8 says what a rep may do. FR-3.1 says an approval is what releases
execution. FR-3.8 and FR-R.14 say a correction is persisted against the merchant. FR-S.1 says a
precedent record is written when a line closes. None of them says who writes those records, or
from what. So the promise the system makes — *better on the next claim, not just this one* — rests
on a step that does not exist, and both stores can currently only be read.

This section specifies that step. It is deliberately small: one record of what a person decided,
and two writes derived from it.

**Recording a decision is not executing one.** Writing down what a rep chose sends no email and
moves no money. FR-3.1 still governs execution and nothing here relaxes it. Keeping the two apart
is also what lets the decision survive a failed send (FR-3.6): what the rep decided is a fact
about the rep, not about whether an API call worked.

**FR-C.1 — Record what the rep decided, per claim line.**
Every review action (FR-2.8) produces one durable record: which claim line it was taken on, which
version of the report the rep was looking at (FR-R.13), which action they took, what they changed
if anything, their own words if they gave any, and when. This record is the only thing FR-C.2 and
FR-C.3 read, and it is the audit trail's account of where the human intervened (NFR-5).

Recorded per line, because approval is per line (FR-3.1a). A rep who approves one line and sends
another back has taken two decisions, and both are recorded.

**A claim stopped in Layer 0 is the exception, and it is not a rare one.** It still produces a
report a rep approves (FR-0.4), but it has no claim lines at all: the split into lines happens in
Layer 1a, which a terminal claim never reaches. So the record must be able to name a whole claim
as well as a single line — the same fields, with no line named — rather than a line being
invented so the decision has somewhere to sit. This is also the cheapest decision in the system,
costing no AI at all (NFR-8), which makes it the first one likely to be built.

> **Reference — what a decision record holds**
> ```json
> {
>   "decision_id": "DEC-CASE-1001-COLLAGEN1-01",
>   "case_id": "CASE-1001",
>   "claim_line_id": "CASE-1001-COLLAGEN1",
>   "report_version": 2,
>   "action": "approved_with_override",
>   "recommended": { "outcome": "request_info", "amount_usd": null },
>   "decided":     { "outcome": "approve",      "amount_usd": "31.20" },
>   "rep_words": "Customer confirmation came in by phone, logged separately.",
>   "decided_by": null,
>   "decided_at": "2026-03-21T10:04:11.000+0000"
> }
> ```
> Illustrative, not specified. No ShipBob endpoint knows about this shape; the system writes it
> itself, as it does merchant memory and precedent.
>
> **`decided_by` has nowhere to come from.** There is no sign-in anywhere in this system, so the
> record cannot say which rep decided. The field must exist and be left empty rather than filled
> with a guess or dropped: an audit record that silently has no author is worse than one that says
> plainly that it does not know.

**FR-C.2 — Write a merchant correction from a difference, not from a narrative.**
A correction is stored only when what the rep decided differs from what the system recommended: a
different outcome, a different amount, a different set of damaged items, or an edit that changed
what the email *tells* the merchant rather than how it reads. FR-2.8 already draws that line —
direct edits are for wording, feedback is for substance — and only substance is worth remembering.

The correction is keyed to the merchant's stable identifier (FR-3.8's reference note: `user_id`,
never `account_name`). It must say what the system got wrong and what the right answer was, in
enough words for the next investigation to act on it. "The amount was wrong" carries nothing. "The
two-pack was claimed, not the single bottle" changes the next run.

**A decision that agrees with the recommendation writes no correction.** A memory of every
decision is a memory of nothing: it would fill the next claim's context with confirmations and
bury the one correction that mattered.

**FR-C.3 — Close a claim line explicitly, and write its precedent then.**
FR-S.1 says a precedent record is written when a line closes and never before. This says what
closes it: an approval that took effect. A report sent back for revision does not close a line
(FR-R.1). Neither does an approval whose execution failed (FR-3.6) — a line whose email never
reached the merchant has not been settled with them.

The record carries the outcome that actually took effect and the amount actually submitted, not
the outcome the agent recommended. Where a rep overrode the recommendation, precedent must show
what ShipBob did rather than what this system suggested; remembering decisions is the entire point
of the store, and remembering its own guesses is the failure FR-S.1 exists to prevent.

**A claim stopped in Layer 0 closes without ever becoming precedent.** Nothing was investigated:
no evidence was read and no product was assessed, so the record FR-S.3 describes would be almost
entirely empty, and a later claim compared against it would be compared against nothing. NFR-8
already says a claim stopped at the gates is never written to the store, and this is the same
rule seen from the other end. It may still write a correction under FR-C.2 — a rep who pays a
claim the gates wanted to refuse has corrected the system, and the next claim by that merchant
should know it.

**FR-C.4 — Make both writes repeatable, and never let them fail a decision.**
Deciding the same line twice — a double-click, a retry after a timeout — must leave one
correction and one precedent record rather than two (FR-3.5, and FR-S.1's rule that closing a line
again replaces its record rather than adding a second).

If either write fails, the decision stands and execution proceeds. Losing the record of what was
learned is bad; losing the decision a person made is worse. But the failure must be visible in the
case's audit record (NFR-5) and recoverable, because a silent failure here means the system
quietly stops improving — which looks exactly like it working.

**FR-C.5 — Make a carried-forward influence traceable in both directions.**
Forwards: a report influenced by a past correction names it and says how (FR-2.6), the same way it
names the precedent it relied on (FR-S.9).

Backwards: a stored correction names the case, the claim line and the decision it came from, so a
rep reading "this merchant was corrected about X" can open the claim where that happened and judge
whether it still applies. A correction whose origin cannot be checked cannot be trusted, argued
with, or safely removed.

**FR-C.6 — Allow a correction to be withdrawn.**
Corrections can be wrong, and a wrong one is repeated on every future claim by that merchant. This
is the same failure FR-S.14 addresses for precedent, and merchant memory has no way out of it
today. Withdrawal affects future claims only: a report already influenced by the correction still
shows what that run was given (FR-S.11).

**FR-C.7 — Say what "more care" means for a high-value claim.**
A high-value shipment is worked out before the agent runs (FR-0.5) and shown to the rep, and
nothing else in the system treats it differently. It is a line of context and no more. That may be
the intent, or a high-value claim may be meant to be handled differently — and the requirement has
to say which, because "warrants more care" is currently satisfied by one sentence of prompt text
that no rule depends on.

Three readings, none of them chosen:

1. **Presentation only.** The rep is told, and decides what extra care to take. This is what
   exists today.
2. **Never recommend approval above the threshold.** A high-value claim asks for
   representative clarification with its value as the stated reason, however good the evidence is.
3. **A higher bar, not a different outcome.** High-value claims are held to a stricter confidence
   threshold than FR-1.15's, so the same quality of evidence approves a small claim and asks the
   representative to clarify a large one.

Whichever is chosen, the rule belongs beside the threshold in the single policy place (FR-0.7,
NFR-7), and it must be a deterministic rule if it changes an outcome. Asking a model to try harder
on expensive claims is not a control, and would show up as run-to-run variance (NFR-1) rather than
as care.

**FR-C.8 — Demonstrate carry-forward on constructed data, and label it as constructed.**
The sample data cannot show any of this. All five cases belong to five different merchants
(FR-3.8's reference note) and no two of them are alike (the precedent reference note), so no case
ever sees a correction or a precedent produced by another. A demonstration needs a constructed
second case sharing a `user_id` with an existing one, and a first case carried all the way to a
decision.

That data is development-only. It must say in its own words that it is invented, must be written
through the same stores a real decision writes to rather than around them, and must be removable
again — otherwise invented history on a screen is indistinguishable from real history, and a rep
has no way to tell.

**Not specified by ShipBob.** Whether a correction should ever expire, or stop applying after a
policy change; whether a correction made on one merchant should ever inform a claim by another
(FR-S.4 deliberately ignores identity, which pulls the other way); how many corrections an
investigation should be shown before they crowd out the evidence in front of it; and whether a
high-value claim is handled differently at all (FR-C.7) are all judgement calls nobody has ruled
on. They belong in the single policy place (FR-0.7), and no starting value for any of them should
be read as ShipBob's position.

---

# Non-functional requirements

**NFR-1 — Consistency.**
The same claim, investigated twice, must produce the same report: the same findings, the
same recommendation, the same figure.

Inconsistency between reps is the problem this system exists to solve, and the mechanism is
this: reps go on deciding, but every claim now reaches them examined the same way, against
the same rules, presented in the same form. Two identical claims look identical on arrival,
so they are far more likely to be decided alike. Consistency is therefore a property of the
report, not a constraint on the rep. Anything introducing run-to-run variance in a report
needs a specific justification.

Per-line isolation extends this within a claim: the same product with the same evidence reaches
the same recommendation regardless of what else was claimed alongside it (FR-1b.4).

Precedent extends it between claims. A line is investigated with sight of how comparable lines
were handled, and a departure from them is reported rather than passing silently (FR-S.10) — this
is the only part of the system able to notice two claims disagreeing. It is also the sharpest
risk to this requirement, because the store grows: without care, the same claim investigated
twice would see different precedent and could produce a different report. FR-S.11 is what
prevents that, by pinning the records a run was given to that run.

**NFR-2 — Constrained model output.**
Every AI response conforms to a defined schema — classifications, judgments, structured
findings. The model never returns a free-form verdict.

A monetary amount **is** now taken from model output, which FR-1.21 explains and which this
requirement previously forbade. It is constrained rather than free: the figure is a schema
field written as money, refused outright if it is not, read into an exact decimal, and
capped. Merchant-facing wording still carries no figure the model wrote — a marker is
substituted after the cap has been applied, so what reaches a merchant is the figure that
survived it and not the one that was proposed.

**NFR-3 — Explainability.**
Every conclusion traces to the observation that produced it. It must be possible to answer
"why this amount?" and "why is representative clarification needed?" from the report itself,
without reading
logs or re-running anything. The rep is being asked to decide, so she must be able to
audit any part of what she is deciding on.

**NFR-4 — Fail toward the human.**
Any failure — model error, API timeout, malformed response, exhausted budget — results in a
claim report requesting representative clarification and no merchant email. No failure path
leads to an unreviewed approval or a silently dropped case.

**NFR-5 — Auditability.**
Each case retains an ordered record of what each agent did, what it observed, what it
concluded, every rep action including feedback and revisions, and what was ultimately sent.

**NFR-5a — Convergent revision.**
Each revision must address the feedback it was given without regressing earlier
corrections. A rep should not find that fixing one thing has broken another they already
approved.

**NFR-6 — Resilience.**
Unavailable APIs, missing credentials, and unreachable images are handled states with clear
messages, not crashes. The system must be demonstrable without live API access.

**NFR-7 — Configurability.**
Policy values are changeable without touching logic, because several of them are judgement
calls rather than stated policy and may need to change once real guidance exists.

**NFR-8 — Cost discipline.**
Ineligible cases must not incur AI costs. Image analysis, the most expensive operation,
runs only on attachments that need it and is not repeated for the same attachment within a
case. Precedent is retrieved once per claim line and only for claims that passed the gates; a
claim stopped in Layer 0 is never searched against the store and never written to it.
