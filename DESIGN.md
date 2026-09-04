# Design

How this system works, written for someone who has never seen it before.

[REQUIREMENTS.md](REQUIREMENTS.md) says **what** the system must do. This file says **how** we
built it, in plain English. You should not need to be an engineer, or know anything about this
project, to follow along.

Every feature we build adds a section under [Features](#features). Read together, those
sections are the design of the whole project.

> **Adding a section?** Copy the [template](#template) below and follow the writing rules in
> [CLAUDE.md](CLAUDE.md#design). Plain words, short sentences, no jargon.

---

## The short version

ShipBob stores and ships parcels on behalf of merchants. Sometimes a parcel arrives crushed, or
the product inside is broken, and the merchant asks to be paid back for the damaged goods.

Today a support representative handles that by hand. They read the complaint, open the photos,
check whether the claim qualifies, work out how much to pay, write an email, and send it. It is
slow, and — the bigger problem — two representatives can reach two different answers on the
same facts.

This system does the slow part. For each damaged product it gathers the evidence, checks it
against the rules, works out what it would suggest, and writes a draft email to the merchant.
Then it stops.

**The system never decides, and never sends anything.** A representative reads what it found and
either approves it or sends it back with a note saying what is wrong. Only after a person
approves does an email go out or money move. The system's job is to make every claim arrive
examined the same way, so the person deciding has less to do and fewer reasons to be
inconsistent.

## Words used here

These come from REQUIREMENTS.md, which holds the authoritative definition of each.

| Word | What it means |
|---|---|
| **Merchant** | The brand whose goods were damaged. ShipBob's customer, and the only party we ever write to. |
| **End customer** | The person who received the parcel. We never contact them. |
| **Case** | The complaint the merchant opened. We read cases; we never create them. |
| **Claim line** | One damaged product inside a case. Two damaged products means two claim lines, each handled on its own. |
| **Rep** | The ShipBob support representative who reviews our work and makes the actual decision. |
| **Attachment** | A photo or screenshot the merchant uploaded — the damage, the box it arrived in, an invoice, an email. |
| **Report** | What we hand the rep for one claim line: what we found, what we suggest, and a draft email. |
| **Reimbursement** | The payment back to the merchant. Only ever sent after a rep approves. |

## How the pieces fit together

Work moves through four stages. Each one hands off to the next.

**1. Quick checks first.** Before doing anything expensive, we ask a few cheap questions with
clear right answers. Is the parcel too old to claim on? Is this even the right kind of
complaint? Is the basic information there? Was the parcel insured, which means it goes down a
different path entirely? These are fixed rules, not judgement — the same case always gets the
same answer. If a claim fails here we stop, but we still write the merchant an explanation for
a rep to approve.

**2. Split the claim up.** One complaint can cover several damaged products, and the merchant's
description usually does not name them. So we read the description and look at the photos to
work out which products are being claimed for. Each one becomes its own claim line. If we
cannot tell which products are meant, we say so and hand it to a rep rather than guess.

**3. Investigate each product.** For every claim line separately, we look for four things: proof
of what was ordered and its price, confirmation from the person who received it that the damage
happened, photos of the damaged product, and photos of the outer box. If any of those is missing
— or present but too blurry to be useful — we ask the merchant for exactly the missing item
rather than assume. If everything is there, we check that the damage is visible, that we can
tell which product it is, and that the product was really on the order. Then we suggest one of
four things: pay, ask for more information, refuse, or hand it to a person. Any amount of money
is worked out by fixed arithmetic, never by the AI, so the same claim always produces the same
figure and a rep can check the sum.

**4. A person decides, then we act.** The rep reads the report. They can approve it, edit the
email wording, or send it back with feedback in their own words — in which case we rework the
report around what they said and hand it back for another look. There is no timeout and no
automatic approval; a person approving is the only way out. Once they do, we send the email and
submit the payment, and we record exactly what was sent.

A rep's correction is also remembered against that merchant, so the next claim from them starts
better informed.

## What exists today

The repository currently holds the foundation only: the service skeleton, project tooling, and
the empty packages for each stage above. None of the four stages is implemented yet. Each
feature adds its section below as it is built.

---

## Features

Sections appear in the order they were built. Each is self-contained — you can read one without
reading the others.

### Template

Copy this for a new feature. Keep it to roughly a page.

```markdown
### <Feature name in plain words>

**What it does** — One or two sentences. No jargon.

**Why we need it** — The problem it solves, and the requirement ids it satisfies (e.g. FR-0.2).

**How it works** — Numbered steps, in the order they happen, as you would explain them out loud.

**What it connects to** — What it reads, what it produces, and what else it depends on.

**Choices we made** — What we picked, what we turned down, and why. Include anything still undecided.

**When things go wrong** — What can fail, and what the system does about it.

**Where the code is** — File paths, for a reader who wants to go look.
```

---

### The service skeleton

**What it does** — Gives the project a running web service to hang everything else on. It
answers one request today — a health check that confirms the service is alive — and provides the
shared plumbing every future feature will use: settings, claim policy values, error handling,
and logging.

**Why we need it** — Features need somewhere to live. Building this first means every later
feature starts from working foundations instead of inventing its own way to read configuration
or report a failure. It also puts the claim policy values in one findable place, which the
requirements ask for directly (FR-0.7, NFR-7).

**How it works**

1. When the service starts, it reads its configuration: which environment it is running in,
   where the ShipBob system lives, and the keys it needs. Anything missing falls back to a safe
   local default rather than crashing.
2. It separately reads the **claim policy** — the money cap, the age limit, and the other
   thresholds used to judge claims. These live apart from ordinary settings because they are
   business rules an operator may need to change, not technical plumbing.
3. It switches on logging, where every line is a set of labelled fields rather than a sentence.
   That means someone investigating a problem can search for one case number instead of reading
   through text.
4. It builds the web service, giving it a tag for each incoming request so all the log lines
   from one request can be found together.
5. It registers a single translator for failures, so every error leaves the system in the same
   shape and never reveals internal details to whoever is calling.

**What it connects to** — Nothing yet. It reads configuration from the environment. Every
feature built after this one starts from it.

**Choices we made**

- **Policy values sit in their own file, separate from technical settings.** The requirements
  ask for one named place for them, and mixing them with database URLs would bury them.
- **Only the $100 cap is a real number.** The age limit, the high-value threshold, the
  confidence threshold, and the step budgets are placeholders we invented so the code runs. They
  are labelled as provisional and need ShipBob to confirm them.
- **Configuration is handed to the service rather than read from a global.** This means a test
  can run the service with different values, which keeps later features easy to test.
- **Still undecided:** where reports, feedback, and merchant history will be stored. Nothing is
  chosen, so the storage area is deliberately empty.

**When things go wrong** — A failure the system expects (something not found, a bad request, a
dependency being unreachable) returns a clear message and the right status. Anything unexpected
is written to the logs in full but returns only a generic message to the caller, so an internal
detail such as a password in an error string cannot leak out.

**Where the code is** — `src/claim_agent/app.py`, `settings.py`, `policy.py`, `errors.py`,
`observability.py`, and `src/claim_agent/api/`.
