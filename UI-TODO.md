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

- [x] UI-6 — The verdict, with the reasons in the order the service ranked them.
  - **Conclusion:** the verdict and the reasons are the service's own values, reshaped to read —
    `claim_too_old` becomes "Claim too old". There is no table of our own wording anywhere, so
    the screen can only show what the service actually said, and a value we have never seen
    still reads.
  - **Be aware:** never sorted on screen. The first reason heads the merchant's email.

- [x] UI-7 — The four checks, all shown, each opening to reveal the values it looked at.
  - **Be aware:** an empty observed value is a real answer — "nothing was missing" — so it is
    drawn as a dash rather than blank space that reads like a bug.

- [x] UI-8 — The claim in numbers, and past rep corrections.
  - **Be aware:** nothing writes corrections yet — that is FR-3.8, a later stage — so this list
    is always empty. It shows the empty state the endpoint actually returns. Do not seed it with
    invented history to make the demo look fuller.

- [x] UI-9 — The stopped-claim findings and the drafted email, marked as a draft.
  - **Conclusion:** the draft note sits above the email because the email's own words never say
    it. No send button, and no endpoint behind one.
  - **Superseded by UI-23 and UI-24.** The email is editable now and there is a send button. It
    still reaches no endpoint — that part has not changed, and the screen says so.

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
  - **What was built:** a button that swaps the composer for a read-only view of the wording, with
    the screen's own sentence saying nothing was sent.
  - **Conclusion:** the user asked for a fake send knowing Layer 3 does not exist. What makes it
    safe rather than dishonest is that the screen says so in its own words, marked as the screen's
    words and not the service's. Do not make that sentence quieter.
  - **Be aware:** the real thing owes several things this does not — refusing to send twice,
    checking the payload against what was approved, keeping a record (FR-3.4, FR-3.5, FR-3.7).
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

- [x] UI-15 — The panel: every threshold, with a control chosen by what sort of value it is.
  - **What was built:** `screens/PolicyScreen.tsx` and `components/PolicyValueRow.tsx`. The
    service sends a kind per value — whole number, money, fraction, words, yes-or-no, ranking —
    and the row draws the matching control.
  - **Conclusion:** the panel knows nothing about claims. Every label is the value's own name
    reshaped to read, every explanation is the sentence from the policy file, and a threshold
    added to that file appears here with no UI change. That includes the file's own "PROVISIONAL"
    marker, which is worth a reader seeing rather than hiding.
  - **Be aware:** every number is an ordinary text box, deliberately. A number box would round or
    refuse on its own, and money must never pass through a browser number (FR-1.21, NFR-2). The
    values arrive as text and are sent back as text, untouched.

- [x] UI-16 — The reason ranking, reordered with up and down buttons.
  - **Conclusion:** buttons rather than dragging — they work with a keyboard, need no library, and
    cannot half-drop an entry. The positions are numbered because the numbering is the point: the
    first reason heads the merchant's email.
  - **Be aware:** the panel does not check the ranking. Losing or repeating a reason is refused by
    the service, which has always had that rule, and its complaint appears under the control.

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
         drafted_email{to, subject, body, is_draft}, requires_rep_approval
error    error{code, message, details} — "not_found" (404), "upstream_unavailable" (502)
```

The policy panel's own shapes, from `src/claim_agent/admin/models.py`:

```
view     values[], changed_at (null until something changes), matches_startup
value    name, description, changed, kind, value, startup_value
         kind "integer" | "money" | "fraction" | "text" → value is text
         kind "boolean"                                  → value is true or false
         kind "ranking"                                  → value is a list of names, in order
update   {"values": {name: text | true/false | [names]}} — partial; anything left out is kept
error    also "invalid_request" (400), whose details carry values[{name, message}]
```

Money is a string on purpose. Line totals and the order total are computed in Python and are not
in the JSON, so there is nothing to multiply in the browser — see
[CLAUDE.md](CLAUDE.md#the-ui).

`layer0-http-transcript.txt` holds six real responses — both verdicts, a missing case and an
outage — which is enough to build every screen against without inventing sample data.

## Not built

Everything past the quick checks, because it does not exist in the service either: no approving,
no feedback, no view over a claim's separate products, no fetching back a screening. Those are
Layer 2 and Layer R.

An email **can** be reworded now (UI-23) and **can** be sent (UI-24), but the send reaches
nothing and the edit is kept nowhere. Both are simulations on a screen, not stages of the
system.

There are also **no tests for the UI**, and it is outside the checks that run before a push.
