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

**Stage 1, the quick checks, is built and working.** A claim can be screened over the web today:
the system reads the case, the parcel and the order from ShipBob, remembers what a
representative has corrected for that merchant before, runs the four checks, and answers either
*carry on* or *stop, and here is why* — with, in the second case, a write-up for a
representative and a draft email to the merchant listing every reason.

**There is a screen to see it on.** A web page offers the sample claims, and lays the answer out
as a conversation: what was read, what the claim is worth, each of the four checks in turn, the
decision, and — on a stopped claim — the write-up and the draft email, which can be reworded on
the spot. It is a demonstration: anyone who opens it can screen any claim, and it decides nothing
itself. It has a send button, and that button reaches nothing — no email leaves the browser,
because the stage that would send one does not exist; the screen says so when it is pressed.
Alongside it there is a stand-in for ShipBob, so the whole thing can be run on a laptop without
being connected to anything.

**The rules can be changed from that screen too.** A second page lists every threshold the checks
judge by — how old a claim may be, what counts as a high-value order, how the reasons for turning a
claim away are explained to them — and lets someone change one and watch the next claim be
screened by the new
number, with no restart. Nothing about a change is stored: a restart puts every value back to what
the machine's own settings say.

Nothing is stored. The answer exists only in the reply, so a representative cannot fetch a
screening again, and there is no lasting record of one. Closing the page loses what it showed.

**Stages 2 to 4 are untouched.** Nothing reads photographs, nothing splits a claim into separate
products, no AI is involved anywhere yet, and nothing has ever been sent to a merchant or paid
out. The parts of the system that could do those things do not exist.

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
- **"There is no such parcel" and "we could not reach ShipBob" are kept strictly apart.** This is
  the most important rule in this part of the system. The first is a fact about the claim, and
  the claim goes on to be screened and the merchant told what was missing. The second is a fact
  about today, and it stops the screen with an error a person sees. If the two were treated
  alike, a passing outage would close a perfectly good claim and send its merchant an email
  saying their claim was missing information — an email nobody can take back, caused by nothing
  worse than a timeout.

**When things go wrong** — A case that does not exist is reported as not found. A parcel or an
order that does not exist is not an error: the claim simply lacks something, and the checks below
decide what that means. Anything else — ShipBob being down, slow, or answering with something we
cannot read — is reported as an upstream failure. The full detail goes to the logs; the caller
gets a plain message with nothing internal in it.

**Not ready for production** — We work from the example payloads quoted in the requirements,
because the full description of ShipBob's endpoints is not in this repository. If the real
replies differ, our reading of them is wrong. There is no circuit breaker: if ShipBob is down,
every claim keeps trying and keeps failing.

**Where the code is** — `src/claim_agent/shipbob/client.py`,
`src/claim_agent/preflight/gather.py`, `src/claim_agent/domain/models.py`.

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
- **If the notes cannot be read at all, we stop the claim rather than screen it without them.**
  This is deliberate, and it costs us something: by the time the notes are read, the four checks
  have already run, so we could usually give an answer anyway. We do not, because the alternative
  is worse. Screening on regardless would hand the next stage an empty list of notes, and nothing
  further down could tell that apart from a merchant with a genuinely clean record — so the
  system would quietly repeat the very correction a representative had already made. Failing
  outright keeps "empty" meaning one thing only. The price is that a problem with our own disk
  blocks claims whose answer was already worked out, and somebody has to fix the disk.

**When things go wrong** — A missing database file is created on first use. A claim whose case
has no merchant identifier gets no notes and carries on; it is not treated as a failure. A
database that cannot be read stops the claim with its own distinct message, deliberately not the
one used when ShipBob is unavailable: telling somebody an outside system is down when the problem
is our own disk wastes the first hour of finding out what went wrong.

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
- **When several checks fail, the merchant is told about every one of them, in a set order.**
  Insurance first, then age, then wrong type, then missing information. Each reason gets its own
  paragraph whichever position it lands in, so the order decides emphasis and nothing else: which
  paragraph is read first, and which reason goes in the subject line. Insurance leads because it
  is the one reason that points a merchant somewhere else entirely — an insured shipment is
  settled through its insurance — and missing information comes last because inviting someone to
  send photographs reads oddly above a paragraph saying the claim is too old to process whatever
  arrives. The order is a judgement call and a setting, not a fixed rule. Whether the claim is
  stopped does not depend on it at all.
- **Every debatable value is a setting.** The age limit and whether the last day counts, the
  high-value figure and whether landing exactly on it counts, the complaint-type wording, the
  shortest acceptable description, and the email order above all live with the other claim policy
  values. Several of these are numbers we invented, and an invented number that cannot be changed
  without a code change is a trap.
- **We do not check things nobody asked for.** The case being marked closed, or the parcel not
  being marked delivered, are not checks. Only four were specified, and adding a fifth would
  quietly change which claims get through.

**When things go wrong** — ShipBob being unreachable stops the claim with an upstream failure a
person sees; it never results in a silent pass. A reply we cannot read is treated the same way. A
case that does not exist is reported as not found. A database we cannot read stops the claim too,
with its own separate message.

Be clear about what "stops the claim" means today: the request fails and the person who asked
gets an error. Nothing is written down, so there is nothing to come back to and no way to pick
the claim up again once whatever broke is fixed — it has to be asked for from the start. Each
read of ShipBob is tried three times before giving up, but that budget is per read, not per
claim, and there is nothing that notices ShipBob is having a bad morning and stops trying. No
claim is ever silently passed or silently closed, which is the part that matters; but a
representative is left with an error rather than something they can act on. A real fallback means
keeping a record of the attempt, and nothing is kept yet.

**Not ready for production** — Three of these behaviours cannot be shown on the sample data:
every sample parcel is uninsured, every sample complaint is the right type, and no sample order
comes close to the high-value figure. Each is proven only by a made-up case, so the real data has
never exercised them. The age limit, the high-value figure, and the email order are all invented
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
3. Write the email. The subject names the first of the reasons. The body explains every reason
   the claim was declined, in that same order, with the actual numbers in it — the
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

### A stand-in for ShipBob

**What it does** — Serves the sample claim records — the case, the parcel and the order — from a
small program on this machine, so the system has something to read when nobody is connected to
the real ShipBob.

**Why we need it** — The system reads its three records over the network from ShipBob. In a test
those reads are intercepted before they leave the process, which is why the test suite has never
needed a server. But a person clicking through the screen is not a test: the reads are real, and
without something answering them every claim fails as "ShipBob could not be reached". There was
no way to see the system work outside a test run.

**How it works**

1. It listens on a port of its own and answers the same three addresses the real ShipBob does:
   one for a case, one for a parcel, one for an order.
2. It looks the requested id up among the sample records. If it has one, it returns it exactly as
   ShipBob would. If it does not, it answers "no such record", which is what makes a claim for a
   case that does not exist behave correctly rather than merely fail.
3. It can be asked to hold every answer back for a moment, which is how the slow-and-unreachable
   behaviour can be seen on purpose rather than only when something genuinely breaks.

**What it connects to** — The system is pointed at it with a single setting, the address it reads
ShipBob from. Nothing in the system knows or cares that it is a stand-in.

**Choices we made**

- **It serves the very same records the tests use, rather than its own copy.** Two sets of sample
  data drift apart, and then the screen shows one thing and the tests prove another. There is one
  definition of what CASE-1001 looks like and both read it.
- **Those records are ShipBob's own, not our approximation of them.** All five claims, their
  parcels and their orders were copied from ShipBob's published collection and then checked back
  against it field by field, cents included. An earlier version filled the gaps with invented
  parcels, invented orders and a merchant that does not exist, which meant a test could pass
  against a shape ShipBob never sends.
- **It is not part of the system.** It sits outside the application's own code and nothing in the
  application can reach it. It cannot be started by accident in production, because production
  never runs it.
- **A missing record is answered properly, not by falling over.** Being able to demonstrate a
  claim for a case that does not exist matters as much as demonstrating one that does.

**When things go wrong** — Stopping it is the point: with it stopped, the system reports that
ShipBob is unreachable, which is exactly the failure a representative would see in a real outage.

**Not ready for production** — It is a development tool and nothing more. It holds nine claims,
has no security of any kind, and does not implement the parts of ShipBob's API this system does
not read. It must never be reachable from anywhere real.

**Where the code is** — `tools/shipbob_mock.py`, reading `tests/fixtures/shipbob.py`.

Note that the past-corrections part of the screening has nothing to show on a fresh machine.
Nothing in the system writes a correction yet — the part that captures a representative's edits
has not been built — so every claim reports none on file. That is the honest answer, and it is
what the screen displays.

That makes the feature impossible to demonstrate, so there is a small tool that writes one
correction by hand. It exists because the alternative is worse: somebody showing the system
would otherwise be tempted to fake the panel on screen, where nobody could tell. Everything
that tool writes is invented, it says so plainly, it writes through the same store the service
reads, and it can take the row back out again. **A correction on screen therefore means one of
two things — a representative made it, or somebody ran that tool.** Today it can only be the
second, and it will stay that way until the stage that captures a representative's edits is
built. Whoever is driving a demonstration should say which they are showing.

---

### The screen a representative uses

**What it does** — Puts a web page in front of the quick checks, laid out as a conversation. A
representative picks one of the sample claims from a row of buttons. The findings then arrive one
at a time, the way a person would tell you them: here is what I read, here is what the claim is
worth, here is the first check, the second, the third, the fourth, here is the decision. When the
claim is stopped, the last thing to arrive is the email to the merchant, which the representative
can edit on the spot and send.

**Why we need it** — Two reasons, and the second is the one that changed the screen.

Everything the system works out used to be reachable only by sending a hand-written request and
reading raw data back. Fine for proving the rules are right, useless for showing anyone what the
system does. That is why there is a screen at all.

But the first screen showed the answer as one wall of panels that appeared together. The system
does not work that way — it works through a claim in stages, and each stage produces something —
and a wall of panels hides exactly the thing that is interesting about it. Laying the findings
out one after another shows the shape of the work, and it makes each finding readable on its own
instead of competing with five others for attention.

**How it works**

1. The representative picks a claim. Whatever the last claim left on screen is cleared — one
   claim at a time, so there is never a doubt about which claim a finding belongs to.
2. The page asks the system to screen it and says it is working. **Nothing else appears until the
   whole answer has come back.**
3. Once it has, the page has everything, and it plays the findings out in order. Each one
   appears busy first — its heading, with something turning where its answer will be — and then
   settles into what was found. The order is the order the system does the work in, not an order
   of ours.
4. Every check is shown, passed or failed, each one its own finding. A check turns for a moment
   and then the turning is replaced by a tick or a cross in the same place, so the answer lands
   where the eye is already looking. Each one opens up to reveal the values it looked at.
5. On a stopped claim, the last finding is the drafted email. The representative can change the
   subject and the wording, and press send.
6. On a claim that passes, there is no email, because the system only writes one to explain a
   stop. The page says so, and says the stage that would investigate the claim does not exist yet.
7. If the claim cannot be screened, the page says which of the four things went wrong and offers
   to try again. No findings appear at all.

**What it connects to** — It reads from the one screening address the system already offers and
writes nothing anywhere. It holds nothing between claims and nothing between visits.

**Choices we made**

- **The pacing is a replay, not a race.** This is the important one. The obvious way to build
  this is to start playing the findings out while the request is still in flight — and then the
  page can say "read the parcel ✓" for a read that has not finished, or worse, for one that
  failed a moment later. So the page waits for the whole answer first, and only then plays back
  what actually happened. Every finding on screen is a finding the system really produced.
  A claim that fails shows a failure and no findings whatsoever.
- **The rhythm is the page's own, and it measures nothing.** The pauses, and the turning before
  each finding, exist so a reader can follow one finding before the next arrives. They are not
  how long any step took — the screening had already finished before the first message appeared.
  This is the one place the screen deliberately shows something that is not so, and it is worth
  being blunt about: a check that appears to be thinking has already been decided. We chose it
  because a page that fills in silently does not show that the system works in stages, and
  showing that is most of the point of the screen. Anyone driving a demonstration should know
  the rhythm is a reading aid rather than a measurement.
- **Sending is a simulation.** There is a send button, and pressing it changes nothing outside
  the browser: no address is contacted, no record is written, and there is no address in the
  system behind the button to call. The stage that would really send an email does not exist.
  Because a button that looks like it sends is a dangerous thing to leave unexplained, the page
  says plainly, after sending, that nothing was sent.
- **A missing recipient stops the send.** A claim with no contact address on it produces an email
  with nobody to send it to, and the button is unavailable rather than merely unwise. That is the
  rule the real sending stage will have to follow, so the screen follows it now.
- **The page decides nothing.** It never works out a verdict, judges a check, or re-orders the
  reasons. The order the reasons arrive in matters — the first names the merchant email's
  subject line — so
  they are printed as given and never sorted. Turning one answer into a list of findings is
  arranging, not deciding: the page chooses what order to *show* things in, and nothing else.
- **No arithmetic on money.** The value of an order is worked out once, by the rules, and sent as
  text. The page prints that text. Multiplying a price by a quantity on screen is the habit that
  ends with a payment built on a rounding error, so the page shows both and stops there.
- **The page says as little as it can.** Almost every sentence on it came from the system. The
  page adds labels, not commentary. There are exactly two places it speaks for itself, both
  because the system has no way to say the thing for it: that nothing was really sent, and that
  the investigation stage a passing claim would go to does not exist. Both are marked on screen
  as the page's own words rather than the system's.
- **The draft email is marked as a draft.** The email's own words never say so, deliberately, so
  that a marker can never reach a merchant — which leaves the screen as the only place that state
  is visible.
- **Nothing on the page is invented.** It shows what the screening returned and nothing else. A
  merchant with no past corrections shows an empty list, because that is what the system knows —
  writing sample history into the store to make the panel look fuller would put fabricated
  content on screen that a reader could not tell from the real thing. The system's own words are
  reshaped to read rather than restated: the page shows "Claim too old" where the rules say
  `claim_too_old`, and never a phrase of its own choosing.
- **There is no way to skip the pacing, except one.** A machine set to reduce movement is given
  the whole conversation at once, with nothing turning and no timer started — somebody who finds
  movement uncomfortable should not have to sit through it. There used to be a button that did
  the same thing on request, and it was taken out: watching the work arrive is what the screen is
  for, and a button offering to not do that undercut it. The cost is real, though — a stopped
  claim takes about thirteen seconds to play out, and there is now nothing to press if you have
  seen it before.
- **The typing box is gone.** It was there to reach a claim the sample buttons did not list, and
  the stand-in for ShipBob only serves the nine that are listed, so it could only ever produce
  the "no such claim" answer. The buttons carry ids and nothing else, still: saying what each one
  demonstrates would be the page asserting an outcome it does not decide.
- **The ShipBob look is taken from the real logo.** The two brand colours are sampled from the
  artwork and the box mark's outline is traced from it. The wordmark is set in the page's own
  typeface, which is not the one ShipBob uses.

**When things go wrong** — Four failures are handled separately because they need different
things from the reader: a case that does not exist is a typo, ShipBob being unreachable is a
wait, the system not answering usually means it is not running, and anything else is kept apart
rather than guessed at. In every case the conversation shows the failure and no findings, so
there is never a half-told story on screen.

**Not ready for production** — One screen, showing the quick checks, because that is all that
exists. It cannot approve a report, send an email anywhere real, ask for the claim to be looked
at again, or fetch back a screening. It also cannot be hurried: about thirteen seconds to play
out a stopped claim, every time, with nothing to press to skip it. An edit to an email is lost the moment another claim is
picked, and is never recorded against the merchant, so the system still learns nothing from it.
Nothing it shows is stored. It has no sign-in, no tests, and has never been tried by a
representative or with a screen reader. The wordmark is not ShipBob's typeface.

**Where the code is** — `web/`, entry point `web/src/App.tsx`.

---

### Changing the rules from a screen

**What it does** — Puts the numbers the quick checks judge by onto a screen. Someone can change
one — the age limit, say — press save, and the very next claim is screened by the new number. No
restart, and no editing a file on the machine.

**Why we need it** — Almost every threshold in this system is a placeholder we invented so the
code would run: how old a claim may be, what counts as a high-value order, how short a
description is too short. Only the $100 reimbursement cap is a real ShipBob figure. They all sit
in one file so they can be corrected without touching any logic (FR-0.7, NFR-7), but until now
correcting one meant setting an environment variable and restarting the service. That is fine for
an engineer and useless for showing someone what a different limit would do to a real claim.

**How it works**

1. When the service starts it reads the policy once — from the environment, or the built-in
   defaults — and keeps a copy of it as *the values it started with*.
2. From then on there is one place holding *the policy in force*. Every screening asks that place
   for the policy once, when the request arrives, and hands what it gets to all four checks.
3. The panel asks the service what the policy is. The answer is one entry per value: its name,
   the sentence from the policy file explaining what the value is for, what kind of thing it is
   (a whole number, an amount of money, a yes or no, some words, a ranking), what it is now, and
   what it started as.
4. Someone edits the form and saves. The panel sends back every value on it, not just the ones
   they touched.
5. The service lays what arrived over what is in force and checks the result as a whole — the
   same checking a policy gets at startup, so a number outside its allowed range or a ranking
   that leaves a reason out is refused here exactly as it would be there. If anything is wrong,
   **nothing changes at all**, and the panel is told which values were rejected and why, value by
   value.
6. If everything is good, the finished policy replaces the one in force in a single step, and the
   moment is recorded. Claims already halfway through screening finish on the values they
   started with; every claim after that point uses the new ones.
7. Reset puts back the values the service started with, as though nobody had touched it.

**What it connects to** — It reads the same policy file the checks read, and writes nothing
anywhere: not to the database, not to disk. The screening reads the policy in force through the
same one place the panel writes to, which is what makes a change take effect immediately.

**Choices we made**

- **Every value travels as text**, numbers included. An amount of money must never become a
  browser number, or a cap of $100.00 comes back as 100.00000000000001; sending whole numbers and
  fractions the same way means the screen has one rule to follow instead of two, and the service
  is the only thing that ever reads a number out of what was typed.
- **The panel is drawn from the policy file**, not from a list of its own. Every label and every
  explanation on screen comes out of the file the values live in, so the two cannot drift apart
  and a value added to the file later appears on the panel without anyone touching the screen.
- **The policy is swapped whole, never edited value by value.** A claim judged half by the old
  age limit and half by the new one would be unexplainable afterwards, and that is exactly what
  editing in place invites.
- **Nothing is stored.** A restart puts every value back to what the environment says. That is
  deliberate for a demonstration, and it is a trap in anything longer-lived: a change made this
  morning is silently gone after a restart this afternoon.
- **No sign-in.** Anyone who can reach the screen can change what every claim is judged by. The
  rest of this demo has no sign-in either, and adding one here alone would be a false comfort.
- **The email order is reordered with buttons, not by dragging.** Up and down buttons work with a
  keyboard, need no library, and cannot half-drop a reason somewhere unexpected.
- **One sentence on the panel is ours**, the one saying a change is lost on restart. It sits with
  the screen's other two invented sentences, in the single file that holds them, and is marked out
  on screen as the screen's words rather than the system's. Everything else on the panel is either
  a label or the system's own wording: the explanation under each threshold is the sentence written
  beside that threshold in the code, "PROVISIONAL" and all.

**When things go wrong** — A value the service will not accept leaves the policy exactly as it
was: the panel shows the service's own complaint under each value it rejected, and the form still
holds what was typed so it can be corrected rather than typed again. An order that lists a
reason twice, or leaves one out, is refused by the same rule that has always refused it, because
a claim could otherwise fail a check whose reason has nowhere to sit. If the service is not
answering at all, the panel says so instead of showing a policy that might not be the real one.

**Not ready for production** — No sign-in, so no idea who made a change. No record of what was
changed, by whom, or when, beyond a line in the log and the time the last change landed. Nothing
is stored, so a restart loses it. No confirmation step before a change that affects every claim
that follows. And it holds for one running copy of the service only: a second copy would carry on
judging claims by its own values, which is the sort of split-brain that is very hard to see from
either screen.

**Where the code is** — `src/claim_agent/live_policy.py` holds the policy in force,
`src/claim_agent/admin/` turns it into what a panel needs and back again,
`src/claim_agent/api/routes/admin.py` is the way in, and the screen is
`web/src/screens/PolicyScreen.tsx`.

---

## Future production

This project is an interview exercise. It is not complete and it is not production-hardened,
and it does not need to be. What matters is that the gaps are **known** rather than missed, so
this section keeps an honest list of them.

Four kinds of entry: things we did not build, things that could break under real use, things
worth improving later, and questions only ShipBob can answer. Add to it the moment you cut a
corner or spot a risk — writing it down is what separates a known limitation from a bug someone
finds in production.

### Not implemented

- **Any test at all for the screen.** The Python side has 224 tests; the web page has none, and
  it is not covered by the checks that run before every push either. Both were deliberate — it is
  a demonstration, and keeping it out of the push loop keeps that loop fast — but it means a
  change to the screen is only as safe as the person making it. It has also never been tried by a
  representative, on a phone, or with a screen reader.
- **Any way for the screen to reach the system other than in development.** The development
  server forwards requests to the system on the page's behalf, which is what avoids opening an
  unauthenticated service up to any web page anywhere. A built page served from a real address
  has no such helper, and nothing has been decided about what it would use instead.
- **Anything on the screen beyond the quick checks.** It shows what has been built, which is one
  stage of four. Approving a report, sending an email back with feedback, seeing a claim's
  separate products — all of those are later requirements with nothing behind them yet. The
  wording of an email *can* be edited, but only on screen: see the two entries below.
- **Any real sending.** The send button is a simulation. Nothing is contacted, nothing is
  recorded, and there is no address in the system behind it — the whole of stage 4 is empty. The
  screen says outright that nothing was sent, which is the only thing making that safe. Whoever
  builds the real sending stage should replace the simulation rather than wire something up
  behind it, because the real one owes several things this one does not: refusing to send twice,
  checking what is being sent against what was approved, and keeping a record of it.
- **Any record of an edited email.** A representative can reword a draft, and the rewording is
  gone the moment another claim is picked. Nothing keeps it, and nothing learns from it — so the
  requirement that a representative's corrections improve the next claim from that merchant is
  still entirely unmet, even though the screen now has the edit that would feed it.

- **Stages 2, 3 and 4 of the claim pipeline.** The triage that splits a claim into products, the
  per-product investigation, the report the AI produces, the revision loop, and the post-approval
  sending are all still empty. Only the quick checks exist.
- **Anywhere to keep a screening.** The answer exists only in the reply to the request that asked
  for it. A representative cannot fetch it again, nothing records what was decided or when, and a
  restart loses everything — which also means there is no ordered history of a claim, something
  the requirements ask for outright.
- **Nothing writes down a representative's corrections.** Merchant memory can be read and can be
  written, and the screen reads it, but no part of the system puts anything in it yet, because
  the part that would is in a later stage. In practice the system does not yet learn between
  claims — the machinery is there and the input is not. Editing an email on screen does not
  count: that edit is discarded when the next claim is picked and never reaches the store. The
  only thing that writes a correction today is a development tool run by hand, which is a way to
  demonstrate the reading half, not a way for the system to learn.
- **Any access control.** Anyone who can reach the service can screen any case id and read back
  the merchant's name, contact address, their description of what happened, and what the order
  was worth. There is no sign-in, no notion of which representative is acting, and no limit on
  how fast someone can ask.
- **Any way to tell one duplicate request from another.** Two identical screening requests do the
  work twice. Harmless while nothing is stored and nothing is sent; not harmless later.
- **No sign-in to ShipBob.** The mock needs no credentials, so we send none. The real system
  would.
- **Nobody who writes to merchants has read the emails.** The wording, the tone, and the sign-off
  are all our invention. They should be reviewed by whoever owns customer communications before a
  single one is sent.
- **Only the three reads the checks need.** There is no way to fetch attachments, generate an
  invoice, send an email or pay anyone — deliberately, so the cheap stage cannot become expensive
  by accident, but it does mean later stages start by adding to it.

- **Any sign-in on the policy panel.** Anyone who can reach it can change the numbers every claim
  after them is judged by, and nothing records who did. That is the access-control gap above with
  sharper consequences: reading a claim exposes a merchant's details, whereas changing the age
  limit changes outcomes.
- **Anywhere to keep a policy change.** A changed threshold lives in the running process and
  nowhere else. There is no history of what the policy was on a given day, no note of who changed
  it or why, and a restart silently puts every value back to what the environment says.

### Could break

- **The stand-in for ShipBob is not ShipBob.** It serves nine claims from the same sample records
  the tests use. Anything the real API does that those records do not show — a field with an
  unexpected shape, an error we have not seen, a slow response — is not being exercised by
  clicking through the screen, and a demo that works proves less than it appears to.
- **The screen shows money exactly as the system sends it, and pads nothing else.** That is
  deliberate, and it means a figure arriving in an unexpected shape would appear on screen in
  that shape rather than being quietly tidied up. Tidying it up in the browser is the thing this
  project most wants to avoid, so the trade was made knowingly.
- **The rhythm of the conversation is invented, and now looks convincingly like it is not.**
  Each finding turns before it settles, which reads as a step being worked on. It is not: the
  screening finished before the first message appeared, and every pause is a fixed length the
  screen chose. Somebody watching could reasonably conclude that the checks take about a second
  each, that the parcel was slow to read, or that a spinning check is still undecided — and be
  wrong on all three. The findings themselves are never invented, because the screen waits for
  the whole answer before it starts; only the timing is. This is the largest gap between what
  this screen shows and what the system does, and the only defence against it is that it is
  written down here and in the design notes beside the code. It would go away entirely if the
  service reported its stages as it went — see **Would improve**.
- **Only the conversation holds a screening.** It was true before that nothing was stored, and it
  bites harder now: picking a second claim throws the first conversation away without asking, and
  takes any rewording of its email with it. There is no way back to it.

- **Four made-up claims sit alongside the five real ones.** ShipBob's own five claims, their
  parcels and their orders are now exactly what ShipBob serves, checked record by record against
  the published collection. The four we constructed are still ours, top to bottom, and exist only
  because three of the quick checks cannot be shown on ShipBob's data at all. Every identifier we
  invented starts with a 9, so the two can be told apart at a glance, but that is a convention
  rather than a guarantee.
- **Three behaviours have never run against real data.** No sample parcel is insured, no sample
  complaint is the wrong type, and no sample order comes near the high-value figure. All three
  are proven only by cases we constructed. If the real system words any of them differently, we
  would turn away claims we should accept and never know.
- **The claim thresholds are guesses.** Only the $100 cap is a real ShipBob figure. The age limit,
  whether the last day counts, the high-value figure, the shortest acceptable description, and
  the order the reasons appear in the merchant's email are all placeholders. They can be changed
  without touching
  code, which is not the same as being right.
- **One stopped claim, several reasons, one label.** "Missing information" covers three different
  problems: a detail absent from the claim, a record ShipBob could not give us, and no delivery
  date on either record. A merchant can therefore be asked to send something they cannot send,
  because the real problem was never theirs. A separate reason for "we could not assess this"
  would be more honest.
- **The checks and the merchant email are joined by plain text.** The email lifts values out of
  what each check recorded, by name. Rename one and the email quietly degrades to a vaguer
  sentence rather than failing a test. Worse, the wording the check uses for a missing item lands
  word for word in front of a merchant, and nothing in the checks guards that.
- **Two delivery dates that disagree are recorded and then ignored.** We use the claim's own date
  and note the disagreement. If the two were months apart, the claim's age would be decided on one
  of them with nobody looking. There is no ShipBob rule for this.
- **A claim filed before it was delivered passes.** That is impossible and does happen in real
  data. It passes the age check with a sentence, when it should probably reach a person.
- **A slow or unavailable ShipBob.** Each read is tried up to three times, but the budget is per
  read, not per claim: three reads against a hanging system can take about a minute and a half
  before anyone is told. There is no circuit breaker, so during an outage every claim pays the
  full wait before failing. A "too many requests" reply is not retried at all and the system
  ignores how long it was asked to wait.
- **Every client retries in step.** We deliberately left the pauses between attempts fixed so that
  a run is repeatable. Under real load that means many clients coming back at the same instant and
  hitting a struggling system together.
- **The database is one file on one machine.** A second copy of the service has a different memory
  and neither knows about the other. Nothing is backed up. Two writers at once wait five seconds
  and then fail the claim. And there is no way to change the shape of the stored data later: the
  table is only created if absent, so a future change would silently do nothing.
- **Reading merchant memory blocks everything else.** The database is read in the middle of
  handling a request, so under load every screening queues behind the same file. Fine for a local
  file; not fine for a real one.
- **A database we cannot read stops every claim, including ones already decided.** This is a
  chosen trade rather than an oversight — the reasoning is in [Remembering a
  merchant](#remembering-a-merchant) — but the consequence is worth being clear about: a single
  corrupt file on one machine halts screening entirely, and there is no degraded mode to fall
  back to. It is one more thing that a store not living on one local disk would fix.
- **Every price is assumed to be in dollars.** Nothing in ShipBob's data says what currency an
  order is in, so we add the numbers up and call the total dollars. A non-dollar order would be
  compared against a dollar threshold and nobody would notice.
- **Nothing limits how much a merchant's history can grow.** Corrections are never trimmed,
  de-duplicated or capped, and the whole list is handed to the AI as context in a later stage. A
  long-standing merchant could eventually swamp it.
- **Connections are opened by building the service, not by starting it.** Anything that builds a
  service and never runs it — every test does — leaves a connection pool open. Harmless in a
  short-lived process; it would accumulate in a long-lived one that rebuilt services.

- **The same claim can now be screened twice and answer differently.** The quick checks are still
  fixed rules, but the policy they judge against is an input, and that input can be changed from a
  screen between two runs. Each check does record the limit it used, so a single answer can still
  be explained on its own; what is missing is any stamp saying which policy produced it, and any
  way to ask what the policy was once the process has moved on.
- **One running copy of the service only.** The policy in force is held in memory in one process.
  Run two copies behind a load balancer and a change reaches whichever one answered the request:
  the two then judge claims by different numbers, and neither screen shows anything wrong.

### Would improve

- **A record of every screening, and the ability to fetch one back.** This is the single biggest
  gap: it blocks an audit trail, protection against doing something twice, and a representative
  simply reopening what they were looking at yesterday.
- **A screening that reports its stages as they happen.** The screen plays the findings out one
  at a time, but the service still answers in a single reply, so the pacing is the screen's
  invention. The service works through a claim in stages already, and having it say so as it goes
  would make the conversation real rather than a replay — the reads are the slow part, and a
  representative would see which one they are waiting on. It would also give the screen something
  honest to show during a long wait instead of one unchanging line.
- **A reason of its own for "we could not assess this claim",** separate from "the merchant left
  something out", so nobody is asked for information that would not have helped.
- **A readiness check as well as a liveness check.** The current health check only says the
  process is alive, not whether it can reach ShipBob or its database — which is what a deployment
  system actually needs to know.
- **Measurements.** Nothing records how long a claim takes to screen, how often reads are retried,
  or how many claims are stopped and for which reason. Those numbers are how anyone would know
  the thresholds are wrong.
- **One vocabulary, checked.** Merchant-facing wording is now consistent, but nothing enforces it
  across the files that contribute to a single email.
- **Bounding what a representative types.** Their corrections are free text that will one day be
  put in front of an AI. Deciding now what a safe length and shape looks like is cheaper than
  discovering it later.
- **A minimum test coverage bar in CI.** Coverage is measured and reported but nothing fails when
  it drops.
- **Dependency vulnerability scanning**, and testing against more than one Python version.
- **A container image and a deployment path.** There is currently no defined way to run this
  anywhere but a developer's laptop.

### Questions for whoever owns the requirements

- **The requirements refer to "open question 2" and "open question 3" but contain no list of open
  questions.** Neither affects the quick checks, but both are cited as unresolved and nobody can
  look them up.
- **Does a claim filed exactly on the age limit still count?** We say yes. It is a coin flip.
- **What should happen when neither the claim nor the parcel records a delivery date?** We stop
  the claim and call it missing information. This is the decision we are least sure of.
- **When a claim fails several checks at once, which reason should the merchant be told first?**
  We lead with insurance, then age, then wrong type, then missing information, on the reasoning
  that a merchant with a live insurance route should hear about that first. They are told every
  reason either way — the order is about which one they read first and which one is in the
  subject line, not about which ones they hear. Nobody has confirmed that this is the right
  emphasis.
