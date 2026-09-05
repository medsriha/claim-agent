# UI tracker

The demo interface in `web/` — what is built and what is not.

The UI does not appear in [TODO.md](TODO.md) because it does not appear in
[REQUIREMENTS.md](REQUIREMENTS.md) either: that document covers the backend and says the
reviewer-facing UI is "specified separately". The separate specification is not in this repo. So
**these ids are ours, invented here** — do not go looking for `UI-1` in REQUIREMENTS.md.

That also means this file carries a one-line description per id, unlike TODO.md. There is no
other document holding them.

**Tick a box only when it genuinely works** — built, tried in a browser, and explained in
[DESIGN.md](DESIGN.md). Then write underneath it what was actually built, what a future reader
should take away, and anything they need to be aware of, the same way TODO.md does.

## v1 — Layer 0 on a screen

A rep types a case id and sees what the pre-flight screening decided. Nothing else. The
endpoint behind it is `POST /cases/{case_id}/preflight`, which is already built.

- [x] UI-1 — The `web/` project: Vite, React, TypeScript strict, eslint; `node_modules` ignored.
  - **Be aware:** the type-aware eslint rules are pointed only at the TypeScript files; applied
    to everything they make the eslint config itself fail to lint.

- [x] UI-2 — The ShipBob look: one token file and the logo.
  - **Conclusion:** every colour is a custom property in `web/src/theme/shipbob.css`, and the
    stylesheet beside it holds no literal colour at all. The brand blue and navy are sampled
    from the logo artwork and the box mark is traced from it, so neither is guesswork.
  - **Be aware:** the wordmark is set in the page's own typeface, not ShipBob's. Swap both the
    mark and the wordmark for the official asset before this is seen outside the team.

- [x] UI-3 — A typed client: types mirroring the result and the error shape, in one place.
  - **Conclusion:** `api/types.ts` mirrors the service field for field; `api/client.ts` is the
    only thing in the UI that knows an address or a status code.
  - **Be aware:** money is typed as text, which is what stops anything doing arithmetic with it.

- [x] UI-4 — Reaching the API: the Vite dev proxy forwards `/cases` and `/health`.
  - **Conclusion:** no backend change, and nothing opened up on a service with no sign-in.
  - **Be aware:** only works behind the dev server. A built page served elsewhere has no proxy.

- [x] UI-5 — Case lookup: an input, a button, and the nine sample ids.
  - **Be aware:** the sample buttons carry ids and nothing else. Labelling what each one
    demonstrates would be the page asserting an outcome it does not decide.
  - **Superseded by UI-22.** The input and its button are gone; the nine ids remain. The rule
    about not labelling them still holds.

- [x] UI-6 — The verdict, with the reasons in the order the service sent them.
  - **Conclusion:** the verdict and the reasons are the service's own values, reshaped to read —
    `claim_too_old` becomes "Claim too old". There is no table of our own wording anywhere, so
    the screen can only show what the service actually said, and a value we have never seen
    still reads.
  - **Be aware:** never sorted on screen. The first reason names the merchant email's subject
    line, so re-ordering them here would misreport what the merchant will read.

- [x] UI-7 — The four checks, all shown, each opening to reveal the values it looked at.
  - **Be aware:** an empty observed value is a real answer — "nothing was missing" — so it is
    drawn as a dash rather than blank space that reads like a bug.

- [x] UI-8 — The claim in numbers, and past rep corrections.
  - **Be aware:** nothing in the *system* writes corrections — that is FR-3.8, a later stage — so
    on a fresh machine this list is empty, and that is the real state of the endpoint rather than
    a gap in the screen.
  - **Be aware:** it is no longer *always* empty. `tools/seed_merchant_memory.py` writes one
    invented correction against CASE-1001's merchant so the panel can be demonstrated, and
    `--clear` removes it. So a correction on screen means either a rep made it or somebody ran
    that tool — and today it can only be the second. Still do not seed from the UI, a test, or a
    fixture; the tool is deliberately the one place that does it, and it announces itself.

- [x] UI-9 — The stopped-claim findings and the drafted email, marked as a draft.
  - **Conclusion:** the draft note sits above the email because the email's own words never say
    it. No send button, and no endpoint behind one.
  - **Superseded by UI-23 and UI-24.** The email is editable now and there is a send button. It
    still reaches no endpoint — that part has not changed — but the screen no longer says so; it
    reports the email as sent.

- [x] UI-10 — Failure: four named kinds, each with its own heading and one line on what to do.
  - **Conclusion:** the explanation comes from the service where it sent one.
  - **Be aware:** a result and a failure are never on screen together.

- [x] UI-11 — Something to run it against: `tools/shipbob_mock.py`.
  - **Conclusion:** the stand-in serves the same fixtures the tests use, so the screen and the
    tests cannot disagree about what CASE-1001 looks like.
  - **Be aware:** it restores the cents on every price first — the fixtures hold them as ordinary
    numbers, and without that the demo would stop exercising the exact-money handling. Importing
    from `tests/` also meant making `tests/` a package and its imports absolute.

- [x] UI-12 — `make ui-install`, `ui-dev`, `ui-build`, `ui-lint`, plus `mock`.
  - **Be aware:** deliberately not part of `make check` or CI, so nothing catches a broken UI.

## v2 — the same screening, as a conversation

The findings arrive one at a time instead of all at once, and a stopped claim ends in an email a
rep can reword and send. Same endpoint behind it — `POST /cases/{case_id}/preflight` — and no
backend change of any kind.

**Why these start at UI-20.** The policy panel was being built at the same time and had first
claim on the numbers after UI-12. Leaving UI-13 to UI-19 free was cheaper than two features
answering to the same id.

- [x] UI-20 — The conversation: one screening laid out as an ordered list of messages.
  - **What was built:** `web/src/chat/transcript.ts` turns one result into messages — three reads,
    the numbers, one message per check, the decision, then the write-up and the email on a stopped
    claim. `chat/Message.tsx` is the only place that knows which component draws which kind.
  - **Conclusion:** the order is the service's running order, not ours, and the transcript file
    arranges without deciding — it reads no rule and computes no figure. It is the file here most
    likely to drift into deciding something, so keep it dull.
  - **Be aware:** the old panels were split to make this work — `RecordPanel` became three read
    components, `GateList` became a single `GateCard`. The panel frame now comes from the message
    bubble, which is why those components no longer carry one.

- [x] UI-21 — The pacing, and the fact that it is a replay rather than a race.
  - **What was built:** the whole response is fetched first; only then does `chat/useReveal.ts`
    play the messages out. Each message the system sends has two phases — **working**, showing its
    heading and a spinner, then **settled**, showing the finding. A check spins and then the
    spinner is replaced by a tick or a cross in the same place, so the answer lands where the eye
    already is. About 1.15s per message, so roughly thirteen seconds for a stopped claim.
  - **Conclusion:** **this is the decision to preserve.** Revealing while the request is in flight
    would show a finished step for work that had not finished, or had already failed. Because the
    reveal only ever replays a response that arrived, a failed screening has no steps to show —
    which is structural, not something a check has to catch.
  - **Be aware:** the spinners are a lie, and a convincing one — every check was decided before
    its message existed. That is the biggest gap between this screen and the system, and it is
    written up in DESIGN.md under **Could break**. Keep it written up. The two durations live in
    the hook rather than the theme file, because a timer needs a number and a stylesheet cannot
    hand one over.
  - **Be aware:** there is **no skip button**. One was built and then removed on request — it
    undercut the point of the screen. `prefers-reduced-motion` is the only way to get the whole
    conversation at once, and it is an accessibility path, not a convenience, so do not remove it
    as well. Anyone demoing the same claim repeatedly waits the full thirteen seconds each time.

- [x] UI-22 — The case picker: the nine ids, and no typing box.
  - **What was built:** `components/CasePicker.tsx`, pinned below the conversation, with the
    picked claim marked. `SAMPLE_CASE_IDS` moved to `web/src/sampleCases.ts`.
  - **Conclusion:** the box could only ever produce "no such claim" — the stand-in serves these
    nine and nothing else — so removing it took a dead end off the screen.
  - **Be aware:** `.lookup-input` stayed in the stylesheet on purpose. The policy panel borrows it.

- [x] UI-23 — The editable email.
  - **What was built:** `chat/EmailComposer.tsx`. Subject and wording are editable; the recipient
    is not, because it comes from the claim's contact address and who hears about a claim is not a
    rep's to change. A claim with no contact address disables the send and says why.
  - **Be aware:** an edit lives in browser state and nothing else. Picking another claim discards
    it silently, and nothing is recorded against the merchant — so FR-3.8 is still entirely unmet.

- [x] UI-24 — The send, which sends nothing.
  - **What was built:** a button that swaps the composer for a read-only view of the wording under
    a confirmation reading "Sent to <the merchant's address>".
  - **Conclusion:** the user asked for a fake send knowing nothing behind it sends, and then asked
    for the disclaimer to come off, so **nothing on screen reveals that the send is not real**.
    That is a product decision, not an oversight: a demonstration should read as a working product
    rather than one apologising for itself. It does mean anyone shown this believes a merchant was
    contacted, so whoever demonstrates it has to say otherwise out loud.
  - **Be aware:** the warning now exists in exactly two places — DESIGN.md under **Not
    implemented**, and the docstring of `chat/EmailComposer.tsx`. Keep both current; they are all
    anyone gets. The real thing owes several things this does not — refusing to send twice,
    checking the payload against what was approved, keeping a record. Those used to be
    requirements; the execution layer they belonged to has since been cut from REQUIREMENTS.md,
    so reinstating the send is a scope decision rather than an outstanding task.
    Replace the simulation; do not wire something up behind it.

- [ ] UI-25 — Tried in a browser.
  - **Not done, and deliberately not ticked.** Every message was rendered to HTML against the live
    service and checked — all four checks present, the composer only on stopped claims, no steps at
    all on a failure — and the project builds, typechecks and lints clean. But nobody has watched
    the pacing run, clicked send, or resized the window. The session that wrote it had no browser.

## v3 — changing the rules from a screen

The numbers the checks judge by, on a screen an admin can edit. The endpoints behind it —
`GET /admin/policy`, `PUT /admin/policy`, `POST /admin/policy/reset` — were built for this and
are new; everything about the claim policy already lived in one file (FR-0.7, NFR-7).

**These are the reserved UI-13 to UI-19.** The conversation rewrite was being built at the same
time and starts at UI-20.

- [x] UI-13 — Two screens, and tabs in the header to move between them.
  - **What was built:** `App.tsx` holds which screen is showing; the screening screen and the
    policy panel are the two. The current tab is marked for anything reading the page aloud.
  - **Be aware:** the screen you leave is taken down, not hidden, so a conversation is lost when
    you switch. That is on purpose — a conversation screened under the old policy, sitting beside
    a policy that has since changed, is the one thing on this page that could mislead.

- [x] UI-14 — One failure type for both screens, and the dev proxy forwarding `/admin`.
  - **What was built:** `api/failure.ts` holds the failure kinds, the error-envelope reading and
    the per-value complaints; `api/request.ts` is now the only place that calls `fetch`. The
    screening client and the policy client are both a few lines on top of it.
  - **Conclusion:** the alternative was a second copy of the same careful failure handling. One
    kind was added — `invalid_request`, which only the panel can cause — and the notice component
    grew a heading for it.
  - **Be aware:** this renamed `ScreeningFailure` to `ApiFailure`, which touched the screening
    screen, the transcript and the failure notice. Nothing about screening behaviour changed.

- [x] UI-15 — The panel: the thresholds worth changing, each with a control chosen by what sort
  of value it is.
  - **What was built:** `screens/PolicyScreen.tsx` and `components/PolicyValueRow.tsx`. The
    service sends a kind per value — whole number, money, fraction, words, yes-or-no, or one of a
    set of choices — and the row draws the matching control.
  - **Conclusion:** the panel knows nothing about claims. Every label is the value's own name
    reshaped to read, every explanation is the sentence from the policy file, and a threshold
    added to that file appears here with no UI change. That includes the file's own "PROVISIONAL"
    marker, which is worth a reader seeing rather than hiding.
  - **Be aware:** the panel shows what the service offers it, which is no longer every policy
    value. Four are marked off-panel in `policy.py` — three belong to the unbuilt investigation,
    and a control that changes nothing observable is worse than no control. Nothing in the UI
    knows which four; it draws what arrives.
  - **Be aware:** every number is an ordinary text box, deliberately. A number box would round or
    refuse on its own, and money must never pass through a browser number (FR-1.21, NFR-2). The
    values arrive as text and are sent back as text, untouched.

- [x] UI-16 — **Removed.** The email reason order, reordered with up and down buttons.
  - **What happened:** built, then taken out when the order stopped being a policy value and moved
    into `gates.py`. With no list-shaped value left, the control, its type, its styles and its
    tests were all unreachable, so they went too.
  - **Conclusion:** worth reading if you are about to add a list-shaped policy value — the shape
    of the control that worked (up and down buttons, positions numbered, no dragging and no
    library) is in the history rather than in the code.

- [x] UI-19 — **Replaced.** There is no escalation button or escalation outcome.
  - **What exists now:** the report card shows `request_rep_clarification`, explains what the rep
    needs to clarify, displays confidence, and shows no merchant email. The deleted
    `chat/EscalationAction.tsx` simulation is not part of the current interface.

- [x] UI-17 — Saving, being refused, and putting the startup values back.
  - **What was built:** Save sends the whole form; the panel then draws whatever the service says
    is in force. A refusal shows the service's sentence plus one complaint under each value it
    named, and changes nothing. "Put back the startup values" is offered only when the service
    says the policy has moved off them.
  - **Conclusion:** the panel never decides what changed or whether a value is any good. It sends
    what was typed and shows the answer, which is why it cannot disagree with the service.
  - **Be aware:** one sentence on this screen is the screen's own — that a change is lost on
    restart — and it lives in `chat/pageWords.ts` with the other two. The service cannot say that
    about itself, and somebody changing what every later claim is judged by has to know it.

- [ ] UI-18 — Tried in a browser.
  - **Not done, and deliberately not ticked.** The whole chain was driven through the dev proxy
    with the service and the ShipBob stand-in running: the policy read back, the age limit changed
    to 5, `CASE-1001` turned away as too old with the new limit quoted in the merchant's email, a
    refused change proved to have changed nothing, and reset putting it back. It builds,
    typechecks and lints clean. But nobody has clicked a checkbox, moved a ranking entry, or
    looked at the layout. The session that wrote it had no browser.

## v4 — showing how similar claims went

- [x] UI-26 — Similar past claims, fetched after a screening that passes and shown at the end of
  the conversation.
  - **What was built:** `POST /precedent/search` is called from `screens/PreflightScreen.tsx` once
    the screening comes back, **only when the verdict is "proceed"**. The answer is drawn by
    `components/SimilarClaims.tsx` after the decision and before the note about the missing
    investigation stage. The dev proxy now forwards `/precedent`.
  - **Conclusion:** it is still a replay, not a race. Both requests finish before the first message
    appears, so nothing on screen ever shows a finished-looking step for work that had not
    finished. A stopped claim is never asked about at all — that is `sought: false`, which is
    deliberately a third state alongside "found nothing" and "could not look".
  - **Be aware:** the screen sends **only the merchant's description**, because a claim has not
    been split into products at this point and choosing a product in the browser would be the
    screen deciding something. So these results are coarser than what the investigation will
    eventually be shown, which also weighs the product, its price and the evidence pattern.
  - **Be aware:** a failed search does not fail the screening — it becomes a sentence inside the
    similar-claims message and everything else stands (NFR-4). "We looked and found none" and "we
    could not look" render differently on purpose; collapsing them would tell a rep there is no
    comparable history when nobody actually looked.
  - **Be aware:** `chat/pageWords.ts` went from one sentence to three. The service has no wording
    for "read the store, nothing was close enough" or for a request that never got an answer, so
    the screen owns those two. Check them there before adding a fourth.
  - **Each past claim is folded shut**, using the page's own fold — the same one a check card
    uses, so no state and no library. Shut it shows the case, the product and what the claim
    closed on; open it adds the reasons, the other merchant's account and the rep's note.
  - **Revised after the first build.** The panel used to show a review-state pill on every row,
    green for a claim a rep decided and grey for one nobody had looked at. Both are gone: the
    service now stores only closed claims, so every row is a decision and there is nothing to
    mark out as weaker. Each row shows what the claim closed on instead.

## v5 — watching an investigation happen

- [x] UI-28 — The investigation, streamed and shown as it happens, right after the similar
  past claims.
  - **What was built:** `api/investigationStream.ts` posts to `/cases/{id}/investigate` and
    reads the reply as it arrives, handing each message over untouched.
    `screens/PreflightScreen.tsx` starts it once the screening says "proceed" and the similar
    claims are on screen, then appends what the service says as it says it. Two new
    components draw it: `components/InvestigationStep.tsx` for a step, and
    `components/LineReport.tsx` for one damaged product — its recommendation, the working
    behind its figure, the four pieces of evidence and the four questions with their
    confidence. `components/ClaimTotal.tsx` covers what a claim comes to across its products.
  - **Conclusion: this is the first part of the screen that is not a replay.** Everything
    above it is laid out from an answer that had already arrived; these messages exist
    because the service said so, in the order it said it, in its own words. That retires most
    of the invented pacing — see the caveat below for the part that remains.
  - **`EventSource` was not usable.** It only ever sends a GET and asking for an
    investigation is a POST, so the reply is read directly with `fetch`. A few more lines
    here and no change to the service.
  - **Be aware: the timing is still the screen's.** The steps are real and their order is
    real, but each message still waits its turn behind the ones before it and spins for a
    fixed beat as it arrives — so a step can appear a little after it happened. The *steps*
    are no longer invented; the *timing* is. Much smaller than the fiction it replaced, and
    still worth knowing.
  - **Be aware: a claim that passes is now asked about three times** — screening, similar
    claims, then the investigation, which screens the claim again for itself. Those three
    cheap reads therefore happen twice, and cost no AI. The alternative was to wait for the
    stream before showing any of the four checks, which would have made the first thing a
    representative sees arrive later rather than sooner.
  - **Be aware: money is still text everywhere.** Every figure the reports show is a string
    the service sent, and nothing on screen adds any of them up — the arithmetic was done in
    the service, and doing it again in a browser would be a second calculation that could
    disagree with the first (FR-1.21).
  - **`chat/pageWords.ts` went back down to two sentences.** The one saying the investigation
    stage did not exist was removed, because it does. The ambiguity a claim comes back with
    when its split cannot be settled is drawn as a *finding* rather than a note, since a note
    carries a mark saying the screen wrote it and those words are the service's.
  - **Proven against the real model, on ShipBob's own photographs.** It chose to look at all
    four images on CASE-1001, identified them as the customer's email, the invoice, the
    damaged product and the outer mailer, picked out the Liposomal Tripeptide Collagen,
    and judged what the damage was worth — with the four questions answered between 80% and
    95% confidence and an email drafted.
  - **Two real faults were found by running it**, neither visible to any unit test: the model
    was being built before the route body ran, so a missing key refused even a claim that
    screening would stop; and `temperature` is rejected outright by `claude-opus-5`, so every
    single investigation was failing on its first model call. Both fixed, both now pinned by
    a test.

- [ ] UI-29 — Tried in a browser.
  - **Not done.** The whole flow was exercised against the live service and the real model,
    and the project builds, typechecks and lints clean. Nobody has watched it render. The
    thing most likely to look wrong is a long run of steps on a claim with several
    products — the reading order is right, but nobody has seen how much scrolling it makes.

- [ ] UI-27 — Tried in a browser.
  - **Not done.** The flow was exercised against the live service — both verdicts, the exact
    request the screen makes, a seeded precedent coming back with its score and reasons — and the
    project builds, typechecks and lints clean. Nobody has watched it render.

## v6 — the investigation's own words

- [x] UI-30 — What the investigation says, passed on whole and drawn in the shape it was
  written in.
  - **What was built:** two changes, one on each side. In the service, `agent/loop.py` no
    longer cuts the model's remark before putting it on the stream — it used to trim at three
    hundred characters, mid-word. On the screen, `components/Markdown.tsx` reads the part of
    markdown a model actually writes — headings, bullet and numbered lists, code blocks,
    bold, italics, inline code — and `components/InvestigationStep.tsx` draws a step's
    sentence through it.
  - **Conclusion:** the cut was losing the most useful part of a remark. The end of "the
    second photograph is too dark, so I will look at the third" is the half saying what the
    run decided to do next, and that is the half a length limit takes.
  - **Be aware: the step-by-step record still trims its own entries** to three hundred
    characters. That is deliberate and they are different things — the record is a summary
    kept for review, the commentary is the run talking while it works. They shared a limit
    because they looked alike.
  - **Be aware: only the steps are read as markdown.** The report's own fields — a product's
    explanation, its concerns, what a photograph showed — are single sentences laid out in a
    table, and are still drawn as plain text.
  - **Be aware: links are not read**, and show as the characters that were typed. Nothing
    writes them today, and deciding where it is safe to send somebody is worth doing on
    purpose rather than in passing.
  - **Nothing becomes markup.** Every piece of the text is turned into an element directly
    and none of it is handed to the browser as HTML, so a model that writes something looking
    like markup puts those characters on screen and can do nothing else.
  - **Checked by rendering it, since the screen has no tests.** Fourteen samples were
    rendered to fixed HTML and read. Two real faults turned up that way and are fixed:
    `claim_line_id` and `list_attachments` were being italicised on their underscores, and
    `5 * 3 * 2` was being read as emphasis. Both now behave the way markdown itself does —
    a mark has to sit against its text, and an underscore inside a word is part of the word.

- [x] UI-32 — A step that says a lot, folded into a quiet box that scrolls.
  - **What was built:** `components/InvestigationStep.tsx` now draws a step one of two ways.
    A short one reads as before, a line of narration. A long one — more than three lines, or
    more than about 240 characters — goes inside the page's own fold, greyed down and capped
    at about six lines of height with the rest scrolling. Shut, it shows its first line so a
    representative can tell what they are opening.
  - **Conclusion:** the fold is what makes passing the whole remark through affordable. The
    text is never shortened, and a step that reasons at length now takes the same room on
    screen as one that says a sentence.
  - **Be aware: it starts open**, because watching the work happen is the reason the stream
    exists. Shutting it is the representative's to do, and `<details>` remembers it — no
    state, no library, and the message keys are stable so nothing reopens on its own.
  - **Be aware: the rule is about length, not kind.** Nothing here knows that `thinking` and
    `tool_called` are the long ones. A kind this screen has never seen is judged on the same
    terms, and a short remark is never boxed up for nothing.
  - **Checked by rendering it:** a short step, a three-line step and a long one, read as
    fixed HTML. The short shape is byte-for-byte what it was before.

- [ ] UI-31 — Tried in a browser.
  - **Not done.** The screen builds, typechecks and lints clean, and both the reading and the
    folding were checked by rendering them to HTML. Nobody has watched a real investigation
    draw a list on screen. Two things are most likely to look wrong. The first line of a short
    step: the kind mark and the first paragraph share a line on purpose, and a step whose
    first block is a list or a code block starts that block underneath instead. And the
    scrolling box: nobody has seen how a scroll region inside a conversation that also scrolls
    behaves under a wheel or on a phone.

## v7 — how the agent is doing, for the business

A third screen, beside the screening and the admin panel. It answers a different question from
either: not "what should happen to this claim", but "how has this been going, over months, and is
it getting better".

**Read this before anything else: every figure on that screen is invented, and nothing on screen
says so.** Nothing in the system records what a representative decided, so there is no real
history to draw. The screen carries a year of made-up figures in `web/src/analysis/demoFigures.ts`
rather than reading them from anywhere.

That is a deliberate departure from the rule that the interface never invents a record, and it was
taken for one reason: the alternative was a tab that stays blank until somebody runs a command
they have no way of knowing about, and a blank dashboard is indistinguishable from a broken one.
The cost is that a viewer cannot tell these numbers from measured ones. Like the send button, the
warning lives only in the docs and the docstring.

**The numbers were still not typed by hand.** They were produced by running the real thing — the
tool that invents a year of decisions, then the service's own arithmetic — and keeping the answer,
so every written figure matches the value beside it and each week's four shares really do come to
one. They are remade rather than edited.

Even so the screen works nothing out: a rate, a total, an axis and a verdict all arrive decided
(FR-1.21, NFR-2, and the UI rules in CLAUDE.md), which is what would let it be pointed back at
`GET /analysis/performance` without touching a single component.

**These ids cover the service work too, not only the screen.** REQUIREMENTS.md never mentions
measurement, reporting or automation, so the store, the arithmetic and the address behind this
screen trace to no requirement id at all and have nowhere to live in TODO.md, which holds
REQUIREMENTS.md ids and nothing else. Two requirements do bear on it and are named where they
apply: FR-C.8 governs the invented data, and FR-C.7's open question is the shape of the rules the
screen scores.

**There is no charting library and there is not going to be one.** The charts are inline SVG in
`web/src/charts/`, drawn the way `theme/ShipBobLogo.tsx` is drawn. No dependency was added; the
screen still rests on React and React DOM and nothing else.

- [x] UI-33 — A third screen and a third tab.
  - **What was built:** `screens/AnalysisScreen.tsx`, a third `ScreenTab`, and the header's
    ternary replaced by a `switch` that lists every screen — so a fourth one cannot be added
    without the compiler asking where it goes.
  - **Be aware:** the dev proxy does **not** forward `/analysis`. It did, and the entry was taken
    out again when the screen stopped calling the service — a proxy rule for an address nothing
    asks for is one more thing to be wrong. Put it back if the screen is ever pointed at the
    service.
  - **Be aware:** the screen you leave is still taken down rather than hidden (UI-13), and that
    now matters for a second reason: figures worked out under one set of rules, sitting beside
    rules that have since changed, would mislead exactly the way a stale screening would.

- [x] UI-34 — The record of what a representative decided, and the store that keeps it.
  - **What was built:** `domain/decision.py` in the shape FR-C.1 already describes, a
    `rep_decisions` table beside the others, and `storage/decision_store.py`.
  - **Conclusion:** this is the store half of FR-C.1 and nothing more. **FR-C.1 is not ticked in
    TODO.md**, because it asks for a review action to *produce* the record and that stage is not
    built — the same half-built position merchant memory's write side has been in since UI-8.
  - **Be aware:** three fields go beyond FR-C.1's reference record — how sure the system said it
    was, what the order was worth, and how long the review took. None of the figures on the screen
    can be worked out without them, and there is no store of reports to look them up in.

- [x] UI-35 — The arithmetic, and the address that serves it. **Nothing calls it.**
  - **What was built:** `analysis/performance.py` holds every count and rate and touches nothing —
    no database, no network, no model — so all of it is tested without any of those.
    `analysis/view.py` turns those figures into what the screen draws.
  - **Be aware:** a rate over nothing is *nothing*, never zero. A week nobody decided anything in
    has no direct-approval rate, and drawing it at 0% would read as a collapse in quality.
  - **Be aware:** claims the quick checks stopped are counted apart from investigated products
    everywhere. They cost no AI and are agreed with far more often, so one blended figure would
    flatter the advice.

- [x] UI-36 — The typed shapes the figures travel in.
  - **What was built:** `api/analysisTypes.ts`, mirroring the service field for field, and
    `analysis/demoFigures.ts`, which holds a set of those figures per period and says in its own
    docstring that all of them are invented.
  - **Be aware:** the client that fetched them was deleted when the screen stopped calling the
    service. The types stayed, because they are still the shape the service answers in and the
    shape the screen draws — that is what keeps the two swappable.
  - **Be aware:** every figure arrives twice — a number that exists only to become a position, and
    the words a person reads. Nothing on the screen turns one into the other. If you ever find
    yourself writing a `formatPercent` here, the figures are under-specified.

- [x] UI-37 — **Removed.** The filter row: the service's own periods, in one row.
  - **What happened:** the screen shows twelve months and offers no choice. Once the figures moved
    into the screen, a choice of three periods meant carrying three sets of them, and three sets
    nobody switches between is weight in the page for nothing. The sentence saying what the period
    covers stayed; the buttons went.
  - **Be aware:** the service still reports on four weeks and thirteen weeks as well, and the
    shape it answers in still carries the list of choices. Putting the row back is a matter of
    writing out more than one period, not of building anything.

- [x] UI-38 — The hero figure, the tiles, and the savings.
  - **Be aware:** the tiles are whatever list the service sends, drawn in its order — another
    figure appears with no change here, the same way a new threshold does on the admin panel.
  - **Be aware: the assumptions behind the money are no longer shown.** They were, marked
    PROVISIONAL and in the service's own words, and they were taken off for being noise on the
    page. The cost is real and worth stating plainly: the dollar figures are hours multiplied by
    an hourly rate we invented, less a cost per claim we also invented, and nothing on screen now
    says so. The figures still travel in the reply and the service still explains them; only the
    panel that printed them is gone.

- [x] UI-39 — The chart frame: a one-to-one drawing, an axis, a legend, a table twin, and one
  tooltip serving every chart.
  - **Be aware:** the drawing is never scaled. It is measured with a `ResizeObserver` and drawn at
    its measured size, because a `viewBox` stretched by CSS scales the type with everything else —
    7px labels on a narrow window and 22px ones on a wide monitor.
  - **Be aware:** one focus stop per chart, with the arrow keys moving between points. A stop per
    point would be hundreds of them before the table at the bottom of the page.
  - **Be aware:** every chart has a table twin holding the same figures, so no value on this
    screen is reachable only by hovering.

- [x] UI-40 — The charts, after three were taken off.
  - **What was built:** how far a representative changed things (four bands, week by week), the
    confidence comparison, and how long a review took.
  - **What happened to the other three:** *how often each recommendation was changed*, *candidate
    rules, scored*, and *taken exactly as recommended, week by week* were all removed. The first
    said little — disagreement came out much the same across all three actions, because
    what drives it in the invented data is how sure the system was and what the order was worth,
    rather than which of the four it landed on.
  - **Be aware:** the approval rate week by week was the only chart carrying two series, and its
    removal is why the two-line case now has no user. `TimeSeriesChart` still draws any number of
    series and still has the legend for it; nothing on the screen asks for more than one.
  - **Be aware:** the confidence panel is one plot, not two. A rate and a count must never share
    an axis, so how many decisions a band held is *written* under it rather than drawn — the point
    where two such lines crossed would be an accident of scaling a reader would take for meaning.
  - **Be aware:** a week with nothing in it breaks the line. Nothing bridges the gap.

- [x] UI-41 — **Removed.** The candidate rules, as a table and never as a switch.
  - **What happened:** taken off the screen. It scored each order-value band crossed with each
    band of stated confidence, on how much of the work it would cover and how often people agreed,
    and it was the panel that most directly answered "could any of this be automated yet".
  - **Be aware:** the scoring still exists and is still tested — `analysis/performance.py` works
    the rules out and the service still returns them. What went is the table that drew them. The
    care that went into it is worth keeping if it comes back: no toggle, no button, no colour on
    the verdict, and no sorting, because FR-2.9 says a person approving is the only way a claim
    leaves review and a green "meets bar" would read as a recommendation the screen is not making.

- [x] UI-42 — The chart palette, in `theme/shipbob.css`.
  - **What was built:** four hues in a fixed order plus a hairline for the axis, each checked
    against this page's own white for lightness, for staying apart under colour blindness, and
    for reading against the background.
  - **Be aware: this started as four steps of one blue and that did not work.** How far a
    representative went is genuinely an *order*, and one hue getting darker is how a reader sees
    an order in the colour — but four steps that all stay light enough to read on white sit too
    close to tell apart in a stack, which was the whole job. Four hues lose the ordering and win
    the legibility, and the legend carries the meaning instead. Do not put the ramp back without
    looking at it.
  - **Be aware:** aqua and yellow sit below three-to-one against white. That is allowed only
    because every chart using them also has a legend and a table holding the same figures.
  - **Be aware:** the existing pass, stop and flag colours are **not** usable as chart series.
    Flag against stop is very nearly indistinguishable with the commonest form of colour
    blindness, and pass against flag is worse. That costs nothing where each sits beside a word,
    as on the screening screen, and would cost a great deal in a chart.

- [x] UI-43 — Empty, and unreadable, told apart.
  - **What was built:** every panel carries its own sentence for why it is empty, and on the
    service side a store that cannot be read fails the whole request with its own code instead.
  - **Be aware:** with the figures held in the screen there is nothing left to fail, so the
    loading and failure paths were taken out of the screen rather than left sitting unreachable.
    The empty-panel path survives, because a period really can hold nothing.
  - **Be aware:** `storage_unavailable` had to be added to the screen's list of failure kinds.
    Without it, an unreadable store fell through to "something went wrong", and the nearest
    existing heading says "ShipBob could not be read" — which would send somebody looking in
    entirely the wrong place.

- [x] UI-45 — Which claims come back ready to send.
  - **What was built:** the same claims cut four ways, each part showing the share that went out
    untouched, with how many decisions that share rests on. Three of the cuts are things known
    *before* anybody looks at a claim — what the merchant said was damaged, what they said caused
    it, and who carried the parcel — and the fourth is how sure the system said it was.
  - **Conclusion:** this is the panel that answers *which claims are likely to be recommended
    right away and which are not*. The answer is in the spread inside each group, so the service
    writes that spread out and orders the groups by it: how sure the system was separates claims
    by 43 points, what the merchant reported by 20, the carrier by 9, and what they said caused
    the damage by 4 — which is to say the last one does not help, and the screen says so rather
    than leaving somebody to eyeball two bars of much the same length.
  - **Be aware: the first version of this panel was wrong, and wrong in an instructive way.** It
    cut by what the system *recommended* and by what the order was worth, and both came out flat —
    the first because a recommendation is something the investigation produced rather than a
    property of the claim, so grouping by it can only describe work already done. Bars that all
    end in the same place look like a broken chart, when what they really mean is "this way of
    sorting claims tells you nothing". Both problems were fixed: cut by things that arrive with
    the claim, and say the spread out loud.
  - **Be aware:** the vocabulary is ShipBob's own, taken from the published mock API. A case
    description states the two in a fixed form — "Damage Type: Damage due to carrier mishandling.
    Defect Type: Product damaged, but shipping box is intact." — and carriers come from the
    shipment. Nothing here is reworded.
  - **Be aware:** parts within a cut are ordered readiest first, because a carrier is not "more"
    than another carrier and the measure is the only order they have. The confidence bands keep
    their own order, because they have one.
  - **Be aware: the confidence bands are named by the range they cover** — "Under 70% sure",
    "85 to 95% sure" — and not by the short names the settings give them. "Fair" and "High" say
    nothing on their own, and "below the bar" is worse than nothing: it means below the level at
    which the rules already refuse to recommend paying (FR-1.15), which nobody outside this
    codebase could know. The label is built from the band's own edges, so moving a band cannot
    leave the words describing where it used to be.
  - **Be aware:** it is plain bars in HTML rather than a chart. One measure across a handful of
    named groups reads faster as labelled rows, and it needed no drawing code. The bar's length
    comes from a share the service worked out, handed to CSS as a `calc`.
  - **Be aware:** claims the quick checks stopped are left out of all four cuts. They are decided
    by fixed rules and almost always accepted, so including them would drop a large, easy
    population into every group and flatten the differences the panel exists to show.

- [x] UI-44 — Tried in a browser.
  - **What was built:** the screen was rendered against the real service with a year of seeded
    decisions and looked at. **This is the first `tried in a browser` box in this file that is
    ticked** — UI-18, UI-25, UI-27 and UI-29 are all still open.
  - **Be aware:** two real faults were found only by looking. The names under the confidence bars
    were being drawn over the bars themselves, because the room reserved under a plot was sized
    for one line of text and that chart writes two; the axis band is a property of each chart now.
    And the empty state was exercised by accident first — another service was already answering on
    port 8000 — which is how the "nothing was decided" path got checked as well.
  - **Be aware:** it was looked at again after the figures moved into the screen, with no service
    running at all, which is the state anybody cloning this will be in.
  - **Be aware:** what has *not* been tried is a narrow window. The charts are measured and redraw
    on resize, but nobody has watched them do it below about a thousand pixels.

## v7 — deciding on a report

The reports the service now keeps, on screen, with the two things a representative can do to
them. The endpoints behind it — `POST /reports/{id}/approve` and `.../send-back` — are real, and
so is what they record.

- [x] UI-34 — The report, drawn as the document it is.
  - **What was built:** `components/ReportCard.tsx`. The service sends the report as markdown and
    `components/Markdown.tsx` draws it. The card above it shows what is recommended, the amount as
    the text it arrived as, and where the review has got to.
  - **Conclusion:** the screen adds no sentences to the report and takes no data out of it. The
    one thing it needs structurally — the wording of the merchant's email — is sent as a field
    beside the document, so nothing has to read prose for data.
  - **Be aware:** money is text the whole way. The card shows `amount_usd` as it arrived and
    nothing on screen adds two figures together.

- [x] UI-35 — Tables in a report, which markdown could not draw before.
  - **What was built:** `Markdown.tsx` reads tables. It was written for a step's commentary, where
    nothing writes one; a report writes three, and without this the evidence, the four questions
    and the four checks all appeared as rows of raw bars.
  - **Conclusion:** found by rendering a real report to HTML, not by reading the code. A bar the
    service escaped comes back as an ordinary bar inside its cell, so a finding saying
    "two columns | one row" reads correctly instead of shifting every column after it.
  - **Be aware:** a table scrolls inside its own frame, so a wide one never makes the page scroll
    sideways.

- [x] UI-36 — Approving, rewording, and sending back — all three real.
  - **What was built:** `api/reportsClient.ts`, and the buttons on the report card. Approving
    records a decision; rewording the email first changes what the report carries; sending back
    records the note and parks the report.
  - **Conclusion: this is the first thing on this screen that is not a simulation.** The send
    button on a screening email still reaches nothing (UI-24) and this does not — it reaches the
    service and something is written down.
  - **Be aware:** the recipient is shown and cannot be edited, because who hears about a claim
    comes from the claim. The screen refuses to send one, and the service has nowhere to put one.
  - **Be aware:** `chat/pageWords.ts` went from two sentences to three. The new one says that
    approving is recorded and nothing else happens — no email, no money — because the service
    answers with a report and a report cannot describe what the rest of the system does not do.
  - **Be aware: a report sent back leads nowhere.** Layer R is unbuilt, so nothing picks one up.
  - **Be aware: there is no sign-in.** Anyone who opens this can approve a claim, and the record
    cannot say who did.

- [ ] UI-37 — Tried in a browser.
  - **Not done.** The card and the report's markdown were rendered to HTML against the live
    service and read, the whole approve-and-reword round trip was driven through the real
    endpoints, and the project builds, typechecks and lints clean. Nobody has clicked a button.
    The thing most likely to look wrong is a long report inside its scrolling frame next to the
    controls under it.

## v8 — the conversation about a report

Sending a report back used to be a note that went nowhere. It now reaches an agent that reworks
the report and answers, so the card grows a thread: what the representative said, what the agent
said back, what it changed, and what it deliberately left alone.

- [x] UI-38 — The conversation, drawn as a chat.
  - **What was built:** `components/RevisionThread.tsx`, and `revisions` on the report type. The
    representative's messages sit right and the agent's left, oldest first, with what it changed
    and what it left alone hanging under its reply.
  - **Conclusion:** every sentence in it comes from the service. The screen adds which side a
    message sits on, "Changed" and "Left alone", and nothing else — it does not summarise a
    round, reorder one, or say whether an answer was any good.
  - **Be aware:** a round where nothing changed is **marked**, with a rule down its edge, rather
    than hidden. A report left alone because a run failed and one left alone because it was
    already right look identical otherwise, and only one is worth writing back about.
  - **Be aware:** the review history beside it no longer prints sent-back actions, because they
    are the conversation. Nothing is filtered out of what the service sends — only out of what
    that one section draws.

- [x] UI-40 — Reports a message caused to exist.
  - **What was built:** `api/reportsClient.ts` gained a claim reader, and the card fetches the
    claim when a round says the whole claim was investigated again — then draws the new product
    reports nested inside itself.
  - **Conclusion:** without it, a representative who settles what an unsettled claim is for gets
    an answer and no sign of the reports their answer produced, because those reports have ids
    the screen has never seen.
  - **Be aware:** a card drawing cards is unusual, and it is deliberate — the nesting is what
    says *these came from that conversation*. It is one level deep and cannot recurse further,
    because only a claim-level report can produce reports this way.

- [x] UI-39 — The note box, and waiting while the agent works.
  - **What was built:** the box on `ReportCard.tsx` is now a message box. It disables itself while
    the rework runs and the button shows the spinner that was already there.
  - **Conclusion: this is the first thing on this screen that changes what the system concluded.**
    Approving records a decision and rewording changes what a report carries; this sends a
    sentence to an agent and gets a different report back.
  - **Be aware:** there is **no progress and no commentary** while it runs, and a rework is
    several model calls. The service narrates itself into a stream nobody is reading — wiring
    that up is written down in DESIGN.md under **Would improve**, and it is the obvious next
    thing here.
  - **Be aware:** `chat/pageWords.ts` went from two sentences to three. The new one says the
    conversation is waiting on the representative, because the service sends that as a flag and
    a flag cannot be read.

- [x] UI-42 — Forgetting past rep corrections, from the admin panel.
  - **What was built:** `POST /admin/corrections/forget`, `MerchantMemory.forget_everything`, and
    a second section on `screens/PolicyScreen.tsx` apart from the policy form.
  - **Conclusion:** a demonstration often has to start from a system that remembers nothing, and
    the alternative was reaching into the database by hand. It answers with a count, so "it
    worked" and "there was nothing there" are told apart.
  - **Be aware:** it **destroys real history** and there is no undo, no confirmation step and no
    sign-in in front of it. `chat/pageWords.ts` went to four sentences for the warning, because
    the service answers with a count and what the count means for later claims is the part worth
    warning about.
  - **Be aware:** it is all or nothing. Forgetting one correction would be a judgement nobody has
    specified, and offering it would invite quietly deleting an inconvenient one.

- [ ] UI-41 — Tried in a browser.
  - **Not done.** The thread was driven through the real endpoints from the test suite, and the
    project builds, typechecks and lints clean. Nobody has watched a rework happen on screen. The
    thing most likely to look wrong is a long conversation pushing the note box off the bottom of
    a tall report card, and the thing most likely to *feel* wrong is the silence while it runs.

## Reference — what the endpoint returns

Field names as they appear on the wire, so UI-3 does not have to be reverse-engineered from
Python. Source: `src/claim_agent/preflight/models.py` and `src/claim_agent/domain/models.py`.

```
result   case_id, verdict ("proceed" | "terminal"), terminal_reasons[], gates[4],
         record{case, shipment, order}, context, report (null when proceeding), evaluated_at
gate     gate ("age" | "claim_type" | "key_information" | "insurance"), passed,
         reason (null when passed), explanation, observed{string: string}
context  order_value_usd (string, or null when the order could not be read), is_high_value,
         days_since_delivery (null when no delivery date), delivered_date, merchant_corrections[]
report   case_id, account_name, user_id, reasons[], findings[], gates[], context,
         drafted_email{to, subject, body, is_draft} — null when there is nothing the
         merchant can be told, which today means a claim stopped only by being insured,
         requires_rep_clarification (true exactly when the parcel was insured),
         requires_rep_approval
error    error{code, message, details} — "not_found" (404), "upstream_unavailable" (502)
```

The policy panel's own shapes, from `src/claim_agent/admin/models.py`:

```
view     values[], changed_at (null until something changes), matches_startup
value    name, description, changed, kind, value, startup_value
         kind "integer" | "money" | "fraction" | "text" → value is text
         kind "choice"                                   → value is text, plus options[]
         kind "boolean"                                  → value is true or false
update   {"values": {name: text | true/false}} — partial; anything left out is kept
error    also "invalid_request" (400), whose details carry values[{name, message}]

Not every policy value appears: four are marked off-panel in `policy.py`, and a change to
one is refused with the same error shape.
```

Money is a string on purpose. Line totals and the order total are computed in Python and are not
in the JSON, so there is nothing to multiply in the browser — see
[CLAUDE.md](CLAUDE.md#the-ui).

`layer0-http-transcript.txt` holds six real responses — both verdicts, a missing case and an
outage — which is enough to build every screen against without inventing sample data.

## Not built

**Most of this now has a screen** — see v7 above. What is still missing is a **view over a whole
claim**: `GET /cases/{case_id}/reports` returns every product on a claim with its own review
state, and nothing draws it. Today a representative sees the reports from the investigation they
just watched, and cannot come back to a claim later and pick up where they left off. That is the largest gap in this
file: a representative cannot reach any of it from a browser, and the only way to try it is by
hand.

`GET /reports/{report_id}` also returns the other products on the same claim beside it, and
nothing draws those either — so a representative approving one product cannot see that the second
is still waiting.

An email **can** be reworded now (UI-23) and **can** be sent (UI-24), but the send reaches
nothing and the edit is kept nowhere. Both are simulations on a screen, not stages of the
system — and the real rewording endpoint now exists beside them, unused.

Sending a report back is **not** a simulation any more (UI-38, UI-39): the note reaches the
service, an agent reworks the report around it, and what comes back is a new version. What is
missing there is any sign of it happening — the screen goes quiet for as long as the rework takes.

There are also **no tests for the UI**, and it is outside the checks that run before a push.
