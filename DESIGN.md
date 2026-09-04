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
decision, and — on a stopped claim — the write-up, the draft email where there is one, and an
escalation where the parcel was insured. The email can be reworded on the spot. It is a
demonstration: anyone who opens it can screen any claim, and it decides nothing itself. It has a
send button and an escalate button, and neither reaches anything — nothing leaves the browser,
because the stages that would send an email or route a claim out do not exist, though the screen
reports both as done.
Alongside it there is a stand-in for ShipBob, so the whole thing can be run on a laptop without
being connected to anything.

**The rules can be changed from that screen too.** A second page lists every threshold the checks
judge by — how old a claim may be, what counts as a high-value order, how short a description is
too short — and lets someone change one and watch the next claim be screened by the new number,
with no restart. Nothing about a change is stored: a restart puts every value back to what the
machine's own settings say.

Nothing is stored. The answer exists only in the reply, so a representative cannot fetch a
screening again, and there is no lasting record of one. Closing the page loses what it showed.

**Stages 2 and 3 are built and can be asked for.** A claim can be investigated over the web:
the system screens it, finds its photographs, works out what each one is, looks up how
comparable claims were decided, splits the claim into the products being claimed for, and
investigates each of those separately — choosing for itself which images to look at. It then
hands back, per product, what the evidence showed, what it recommends, how the amount was
arrived at, and a draft email. **It reports all of that while it happens** rather than going
quiet and answering at the end.

**The screen shows all of it.** A representative picks a claim and watches the quick checks,
then the similar past claims, then the investigation reporting each thing it does as it does
it, and finally a report per damaged product with the working behind its figure and a draft
email. Two things are worth being clear about: the AI recommends and never decides, and the
money is arithmetic rather than anything the AI produced — it is not shown a figure and has
nowhere to write one.

**Stage 4 is untouched**, and nothing has ever been sent to a merchant or paid out. The parts of
the system that could do those things do not exist.

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
- **An insured parcel is not answered at all — it is handed on.** Insured shipments are claimed
  on their insurance, through a process that is not this one, so nobody here writes to the
  merchant about it. The claim is marked for escalation and left for someone else to pick up
  (FR-0.2). This is the one reason a merchant is never told about.
- **When several checks fail, the merchant is told about every one of them, in a set order.**
  Age, then wrong type, then missing information. Each reason gets its own paragraph, so the order
  decides emphasis and nothing else: which paragraph is read first, and which reason goes in the
  subject line. Missing information comes last because inviting someone to send photographs reads
  oddly above a paragraph saying the claim is too old to process whatever arrives. Being insured
  is deliberately not in that list, because no email explains it. The order is fixed in the code
  rather than being a setting: nobody has asked to tune which reason a merchant reads first, and
  a fixed order is what keeps two screenings of the same claim identical.
- **A claim can be both.** One that is insured *and* too old produces the escalation *and* the
  email about its age, and a representative chooses which to act on. Nothing decides for them.
- **Every debatable value is a setting.** The age limit and whether the last day counts, the
  high-value figure and whether landing exactly on it counts, the complaint-type wording and the
  shortest acceptable description all live together as claim policy values. Several of them are
  numbers we invented, and an invented number that cannot be changed without a code change is a
  trap. The order the reasons are explained in is the exception: it is fixed in the code, because
  nobody has asked to tune it and a setting nobody changes is a lever to maintain for no one.
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
never exercised them. The age limit and the high-value figure are invented numbers awaiting
ShipBob's confirmation, and so is the decision that an insured claim is escalated rather than
explained to the merchant.

**Where the code is** — `src/claim_agent/preflight/`, and
`src/claim_agent/api/routes/preflight.py`.

---

### Closing a claim we cannot process

**What it does** — When the checks stop a claim, this writes up why: a summary for the
representative, and — for every reason a merchant can be told about — a draft email listing them.
An insured claim is the exception: it is marked for escalation and gets no email, because insured
shipments are claimed on their insurance somewhere else entirely.

**Why we need it** — A claim that cannot be processed is not simply dropped. The merchant is owed
an explanation, every explanation is an email, and every email needs a person's approval before it
goes out (FR-0.4). So a stopped claim skips the AI entirely but still arrives on a
representative's desk as something to read and approve.

The exception is the one thing the merchant is not owed an explanation *from us* for. FR-0.2 says
an insured shipment must be "routed out, never processed here", and routing a claim out is not the
same as closing it with an apology: whoever handles insurance claims will be the one to talk to
the merchant. Reading those two requirements together is our interpretation, not something either
of them states — see the questions at the end of this document.

**How it works**

1. Take the verdict, the reasons, and all four check results.
2. Turn each failed check into one plain sentence a representative can read.
3. Set the insurance aside. If the parcel was insured, the write-up is marked for escalation and
   that reason is taken out of everything the merchant will be shown — insured claims go to the
   insurance process, not to us, so nobody writes to a merchant about one. A claim with nothing
   else wrong with it therefore has no email at all.
4. Write the email, if there is anything left to say. The subject names the first remaining
   reason. The body explains every reason the claim was declined, in that same order, with the
   actual numbers in it — the delivery date, the day count, the limit, or exactly which pieces of
   information were missing.
5. Hand over the summary, the escalation if there is one, the email if there is one, and the facts
   already worked out — all of it marked as needing a person's approval.

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
5. On a stopped claim, the write-up is followed by whichever of two things the system produced.
   An insured parcel gives an escalation, with a button to hand the claim on — there is nothing
   to send, because no email is written about insurance. Every other reason gives the drafted
   email, whose subject and wording the representative can change before pressing send. A claim
   that is insured *and*, say, too old gives both, and they choose.
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
- **Sending is a simulation, and the page does not admit it.** There is a send button, and
  pressing it changes nothing outside the browser: no address is contacted, no record is written,
  the rewording is kept nowhere, and there is no address in the system behind the button to call.
  The stage that would really send an email does not exist. The page reports the email as sent
  anyway, and shows who it went to.

  The page used to say outright that nothing had been sent. That was removed on purpose: a
  demonstration should read as a working product rather than one apologising for itself, and a
  paragraph explaining what is not built is not what somebody watching should be reading. The
  cost is worth stating plainly, because it is the reason this paragraph exists — **there is now
  nothing on screen that tells a viewer the send was not real.** Anyone shown this will believe
  an email went to the merchant. Whoever is driving a demonstration has to say so out loud, and
  whoever builds the real sending stage needs to know that this confirmation is already making a
  promise the code does not keep.
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
  page adds labels, not commentary. There is one place it speaks for itself, because the system
  has no way to say the thing for it: that the investigation stage a passing claim would go to
  does not exist. It is marked on screen as the page's own words rather than the system's. The
  page writes one other sentence — the confirmation that an email was sent — and that is a
  different kind of thing: not an explanation but a claim, and discussed above, because it is
  not true.
- **The draft email is marked as a draft.** The email's own words never say so, deliberately, so
  that a marker can never reach a merchant — which leaves the screen as the only place that state
  is visible.
- **Nothing on the page is invented.** It shows what the screening returned and nothing else. A
  merchant with no past corrections shows an empty list, because that is what the system knows,
  and the page never adds a record of its own to make a panel look fuller. Putting history into
  the store is possible — there is a tool for it, described in
  [Remembering a merchant](#remembering-a-merchant) — but that is a decision somebody takes
  deliberately, outside the screen, and not something the screen does to flatter itself. The system's own words are
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
3. The panel asks the service what the policy is. The answer is one entry per value the panel
   is meant to change: its name, the sentence from the policy file explaining what the value is
   for, what kind of thing it is (a whole number, an amount of money, a yes or no, some words, or
   one of a set of choices), what those choices are where it has them, what it is now, and what
   it started as.

   Some values are deliberately left out, and the policy file is where that is marked. Three of
   them belong to the AI investigation, which does not exist: a control that changes something
   nothing reads would look like it was doing something. They are still policy values, still read
   by whatever reads them, and still set from the machine's own settings before the service
   starts — they simply cannot be changed from a browser. A change to one sent by hand is refused,
   so leaving it off the screen is a rule rather than a decision about controls.
4. Someone edits the form and saves. The panel sends back every value on it, not just the ones
   they touched.
5. The service lays what arrived over what is in force and checks the result as a whole — the
   same checking a policy gets at startup, so a number outside its allowed range or a value
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
- **The claim type is picked from a list, not typed.** It is the one value matched *exactly*
  against what a merchant's claim says, so a single typo in it turns every claim away at the
  claim-type check — an easy mistake to make and a confusing one to diagnose. The choices come
  from the policy file, like everything else on the panel, so the screen holds no list of claim
  types of its own.

  **There is one choice in the list, and that is deliberate.** One claim type is quoted in the
  requirements, and the document naming the rest is not in this repository. ShipBob certainly uses
  others, but we do not know what they are, and putting a guess on screen would show somebody a
  claim type nobody has confirmed exists. So the list holds the one we can point at.

  That is why the list constrains what the panel *offers* and nothing else: the value behind it is
  still ordinary text, so a real claim type missing from the list can still be set through the
  machine's own settings, which is how one would be configured before anyone gets round to adding
  it. Whatever is currently set is always among the choices for the same reason — a control unable
  to show the value in force would quietly replace it the moment somebody saved. The list should
  grow the moment someone can tell us the real claim types.
- **The policy is swapped whole, never edited value by value.** A claim judged half by the old
  age limit and half by the new one would be unexplainable afterwards, and that is exactly what
  editing in place invites.
- **Nothing is stored.** A restart puts every value back to what the environment says. That is
  deliberate for a demonstration, and it is a trap in anything longer-lived: a change made this
  morning is silently gone after a restart this afternoon.
- **No sign-in.** Anyone who can reach the screen can change what every claim is judged by. The
  rest of this demo has no sign-in either, and adding one here alone would be a false comfort.
- **Only the values worth changing on a running service.** The panel could show every value in
  the policy file, and at first it did. It now leaves out the ones nothing running reads, because
  offering someone a control that changes nothing observable is worse than not offering it: they
  would reasonably conclude the change had taken effect.
- **The panel adds no words of its own.** It once carried a sentence saying a change is lost on
  restart. That was taken out: a panel explaining its own limitations is not what somebody
  changing a threshold should be reading. The fact is unchanged — see the entry above, and
  [Future production](#future-production) — it is simply no longer said on screen, so whoever is
  driving a demonstration has to know it themselves. Everything on the panel is now either a label
  or the system's own wording: the explanation under each threshold is the sentence written beside
  that threshold in the code, "PROVISIONAL" and all.

**When things go wrong** — A value the service will not accept leaves the policy exactly as it
was: the panel shows the service's own complaint under each value it rejected, and the form still
holds what was typed so it can be corrected rather than typed again. An order that lists a
reason twice, or leaves one out, is refused by the same rule that has always refused it, because
a claim could otherwise fail a check whose reason has nowhere to sit. If the service is not
answering at all, the panel says so instead of showing a policy that might not be the real one.

**Not ready for production** — Nothing about a change is stored, and the panel no longer says so,
so somebody who changed a threshold this morning can find it quietly back to its old value after a
restart this afternoon with nothing on screen having warned them. No sign-in, so no idea who made a
change. No record of what was
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

### Splitting a claim into products

**What it does** — Works out which products a merchant is actually claiming for, and turns each
one into a separate piece of work. It also decides, once, what each uploaded photo is a photo of.

**Why we need it** — A merchant opens one complaint, but it can cover several damaged products,
and the complaint almost never names them. The descriptions say things like "1 order affected" or
"Number of affected orders: 2". Meanwhile the payment system pays for one product per request,
and a representative may well want to pay for one item and ask for more evidence about another.
So the complaint has to be split before it can be investigated (FR-1a.1, FR-1a.2).

This cannot be done by a rule. Working out which products are meant requires reading what the
merchant wrote and looking at the pictures, which is why this is the first place in the system
where an AI is involved at all.

**How it works**

1. Ask ShipBob for the list of images attached to the complaint. This is one cheap read and it is
   the first time in the whole system that attachments are touched — a claim turned away by the
   quick checks never gets this far, and so never costs anything to look at (NFR-8).
2. Look at each image once and say what it is: an invoice, a screenshot of the end customer
   confirming the damage, a photo of the outer box, or a photo of a damaged product. Also say
   whether it is clear enough to be any use, and if not, why not — too dark, too blurry, too
   cropped (FR-1.4, FR-1.5).
   Names and file types are ignored completely. They carry no signal: two files in the sample data
   have nearly identical names and are different kinds of evidence, and every attachment in every
   sample case is a PNG or a JPEG whatever it shows.
3. Three of those four kinds describe the whole parcel rather than any one product — the invoice,
   the customer's confirmation, and the outer box. They are settled here, once, and every product
   in the claim is handed the same answer (FR-1a.3). That is partly about cost, since the invoice
   is not read once per product, and mostly about consistency: two products in one claim can never
   disagree about whether the box was photographed.
4. Then decide which products are being claimed for, by weighing what the merchant wrote against
   the photos of damage and the list of items on the order. Each product identified has to be an
   item that is really on the order, and it carries that item's name, code and price with it
   (FR-1a.2). A claimed product that is not on the order cannot be paid for, and saying so is
   itself a useful finding.
5. If it cannot be established which products are meant, the claim is handed to a person with a
   note saying exactly what is unclear, and no split is guessed at (FR-1a.4). A representative
   told "the photos show a damaged 24oz bottle, but the order has two different 24oz bottles at
   different prices" settles that in seconds. A wrong split is silent and expensive.
6. One damaged product is one piece of work, through exactly the same machinery as five. There is
   no shortcut for the simple case (FR-1a.5).

**What it connects to** — It starts from what the quick checks already gathered, so it never
re-reads the complaint, the parcel or the order. It reads the attachment list from ShipBob and
looks at the images. It hands on a list of products, the settled verdict on the shared evidence,
and what was seen in each image — which is exactly what the per-product investigation needs.

**Choices we made**

- **The AI chooses what to look at.** Nothing here is a fixed sequence of steps. It is given a
  small set of things it is able to do — list the attachments, look at an image and answer a
  question about it, produce an invoice, work out an amount — and it decides which to use, in
  what order, and how many times, until it can justify an answer (FR-1.1). A complaint with no
  photos costs a few steps; one with six earns as many as it needs.
- **It can only read.** Sending an email and paying a merchant are not among the things it is
  able to do — not discouraged, not guarded by a warning in its instructions, simply absent. It
  could not take either action if it decided to (FR-1.2).
- **Every answer it gives has a fixed shape.** It never replies with a paragraph to be
  interpreted. Each answer is a form with named boxes, and a reply that does not fit the form is
  rejected rather than patched up (NFR-2).
- **Each image is looked at once per claim, not once per product.** Looking at pictures is by far
  the most expensive thing this system does, so the answer to a given question about a given image
  is remembered for the rest of the claim (NFR-8).
- **A number of steps it cannot exceed.** Every run has a budget, and running out is an answer in
  itself: the claim goes to a person, carrying whatever was established along the way, rather than
  looping or coming back empty (FR-1.3, FR-1.16).
- **Being unsure is a valid answer, and the preferred one.** Handing an ambiguous split to a
  person is treated as success, not failure. The alternative — picking the likelier of two similar
  bottles — produces a payment nobody checked.

**When things go wrong** — Every failure ends with a person, never with a decision (NFR-4). If
ShipBob will not give up the attachment list, if an image cannot be downloaded, if the AI is
unreachable or replies with something unusable, or if the step budget runs out, the claim is
escalated with whatever was learned so far attached. There is a difference the system is careful
about: an image the merchant sent that is too blurry to use is *their* problem and they can be
asked for a better one, whereas an image *we* could not fetch is *ours*, and asking the merchant
to send it again would be dishonest. The two are recorded separately and lead to different places.

**Not ready for production** — An AI reading a photograph does not give the same answer every
time, which is in direct tension with the promise that the same claim is examined the same way.
Everything around it is fixed and repeatable; the reading of the picture is not. Nothing about a
split is stored, so it cannot be looked at again afterwards. And a photograph can contain writing,
which means an image could in principle carry text aimed at the AI reading it; the damage that
could do is limited by the AI not being able to send or pay anything, but it is not eliminated.

**Where the code is** — `src/claim_agent/agent/triage.py`, with the shared machinery in
`src/claim_agent/agent/` and the shapes it produces in `src/claim_agent/domain/`.

---

### Investigating one damaged product

**What it does** — Takes one damaged product and works out what the evidence shows, whether it
looks like something ShipBob should pay for, how sure it is, and what to say to the merchant. Then
it stops.

**Why we need it** — This is the slow part of a representative's day: opening the photos, checking
the evidence is all there, deciding whether the damage is really visible, working out how much,
and writing the email. Doing it the same way every time is what makes two identical claims arrive
looking identical (FR-1b.1, NFR-1).

**How it works**

One run per product, and the runs happen at the same time as each other. Each run:

1. Receives the whole claim — everything the merchant wrote, every image, every item on the order,
   and what the other products in the same claim are — and one product it is responsible for
   (FR-1b.2). It needs the wider view to read the evidence properly, because a photo showing two
   broken items matters to both of them and the description is the only account of what happened.
   Knowing about the whole claim and answering for one part of it are different things.
2. Checks that four pieces of evidence are present and usable: proof of what was ordered and at
   what price, confirmation from the person who received the parcel, photos of the damaged product,
   and photos of the outer box. Three of those were settled once for the whole claim; the photos of
   the damaged product are this product's own business.
3. If any of the four is missing, or present but too poor to rely on, the run stops there and the
   answer is to go back to the merchant — naming the specific thing that is needed, "a photo of the
   outer shipping box", never "more information" (FR-1.6, FR-1.7). Nothing is inferred, assumed, or
   half-approved.
4. If all four are there, it answers four questions, each with its reasoning and each with how
   sure it is: is the damage actually visible; can the damaged product be identified; does that
   product appear on the invoice; and was the outer box photographed (FR-1.8–FR-1.11). The box
   needs to have been *photographed*, not to be damaged — an intact box with a broken product
   inside is a perfectly good claim.
5. It then recommends one of four things and says why: pay, ask the merchant for something, refuse,
   or hand it to a person (FR-1.14).
6. If it recommends paying, the amount is worked out by arithmetic, not by the AI. The AI says
   which items were damaged; a fixed calculation takes those items' prices from the invoice, adds
   them up, and applies the cap (FR-1.21).
7. A draft email to the merchant is written to match, with the amount filled in afterwards by the
   same calculation.

**What it connects to** — It starts from the split and the shared evidence verdict, and from the
facts the quick checks worked out — what the order was worth, whether it counts as high value, and
anything a representative has corrected for this merchant before. It produces, for each product, a
recommendation, the evidence behind it, the four answers with their reasoning, how the amount was
arrived at, and the draft email. Nothing is sent and nothing is stored.

**Choices we made**

- **The AI recommends; it does not decide.** All four outcomes are its own judgement, including
  refusing a claim. There is one narrow exception, in one direction only: where the rules say an
  approval is not available — a piece of evidence is missing, it is not sure enough, or it ran out
  of steps — the recommendation is moved to asking the merchant or handing it to a person, and what
  the AI originally said is recorded next to it. Nothing can move a recommendation *towards* paying.
- **No amount of money ever comes out of the AI.** Not as a figure it calculates, and not as words
  a figure is read out of. The forms it fills in have no box for an amount at all, so it is not
  that it is asked not to give one — there is nowhere to put it. The number in front of a
  representative is arithmetic they can check (FR-1.21).
- **The email is written by the AI, with a gap where the money goes.** The wording is the AI's, so
  it can speak to the actual claim, but every figure is put in afterwards by the calculation. Any
  amount of money found anywhere else in what it wrote is rejected.
- **How sure it is, is part of the answer.** Each of the four questions carries its own confidence,
  and so does the identification of which product was damaged, because that is the judgement the
  money rests on. Below a set level, paying is not available and the claim goes to a person with
  the doubt spelled out (FR-1.15). The figure is shown to a representative either way — a number
  someone can see is worth more than a threshold they cannot.
- **Each product is judged on its own.** A poorly evidenced product cannot drag down a
  well-evidenced one, and a strong one cannot carry a weak one (FR-1b.3). One product can be
  recommended for payment while its neighbour is waiting on a photograph.
- **A product reaches the same answer whether it was claimed alone or with five others**
  (FR-1b.4). This one is worth explaining, because it is built into the shape of the code rather
  than being asked for politely. The question "could this be one of two similar bottles?" is
  settled against *the items on the order*, which are the same no matter how the claim was split —
  never against the other products being claimed for, which are not. And the parts that decide the
  outcome and the amount are handed nothing at all about the neighbouring products, so they could
  not take them into account even by mistake.
- **Every run has its own budget.** A claim covering four products has four budgets, not one
  divided four ways, so a complicated product cannot starve a simple one (FR-1.3).
- **Nothing is presented as settled.** The result says what is recommended and why. The email is a
  draft, and is marked as one on the outside rather than in its own words, so no marker can ever
  reach a merchant (FR-1.17).

**When things go wrong** — Everything ends with a person (NFR-4). Running out of steps, an AI that
cannot be reached, a reply that does not fit its form, an image that cannot be fetched, and
ShipBob refusing to produce an invoice all lead to the same place: the claim is handed over with
whatever was established, and never to a payment or a silently dropped case. Where an invoice
cannot be produced, the claim is escalated rather than the price being taken from the order
instead — the two happen to be identical in the sample data, and quietly swapping one for the
other would put a number in front of a representative that did not come from where the report says
it came from.

**Not ready for production** — The confidence figure is the AI's own opinion of itself. We use it
to withhold payments, because there is nothing better to use, but nobody has ever checked it
against what actually turned out to be true. The same is true of the level we set it at. Nothing
is stored, so there is no lasting record of an investigation. And "the invoice" means two different
things in the requirements — the picture the merchant uploaded, and the one ShipBob generates on
request — and which of them each rule means is our reading rather than ShipBob's.

**Where the code is** — `src/claim_agent/agent/investigate.py` for one product,
`src/claim_agent/agent/run.py` for the claim as a whole, the rules with no AI in them in
`src/claim_agent/domain/`, and the way in at `src/claim_agent/api/routes/investigate.py`.

---

### Remembering how similar claims were handled

**What it does** — Writes down every damaged product the system investigates, and when a new
one arrives, finds the past ones most like it and puts them in front of the AI before it starts
work.

**Why we need it** — The rest of the system makes each claim *internally* consistent: same
rules, same investigation, same report. None of it can make today's claim agree with a
materially identical claim handled three weeks ago, because nothing remembered that claim. This
is that memory (FR-S.1 to FR-S.14).

It is not the same as [remembering a merchant](#remembering-a-merchant). That answers "what has
*this merchant* been told before?" and is looked up by account number. This answers "how has a
claim *like this one* been handled?" and is looked up by what happened, across every merchant.
A claim can have both, one, or neither.

**How it works**

1. **Capture, but only at the end.** When a representative has decided a product and that
   decision has taken effect, the system writes down what the merchant said happened, which
   product it was, which of the four pieces of evidence were there and what each judgement
   concluded, what the claim closed on, and what was paid. One record per damaged product, named
   after that product's claim line, so closing the same line again replaces the record rather
   than adding a second one.
2. **Nothing still in review is kept.** A claim nobody has decided has no outcome — the system
   suggested something and no person has agreed or disagreed. Being in the store therefore means
   a person settled it, which is why no record needs weighing against another.
3. **Retrieve.** Before the AI investigates a product, the system looks for the past products
   most like it. It compares four things: the words the merchant used, the words in the product
   name, which pieces of evidence were present and missing, and whether the damaged product
   could be tied to a line on the order.
4. **Score and cut.** Each candidate gets a score between nothing and one. Anything below the
   threshold is dropped, and only a handful of the best are kept. Both numbers are policy values
   an operator can change.
5. **Show the AI.** The kept records go into the question the AI is asked, each with what it
   closed on and why it was judged similar. The rules for how to treat them are in the fixed
   wording the AI always gets.

**Where the lookup happens.** Once the claim has been split into products, and before any
product is investigated, the system looks each product up in turn and hands the result to that
product's run. It is done in one pass, before the runs fan out, for two reasons: reading the
store blocks, and doing it inside runs that are meant to happen at once would hold the others
up; and every run then starts with its precedent already in hand rather than having to ask for
it. The AI has no way to search the store — if it did, two runs of the same claim could differ
purely in whether it thought to look, which is the very inconsistency this is meant to remove.

**Why the records go in the claim's own question rather than the standing instructions.** The
rules for weighing precedent are fixed and belong with the other standing instructions, so that
is where they live. The records themselves belong with the claim, beside the merchant's
description and the order — they change with every claim, and the standing instructions are also
sent when the system asks what a single photograph shows, where past claims are irrelevant and
would be paid for on every image.

**Finding the candidates.** The database can search text on its own, so the system keeps a
searchable line of words for each record and asks the database for records sharing any of them.
That narrows thousands of records to a handful without reading them all, and the careful
comparison then happens on that handful.

**What it connects to** — It reads nothing from ShipBob. It is written after an investigation
and read before the next one. The words it shows the AI sit alongside the merchant's own
description and any past corrections, all marked as text we did not write.

**Anyone can ask it directly.** Two addresses expose the same search the AI is given:

- **`POST /precedent/search`** — describe a claim and get back the past ones most like it, each
  with its score and the reasons it was thought similar. Everything in the request is optional,
  because similarity is a matter of degree: a description on its own is a valid search.
- **`GET /precedent/{id}`** — read one stored claim in full, so a precedent that was cited can
  actually be checked. Withdrawn records are returned here, marked as withdrawn; hiding them
  would make a bad record impossible to inspect or put right.

On screen each past claim is **folded shut**, showing only which claim, which product and what
it closed on. That is the least a representative needs to see whether this claim is going the
same way as comparable ones; the reasons, the other merchant's words and the representative's
note open on a click. Five past claims fully unfolded would put a wall of text in front of the
claim actually being decided.

The search deliberately compares on exactly what the AI compares on. An address that scored
differently from the real thing would be worse than no address at all, because a representative
would be carefully checking the wrong answer.

An empty answer always says which kind of empty it is. `was_read` true means we looked and found
nothing alike; false means the store could not be read. Both come back as successes, because
being unable to look is not a bad request — but a caller that confused the two would tell a
representative there is no comparable history when in fact nobody looked.

**Choices we made**

- **Only closed claims are kept.** This was reconsidered. An earlier version recorded every
  product the moment it was investigated and marked each one with whether a person had looked at
  it yet. That made the store circular: the AI could be shown its own earlier suggestion as
  though it were precedent, and the first guess about a kind of claim would become the reason to
  guess the same way again — inconsistency that is much harder to spot, because on the surface
  every claim now agrees with the last one. Keeping only decided claims removes the problem at
  the source rather than managing it. It also removes a whole layer of machinery: with no
  unsettled records, there is nothing to weigh differently, nothing to mark, and nothing for a
  reader to misread. The cost is that the store stays empty until claims start closing.
- **No AI is used to find similar claims.** Comparing meaning with a model would need another
  paid service, another key, and a network call, and would give slightly different answers on
  two runs. Instead the comparison is plain word overlap plus the shape of the evidence, which
  runs offline, costs nothing, and gives the same answer every time.
- **Word overlap is the weak part, and we know it.** Words common to every claim — "damaged",
  "order" — count as much as rare ones, so two unrelated claims share a floor of similarity. A
  proper scheme would weigh a rare word more heavily. Written up under
  [Would improve](#would-improve).
- **The amount is stored but never shown to the AI.** A past payout is a fact a representative
  may want, but the AI is forbidden to write a figure, and the surest way to stop it repeating
  one is never to show it one.
- **A store that cannot be read does not stop the claim.** This is the opposite of what merchant
  memory does, on purpose. Merchant memory has no way to say "unknown" — an empty list would be
  indistinguishable from a merchant with a clean record — so it fails loudly. Here the answer
  can say which of the two happened, so a broken store reports itself as broken and the
  investigation carries on without precedent.
- **Retrieval happens outside the pre-flight checks.** Deciding whether two claims are alike is
  a comparison of meaning, not a rule with a right answer, so it does not belong in the layer
  that must stay strictly rule-based. Keeping it out also means a claim stopped at the gates is
  never searched for and never written down.

**When things go wrong** — An empty store is the ordinary answer for the first claim ever filed,
and is reported as "none found" rather than as a failure. A store that cannot be read is
reported as "could not be read", which is deliberately a different answer: telling a
representative there is no comparable history, when in fact nobody looked, is worse than saying
nothing. A record that turns out to be wrong can be withdrawn, which takes it out of future
searches without touching the record of the claim it came from.

**Not ready for production** — The two addresses have no sign-in, like the rest of this
demonstration: anyone who can reach the service can read every past claim, across every merchant.
The lookup blocks while it reads the file, which is fine for a local file and would not be for a
real database. Nothing closes a claim yet, because the screen where a representative approves a
report does not exist, so nothing writes a record either — the capture works and is exercised by the tests only,
and a real store fills up only once claims start being decided. Withdrawing a bad record works
but is not reachable over HTTP, so it needs a console today. The report a representative reads does not yet show which
precedents were used, or flag a recommendation that departs from them, and the set a run was
given is not yet pinned to that run — so the same claim investigated twice can see a different
store. Those are FR-S.9, FR-S.10 and FR-S.11 and they wait on the report.

**Where the code is** — `src/claim_agent/domain/precedent.py`,
`src/claim_agent/storage/precedent_store.py`, `src/claim_agent/agent/precedent_context.py`,
`src/claim_agent/agent/prompts.py`.

---

### Showing a representative how similar claims went

**What it does** — When a claim clears all four checks, the screen asks the service which past
claims resemble it and shows them at the end of the conversation, each with the service's own
reasons for thinking it similar.

**Why we need it** — A claim that passes the checks used to end on four green ticks and a note
saying the investigation does not exist yet. There was nothing on screen a representative could
actually use. The record of past claims is the one thing the system knows about a passing claim
without any AI, so it is the one thing worth showing (FR-S.4, FR-S.5).

**How it works**

1. The screening runs as before, and the whole answer comes back.
2. **Only if the verdict is "proceed"** does the screen ask a second question. A stopped claim
   is owed an explanation and an email, not a comparison — nothing is going to be investigated,
   so how comparable claims went does not help anybody.
3. The screen sends the merchant's own description of what happened, which is all it has: the
   claim has not been split into products yet, so there is no product or price to compare on.
   The service does the comparing.
4. Only when **both** answers are in does the conversation start playing out. The similar claims
   appear after the verdict, before the note about the investigation.

**What it connects to** — It reads `POST /precedent/search` and nothing else. It sends one field
and adds nothing: which claims count as similar is entirely the service's judgement, and the
screen shows the ranking and the reasons exactly as they arrive.

**Choices we made**

- **Only on a claim that passes.** Asked for directly, and right for its own reasons: a stopped
  claim's conversation ends in an email a representative has to approve, and dropping a
  comparison in front of that would bury the thing they actually have to act on.
- **Still a replay, not a race.** Both requests finish before the first message appears. Starting
  the conversation while the second was still in flight would put finished-looking steps on
  screen for work that had not finished — the same trap the pacing already avoids.
- **A failed search does not fail the screening.** The screening succeeded; throwing it away
  because a second question went unanswered would lose work a representative can use. So the
  similar-claims message says it could not look, and everything else stands.
- **"We looked and found none" and "we could not look" are shown differently.** The service
  distinguishes them and so does the screen. Telling somebody there is no comparable history when
  in fact nobody managed to look is the one wrong answer here.
- **The screen sends only the description.** It would be worse to guess at a product: choosing
  which of an order's items a claim is about is exactly the judgement the splitting stage exists
  to make, and doing it in the browser would be the screen deciding something. The results are
  therefore looser than what the investigation will eventually see, which is honest — the screen
  has less to go on at this point, because less is known.

**When things go wrong** — The service being unreachable, or refusing the request, leaves a
message saying the past claims could not be read and leaves the rest of the conversation intact.
An empty result says so plainly rather than showing an empty box.

**Not ready for production** — The search is on the merchant's description alone, so it is
coarser than the comparison the investigation gets, which also weighs the product, its price and
the evidence pattern. Nothing on screen says a past claim's outcome was never reviewed by a
person beyond the label the service sends, and a representative skimming could read the two
alike. There are still no tests for the UI.

**Where the code is** — `web/src/screens/PreflightScreen.tsx`, `web/src/chat/transcript.ts`,
`web/src/components/SimilarClaims.tsx`, `web/src/api/client.ts`.

---

### Watching an investigation happen

**What it does** — Gives an investigation a way in over the web, and reports what it is
doing while it does it rather than going quiet and answering at the end.

**Why we need it** — An investigation is slow. It screens the claim, reads photographs one
at a time, looks up how comparable claims were decided, works out which products were
damaged, and only then reaches a recommendation for each of them. Answering all of that in
one reply means a representative watches a blank screen for most of a minute with no way to
tell whether anything is happening, which of several products is being worked on, or
whether it has quietly failed.

It also settles something that was not honest before. The screen used to play the quick
checks out one at a time as though they were happening; in truth the answer had arrived
whole and every pause was a length the screen invented. This is the real version of that.

**How it works**

1. A caller asks about one claim. The case id is the whole request — there is nothing to
   send with it.
2. The reply opens immediately as a stream, and stays open. Everything that follows arrives
   on it in pieces.
3. The quick checks run first. Their verdict is the first thing sent.
4. **A claim the checks turn away stops there.** Its explanation and its draft email are
   sent as the result, and no photograph is ever looked at — an ineligible claim costs three
   cheap reads and no AI at all.
5. Otherwise the investigation starts, and says what it is doing as it goes: the images it
   found, what each one turned out to be, what the shared evidence came to, how the claim
   was split, **what comparable past claims were found for each product**, and then, for
   each product, which tool it chose to look at next and what it concluded.
6. When every product is finished, one last message carries everything a representative
   decides from: the split, each product's findings and reasoning, its recommendation, how
   its amount was worked out, and its draft email.
7. A closing message ends the stream.

**What it connects to** — It is the only way in to the investigation, and the only place the
quick checks and the investigation meet. It reads from ShipBob and from the store of past
claims, and writes nothing anywhere.

**Choices we made**

- **The messages are the service's own words.** Each one arrives as a finished sentence,
  ready to put on screen unchanged. The screen adds labels and nothing else — it never works
  out a verdict, re-orders anything, or writes a sentence of its own about what was found.
  That is what keeps the browser a window onto the investigation rather than a second
  opinion about it.
- **Somebody closing their browser cannot fail a claim.** Whoever is watching is outside our
  control: a connection drops, a tab closes. None of that says anything about the claim, so
  a message that cannot be delivered is noted and ignored, and the investigation carries on.
- **What the investigation says is drained before the result is sent.** A run can say
  several things and finish in the same breath, and stopping the moment the work is done
  would throw those away — including, on a claim that failed, the messages saying what it
  had managed to establish first.
- **The model is not built until the claim is going on.** Building one needs a key, and a
  claim the checks turn away needs no model at all. Asking for one up front would refuse an
  ineligible claim for want of a credential it was never going to use.
- **The result is sent whole, not in pieces.** A report read half-arrived is worse than one
  that arrives a moment later.
- **Failing part way through is said, not signalled.** Once a stream has opened there is no
  status left to change, so a failure arrives as a message and the stream still closes
  tidily. A connection that simply stops is the thing this whole shape exists to prevent.
- **Asked for as a POST**, even though it changes nothing today. Investigating is a step in
  the claim pipeline, and once results are kept the step will record one.

**When things go wrong** — Every failure ends the stream with a message saying what happened
and then a close. A case ShipBob does not have, a ShipBob that cannot be reached, a missing
model key, a run that used up its steps, a photograph that cannot be fetched: each arrives
as something a representative can act on. Nothing ends in an empty connection, and nothing
ends in a payment.

**Not ready for production** — Nothing is stored, so a stream cannot be caught up
with or replayed — a representative who reloads has to start the investigation again, and
one who closes the tab half way through loses the work. There is no keep-alive on a quiet
connection, so anything between the browser and the service that times out an idle stream
would cut a long investigation off. And a caller who goes away does not stop the
investigation: it runs to the end and its findings are discarded.

**Where the code is** — `src/claim_agent/api/routes/investigate.py` is the way in,
`src/claim_agent/agent/events.py` is what a run says about itself, and
`src/claim_agent/agent/run.py` is the investigation it narrates.

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
- **Any real escalation.** The escalate button is a simulation in exactly the way the send
  button is: nothing is queued, nobody is told, and the screen reports it as escalated regardless.
  It is worse in one respect — nothing anywhere decides where an escalated claim should *go*, so
  even the real version has an unanswered question in front of it (see the questions at the end).
- **Any real sending.** The send button is a simulation. Nothing is contacted, nothing is
  recorded, and there is no address in the system behind it — the whole of stage 4 is empty. The
  screen reports the email as sent and gives no hint that it was not, which makes this the most
  misleading thing in the project: anyone shown the demonstration will believe a merchant was
  contacted. That was asked for deliberately, and the trade is that this entry and the component's
  docstring are now the only warning. Whoever builds the real sending stage should replace the
  simulation rather than wire something up behind it, because the real one owes several things
  this one does not: refusing to send twice, checking what is being sent against what was
  approved, and keeping a record of it.
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


- **The investigation is built in pieces and none of it runs yet.** The parts that judge an
  outcome, work out an amount, count a run's steps, keep its record, reach the model, and read
  images and invoices from ShipBob all exist and are tested. Nothing joins them up: there is no
  loop that spends the budget, no tools bound to the model, and no way to reach any of it over
  the web. So the promises that a run always terminates and that running out of steps hands the
  claim to a person are wired but not yet kept, and no claim has ever been investigated.
- **Nothing caches an image.** The requirement that an image is looked at once per claim, not
  once per damaged product, has nowhere to live yet — the client re-lists attachments on every
  call and remembers nothing. Looking at pictures is the most expensive thing this system does,
  so this is the single biggest cost risk in the layer.
- **The stand-in for ShipBob serves neither new endpoint.** It answers the three cheap reads and
  nothing else, so even once the investigation is joined up, it cannot be demonstrated end to end
  on a laptop until the stand-in can list attachments and price a shipment.
- **The whole-claim cap is not enforced anywhere.** There is a setting saying the cap should limit
  a whole claim as well as each product in it, and nothing reads it. The amount function caps only
  what it is handed, one product at a time, so until whoever joins the pieces up enforces it, the
  cap can be exceeded simply by splitting a claim into more products — the exact hole the
  requirements warn about.
- **Nothing records that a claimed quantity was reduced.** A merchant claiming five of a product
  the invoice shows two of is quietly paid for two. The reduction is correct and it is invisible:
  there is no field for it, so no report shows it and no email mentions it. The merchant is left
  to notice the shortfall themselves.
- **An amount that came to nothing does not say why.** No invoice, a product the invoice does not
  list, and a product the invoice prices at nothing all produce the same empty result, and every
  reader has to work out which of the three happened from the surrounding fields. Three different
  problems deserve to be said once rather than reconstructed three times.
- **The record of a run is not kept.** It exists for as long as the reply takes and is then gone.
  The requirement asking for an ordered record of what was done to each case is unmet, and the
  record has ordering but no times, because nothing fills them in.

### Could break

- **The stand-in for ShipBob is not ShipBob.** It serves nine claims from the same sample records
  the tests use. Anything the real API does that those records do not show — a field with an
  unexpected shape, an error we have not seen, a slow response — is not being exercised by
  clicking through the screen, and a demo that works proves less than it appears to.
- **The screen shows money exactly as the system sends it, and pads nothing else.** That is
  deliberate, and it means a figure arriving in an unexpected shape would appear on screen in
  that shape rather than being quietly tidied up. Tidying it up in the browser is the thing this
  project most wants to avoid, so the trade was made knowingly.
- **Half the rhythm is now real, and the half that is not looks exactly like it.** The
  investigation genuinely reports as it works, and the screen shows those steps as they
  arrive — so what a representative watches during the investigation is real work in real
  order, in the service's own words. The quick checks at the top are still a replay, and
  every message still spins for a fixed beat as it arrives, which means a step can appear a
  little after it happened. So the *steps* are no longer invented; the *timing* still is.
  That is a much smaller lie than the one this entry used to describe, and it is still worth
  knowing before trusting the pace of it. Everything below applies to the quick checks.

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


- **Asking the same question twice can give two different answers.** Everything around the AI is
  fixed and repeatable — the arithmetic, the rules, the ordering, the identifiers — and the
  reading of a photograph is not. The model is asked for its most likely answer rather than a
  fresh one each time, which helps and is not a guarantee: the same name can be served by a
  changed model, and the provider's own arithmetic is not identical run to run. This is the
  clearest gap between what the system promises about consistency and what it can actually
  deliver, and the honest defence is that the parts that decide money and outcomes are not the
  parts that vary.
- **The confidence figure now withholds real payments.** It is the AI's own opinion of how sure it
  is, nothing in this system has ever checked it against what turned out to be true, and the level
  we compare it against is a number we invented. A model that is confidently wrong will say so
  confidently, and a model that is habitually modest will send good claims to a person for no
  reason.
- **A mistake in our own loop reaches a rep as a blank error.** Spending more steps than the
  budget allows is treated as a fault in our code rather than an outcome for the claim, and
  nothing translates it into an answer. Safe, in that no claim is ever paid or closed by it, but
  the rep gets an opaque failure with no way to resume.
- **A reply the AI malforms is never asked for again.** It goes straight to a person. That is
  deliberate — the identical question asked the identical way is the least likely thing to come
  back differently — but it means a single badly-shaped answer costs a whole investigation.
- **One label covers three different reasons a product cannot be priced.** An ambiguous product,
  no invoice at all, and a product the invoice prices at nothing are all reported the same way.
  The sentence a rep reads tells them apart; the label does not, so anything built on the label
  alone will treat them as one thing.
- **The invoice cannot be matched to the order by product code.** The requirements say the two
  documents carry identical lines, and the example invoice has no product code on its lines, so a
  product can only be tied to an invoice by its code or its name as written. A merchant with two
  similarly named products is exactly where that goes wrong, and that is the case this system
  most needs to get right.
- **We guessed how ShipBob says it will not price a shipment.** Only the status code is
  load-bearing. If it signals that refusal some other way, every such shipment is reported as
  ShipBob being broken instead, and a rep is sent looking for an outage that is not happening.
- **The two ShipBob clients now hold the same code twice.** Retrying, parsing, and the careful
  handling that stops money losing its cents were copied rather than shared, because the second
  client was written without touching the first. They agree today. A fix applied to one will
  silently miss the other.

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


- **One reading of ShipBob, not two.** The client that screens a claim and the client that
  fetches its evidence now hold the same retrying and parsing code twice, because the second was
  written without touching the first. Sharing it would leave one copy to fix.
- **A second, differently-worded attempt when the AI malforms its answer.** Feeding the
  complaint back and asking again would recover some investigations that currently go to a
  person. It was deliberately not done, because deciding what to say the second time is a
  question about wording rather than plumbing.
- **Reasons as a list rather than one long sentence.** A claim line with five things wrong
  produces a single very long sentence. It is complete and true, and a rep would read it faster
  as a list.

### Questions for whoever owns the requirements

- **The requirements refer to "open question 2" and "open question 3" but contain no list of open
  questions.** Neither affects the quick checks, but both are cited as unresolved and nobody can
  look them up.
- **Does a claim filed exactly on the age limit still count?** We say yes. It is a coin flip.
- **What should happen when neither the claim nor the parcel records a delivery date?** We stop
  the claim and call it missing information. This is the decision we are least sure of.
- **Should an insured claim reach the merchant at all?** We say no: FR-0.2 says an insured
  shipment must be "routed out, never processed here", so we mark it for escalation and write
  nothing to the merchant, on the reasoning that whoever handles insurance claims will be the one
  to talk to them. But FR-0.4 says every ineligible claim is closed *with an explanation to the
  merchant*, without excepting this one, so the two can be read as contradicting each other. This
  is the interpretation the code now rests on, and it is the decision most worth confirming.
- **And where should an escalated claim go?** Nothing says. The write-up says a claim has to be
  escalated and nothing about to whom, which means today it is escalated to nobody in particular.
- **When a claim fails several checks a merchant can be told about, which comes first?** We lead
  with age, then wrong type, then missing information. They are told every reason either way —
  the order settles which one they read first and which one is in the subject line, not which
  ones they hear. Nobody has confirmed that this is the right emphasis.
- **Which "invoice" does each rule mean?** The word covers two different documents: the picture
  the merchant uploaded as proof of what they bought, and the priced list ShipBob generates on
  request. We read the first as the evidence a claim needs and the second as where prices and the
  "is this product on the invoice?" check come from. Nobody has confirmed that, and it decides
  what every payout is calculated from.
- **What should happen to a product the invoice prices at nothing?** CASE-1005's order contains a
  free promotional insert. We send it to a person, because paying nothing and refusing outright
  are both defensible and neither is written down.
- **Should a merchant be told when we pay for fewer items than they claimed?** Claiming five of a
  product the invoice shows two of is currently reimbursed at two, silently.
