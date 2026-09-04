# Design

How this system works, written for someone who has never seen it before.

[REQUIREMENTS.md](REQUIREMENTS.md) says **what** the system must do. This file says **how** we
built it, in plain English. You should not need to be an engineer, or know anything about this
project, to follow along.

Every feature we build adds a section under [Features](#features). Read together, those
sections are the design of the whole project.

[Future production](#future-production) at the end lists what is deliberately not built yet and
what could break under real use.

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

Stage 1, the quick checks, is being built now. The records it works on, the shapes it produces,
and the sample data it is tested against are in place; the checks themselves, the connection to
ShipBob, and the merchant memory are next. Stages 2 to 4 are untouched.

The sections below are written before the code they describe, then corrected once it works. A
section may therefore describe something still being built — [What exists
today](#what-exists-today) is the honest list.

For what that leaves missing or fragile, see [Future production](#future-production).

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

**Not ready for production** — What you knowingly left out, simplified, or hardcoded, and what
could break under real use. Copy anything lasting into [Future production](#future-production).

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

**Not ready for production** — Anyone who can reach the service can call it; there is no
authentication of any kind. The health check only says the process is running, not that it can
reach anything it depends on. Secrets are read from a local file rather than a secret manager.

**Where the code is** — `src/claim_agent/app.py`, `settings.py`, `policy.py`, `errors.py`,
`observability.py`, and `src/claim_agent/api/`.

---

### Reading a case from ShipBob

**What it does** — Fetches the three records a claim is built from: the complaint the merchant
opened, the parcel it is about, and the order that parcel came from.

**Why we need it** — Everything else needs these facts, and this is the first part of the system
that talks to ShipBob at all (FR-0.1). It is deliberately narrow: three reads and nothing else.
It cannot fetch photos, cannot ask for an invoice, and cannot send anything. Those belong to
later stages, and keeping them out of here means no later change can accidentally make the cheap
first stage expensive (NFR-8).

**How it works**

1. Ask ShipBob for the case. It carries the identifiers for everything else.
2. Ask for the parcel and the order at the same time, since neither depends on the other.
3. Turn each answer into a checked record. Anything that does not fit the expected shape is
   refused rather than half-understood.

**What it connects to** — It reads from ShipBob and hands three records to the pre-flight
checks. Nothing else calls it yet.

**Choices we made**

- **Money is read exactly as written.** A price of `38.00` is kept as thirty-eight dollars and
  zero cents, not as a number a computer rounds. This sounds fussy and is not: the ordinary way
  of reading prices quietly turns `38.00` into `38`, and two different-looking answers for the
  same claim is the exact problem this project exists to prevent.
- **Every time is converted to one common clock.** ShipBob can write the same moment in more than
  one style, and a day count must not change because of how a date was spelled.
- **A parcel with no insurance flag is refused, not assumed.** If ShipBob does not tell us whether
  a parcel was insured, we stop and say so. Guessing "not insured" would send an insured claim
  down a path the requirements say it must never take.
- **We try again, but not forever.** A read is attempted up to three times, with a short and
  growing pause. Three is a guess, and it is a setting rather than a fixed number.
- **We do not try again when the answer will not change.** A missing record or a reply we cannot
  read is a real answer; repeating the question only wastes time.

**When things go wrong** — A case that does not exist is reported as not found. A parcel or an
order that does not exist is not an error: the claim simply lacks something, and the checks below
decide what that means. Anything else — ShipBob being down, slow, or answering with something we
cannot read — is reported as an upstream failure. The full detail goes to the logs; the caller
gets a plain message with nothing internal in it.

**Not ready for production** — We work from the example payloads quoted in the requirements,
because the full description of ShipBob's endpoints is not in this repository. If the real
replies differ, our reading of them is wrong. There is no circuit breaker: if ShipBob is down,
every claim keeps trying and keeps failing.

**Where the code is** — `src/claim_agent/shipbob/client.py`, `src/claim_agent/domain/models.py`.

---

### Remembering a merchant

**What it does** — Keeps a note of the corrections a representative has made on a merchant's
earlier claims, so the next claim from that merchant starts better informed.

**Why we need it** — ShipBob has no place to store this. There is no endpoint that says "this
merchant's claims have been wrong in this way before", so the system has to remember it itself
(FR-0.1, FR-0.5). Without it, every representative would keep making the same correction.

**How it works**

1. Notes are filed against the merchant's account identifier — the stable number that appears on
   both the case and the order, not the brand name, which is only display text and can change.
2. When a claim arrives, the system looks up every note filed against that merchant and passes
   them along as starting context.
3. Notes come back in the order they were written, always, so the same claim reads the same way
   twice.

**What it connects to** — It is read by the pre-flight checks and passed to the agent as
context. Nothing writes to it yet; representative feedback is a later stage.

**Choices we made**

- **A single database file on disk.** It survives a restart, needs no server to be running, and
  is one of the few things a reader can inspect by hand. This was an open question until now;
  it is settled for merchant memory, not for reports or the audit trail.
- **A fresh connection for each read.** These reads are tiny and this avoids a whole class of
  problem where a shared connection is used from the wrong place.
- **The table can be written to, even though nothing writes to it yet.** A store that can only be
  read is not really a store, and the code that writes corrections arrives with a later
  requirement. Today it is used only by the tests.
- **A merchant with no notes is not an error.** It is the ordinary case, and it comes back as an
  empty list.

**When things go wrong** — A missing database file is created on first use. A claim whose case
has no merchant identifier gets no notes and carries on; it is not treated as a failure.

**Not ready for production** — One file on one machine. A second copy of the service would not
see the first one's notes, and there is no backup. The read blocks the request while it happens;
that is fine for a local file and would not be for a real database.

**Where the code is** — `src/claim_agent/storage/merchant_memory.py`,
`src/claim_agent/storage/database.py`.

---

### The pre-flight checks

**What it does** — Answers one cheap question before anything expensive happens: can this claim
be processed at all? It either says *carry on* or *stop, and here is why*.

**Why we need it** — Some claims are dead on arrival no matter how good the photos are. Finding
that out first means an unprocessable claim costs three quick reads instead of a full
investigation with an AI reading every image (FR-0.2, FR-0.3, NFR-8). It also removes a whole
class of inconsistency: these are questions with right answers, so no judgement is involved and
the same claim always gets the same verdict (FR-0.6).

**How it works**

1. Read the case, the parcel, and the order, and look up anything remembered about the merchant.
2. Work out which delivery date to trust. The case's own date is used when it has one, otherwise
   the parcel's. If the two disagree, we use the case's and record both, so a person can see the
   disagreement instead of it being smoothed away.
3. Run four checks:
   - **Is the parcel too old?** Count the days from delivery to the day the merchant opened the
     case, and compare that with the limit.
   - **Is this the right kind of complaint?** Only damage-in-transit is handled here.
   - **Is the basic information there?** A claim with no parcel, no order, or no description of
     what happened has nothing to investigate.
   - **Was the parcel insured?** Insured parcels follow a completely different process and must
     never be handled here.
4. Work out the facts the AI should not have to rediscover: what the order was worth, whether
   that counts as high value, how many days passed, and what a representative has previously
   corrected for this merchant (FR-0.5).
5. Give a verdict. If all four checks pass, the claim carries on to the next stage with those
   facts attached. If any fails, it stops, and the reasons go into a report for a person.

**What it connects to** — It reads from ShipBob and from merchant memory. It produces a verdict,
the four check results, and the starting facts, which the next stage will use. It is reachable
directly so a claim can be screened and inspected on its own.

**Choices we made**

- **All four checks always run, even after one has failed.** Stopping at the first failure would
  save nothing — the information is already in hand — and would hide facts a person needs. A
  representative should be able to see that a claim is *both* insured *and* three months old.
- **The result records what each check looked at, not just its answer.** "Why was this stopped?"
  has to be answerable from the result itself, without reading logs or running anything again.
- **The clock is never consulted.** The age check compares two dates that both come from ShipBob,
  so a claim that was 73 days old when it was filed is 73 days old forever. Re-running this next
  year gives the same answer, and a number in a stored report never goes stale.
- **The days count is whole calendar days.** "Delivered on the 26th, filed on the 9th" is what a
  person can check by looking at a calendar.
- **The complaint type must match exactly.** We ignore capitals and extra spaces, because those
  are just typing. We deliberately do not accept anything merely *starting* with the right words:
  a category called "damaged in transit — insured" is a different thing entirely, and treating it
  as a match would send an insured claim down this path, which is the single worst mistake
  available here.
- **What counts as missing.** A field that is absent, empty, or only spaces is missing. So is a
  record ShipBob could not give us — a parcel that does not exist and a case with no parcel
  number are the same problem, and the result says which of the two it was.
- **No delivery date anywhere stops the claim.** A check we cannot carry out must never quietly
  pass. We report it as missing information rather than inventing a fifth kind of reason. This is
  our judgement, not a stated rule, and it is one of the things worth confirming.
- **When several checks fail, they are ranked.** Insurance first, then age, then wrong type, then
  missing information. Telling a merchant "too old" when the real answer is "claim on your
  insurance" is actively unhelpful, and asking for more photos on a claim being closed for age is
  worse. The ranking is a judgement call and is a setting, not a fixed rule.
- **Every debatable value is a setting.** The age limit and whether the last day counts, the
  high-value figure and whether landing exactly on it counts, the complaint-type wording, the
  shortest acceptable description, and the ranking above all live with the other claim policy
  values. Several of these are numbers we invented, and an invented number that cannot be changed
  without a code change is a trap.
- **We do not check things nobody asked for.** The case being marked closed, or the parcel not
  being marked delivered, are not checks. Only four were specified, and adding a fifth would
  quietly change which claims get through.

**When things go wrong** — ShipBob being unreachable stops the claim with an upstream failure a
person sees; it never results in a silent pass. A reply we cannot read is treated the same way. A
case that does not exist is reported as not found.

**Not ready for production** — Three of these behaviours cannot be shown on the sample data:
every sample parcel is uninsured, every sample complaint is the right type, and no sample order
comes close to the high-value figure. Each is proven only by a made-up case, so the real data has
never exercised them. The age limit, the high-value figure, and the ranking are all invented
numbers awaiting ShipBob's confirmation.

**Where the code is** — `src/claim_agent/preflight/`, and
`src/claim_agent/api/routes/preflight.py`.

---

### Closing a claim we cannot process

**What it does** — When the checks stop a claim, this writes up why, in two forms: a summary for
the representative, and a draft email to the merchant listing every reason the claim was
declined.

**Why we need it** — A claim that cannot be processed is not simply dropped. The merchant is owed
an explanation, and every explanation is an email, and every email needs a person's approval
before it goes out (FR-0.4). So a stopped claim skips the AI entirely but still arrives on a
representative's desk as something to read and approve.

**How it works**

1. Take the verdict, the reasons, and all four check results.
2. Turn each failed check into one plain sentence a representative can read.
3. Write the email. The subject comes from the highest-ranked reason. The body explains every
   reason the claim was declined, in that same ranking, with the actual numbers in it — the
   delivery date, the day count, the limit, or exactly which pieces of information were missing.
4. Hand over the summary, the email, and the facts already worked out, marked as needing a
   person's approval.

**What it connects to** — It reads the verdict and check results from the pre-flight checks and
produces the report a representative reviews. Nothing sends the email; sending is a later stage
and only happens after approval.

**Choices we made**

- **No AI anywhere in this.** The whole point of stopping early is that a claim we cannot process
  costs almost nothing. Asking a model to write the email would throw that away, and the
  explanations are fixed text with the facts filled in — there is nothing to reason about.
- **The email lists every reason, not just the main one.** A merchant told only "too old" who
  fixes nothing and re-files has been failed by the explanation.
- **The email never says "draft" in its text.** A representative needs to read the exact words
  that would be sent. The fact that it is a draft is recorded alongside the email, not inside it,
  so a marker cannot be sent to a merchant by accident.
- **The report shows the checks that passed too.** A representative can see that the insurance
  check ran and passed, rather than having to infer it from silence.
- **The report never mentions money.** Nothing at this stage recommends an amount.
- **Month names are written out by hand.** The usual way of formatting a date changes language
  depending on how the machine running it is configured, which would mean the same claim
  producing a different email on a different computer.
- **A case with no contact address still gets an email written.** The reasons still reach the
  representative; only the recipient is blank, and the later sending stage refuses to send
  without one.

**When things go wrong** — There is nothing here to fail: no network, no model, no database. It
works from facts already in hand.

**Not ready for production** — This is a report shaped for stopped claims only. The full report
that the AI stages will produce is a later requirement with its own rules, and this is not it —
it will need to be reconciled with that shape rather than extended into it. The email wording has
not been reviewed by anyone who writes to merchants for a living.

**Where the code is** — `src/claim_agent/preflight/report.py`,
`src/claim_agent/preflight/email.py`.

---

## Future production

This project is an interview exercise. It is not complete and it is not production-hardened,
and it does not need to be. What matters is that the gaps are **known** rather than missed, so
this section keeps an honest list of them.

Three kinds of entry: things we did not build, things that could break under real use, and
things worth improving later. Add to it the moment you cut a corner or spot a risk — writing it
down is what separates a known limitation from a bug someone finds in production.

### Not implemented

- **All four stages of the claim pipeline.** The pre-flight checks, the triage that splits a
  claim into products, the per-product investigation, the report, the revision loop, and the
  post-approval sending are all still empty. Only the foundation exists.
- **Anywhere to store anything.** Reports, their versions, rep feedback, merchant history, and
  the audit trail have no home yet, and no storage technology has been chosen. Several
  requirements depend on remembering things across cases, so this blocks more than it looks.
- **Any connection to ShipBob.** Nothing calls the ShipBob system yet. The full description of
  its endpoints (`shipbob-mock-api.md`) is also absent from this repository, so some payload
  shapes are unknown.
- **Any access control.** The service has no authentication, no authorisation, and no notion of
  which rep is acting. In production this decides real payments, so it cannot ship without one.

### Could break

- **The claim thresholds are guesses.** Only the $100 cap is a real ShipBob figure. If the age
  limit or the high-value threshold is wrong, the system will confidently reject claims it
  should accept, or accept ones it should not. They need confirming before anyone relies on
  them.
- **The same claim could get two different answers.** The requirements demand that an identical
  claim always produces an identical report, but AI models can word things differently between
  runs. Any part of the report that comes from the model, rather than from fixed arithmetic,
  is a place where that promise can quietly fail. It needs testing by running the same claim
  repeatedly, not by assuming.
- **A slow or unavailable ShipBob system.** There is no retry, no back-off, and no circuit
  breaker. As written, one timeout would fail a claim outright and leave the rep with an error
  and no way to resume.
- **Sending twice.** A double-click, a refresh, or a retry after a network blip must not send a
  second email or pay a merchant twice. Preventing that needs a stored record of what has
  already been sent — which does not exist yet, because storage does not.
- **Losing work on restart.** Until reports are stored somewhere durable, anything held only in
  memory disappears when the service restarts, and a second copy of the service would not see
  the first one's work.
- **Cost.** Reading images is the expensive operation. Without a cache keyed to each attachment,
  a re-run or a revision could pay to look at the same photo repeatedly.

### Would improve

- **A readiness check as well as a liveness check.** The current health check only says the
  process is alive. It does not say whether ShipBob or the model is reachable, which is what a
  deployment system actually needs to know before sending traffic.
- **Metrics and tracing.** Logs are structured, but there is no measurement of how long a claim
  takes, how often the agent escalates, or what a case costs to investigate. Those numbers are
  how you would know the system is working.
- **A minimum test coverage bar in CI.** Coverage is measured and reported but nothing fails
  when it drops. Worth turning on once there is real code to cover.
- **Dependency vulnerability scanning**, and testing against more than one Python version.
- **A container image and a deployment path.** There is currently no defined way to run this
  anywhere but a developer's laptop.
