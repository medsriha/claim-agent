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

- [x] UI-1 — The `web/` project itself: Vite, React, TypeScript in strict mode, eslint. Add
  `node_modules` to `.gitignore`, which does not mention it today.
  - **Conclusion:** TypeScript runs as strictly as mypy does next door — unchecked index access,
    exact optional properties and unused arguments are all errors — and eslint runs the
    type-aware rule set, not just the syntactic one. Three real problems came out of that on the
    first run, including a branch that could never execute.
  - **Be aware:** the type-aware eslint rules are pointed only at the TypeScript files. Applied
    to everything they make the eslint configuration file itself fail to lint, because there are
    no types to read for it.

- [x] UI-2 — The ShipBob look: one token file, logo asset, values marked provisional.
  - **Conclusion:** every colour and font is a custom property in `web/src/theme/shipbob.css`,
    and the stylesheet next to it contains no literal colour at all, so a wrong shade is one
    edit rather than a hunt.
  - **Be aware:** the values are our approximation of ShipBob's public branding and nobody has
    signed them off, exactly like most of `policy.py`. The logo is a drawn stand-in, not
    ShipBob's mark, and says so in its own file.

- [x] UI-3 — A typed client for the backend: TypeScript types mirroring the screening result and
  the error shape, in one place, so no screen parses raw JSON.
  - **Conclusion:** `web/src/api/types.ts` mirrors the service field for field with nothing
    renamed on the way in, so it can be read side by side with the Python models and checked.
    `client.ts` is the only thing in the UI that knows an address or a status code.
  - **Be aware:** money arrives as text, not as a number, and the types say so. That is what
    stops anything on the page doing arithmetic with it by accident.

- [x] UI-4 — Getting the browser to the API: a Vite dev proxy, or cross-origin middleware on the
  backend. Nothing configures this today.
  - **Conclusion:** the dev server forwards `/cases` and `/health` to the service. No backend
    change at all, and nothing opened up on a service that has no sign-in.
  - **Be aware:** this only works while the dev server is in front of the page. A built UI served
    from anywhere else has no proxy and would need this solved properly.

- [x] UI-5 — Case lookup: enter a case id, call the endpoint, show that something is happening
  while it runs.
  - **Conclusion:** an input, a button, and the nine sample ids as buttons so someone can try it
    without knowing an id.
  - **Be aware:** the sample buttons are labelled with ids and nothing else, on purpose. Saying
    what each one demonstrates would be the page asserting an outcome it does not decide, and it
    would become a lie the moment a threshold changed.

- [x] UI-6 — The verdict: carry on, or stopped with every reason, in the order the backend
  ranked them.
  - **Conclusion:** stated first and largest, with a sentence saying what it means for the rep
    rather than only what it is called.
  - **Be aware:** the reasons are printed in the order they arrive and never sorted. The order is
    not cosmetic — the first is the one that heads the merchant's email — and the page marks it
    as such when there is more than one.

- [x] UI-7 — The four checks: all four always shown, passed and failed alike, each with its
  plain-sentence explanation and the values it looked at.
  - **Conclusion:** every check can be opened to reveal its `observed` values as a labelled
    table, closed to begin with, so the sentence is what a rep reads first and the working is
    there when they doubt it.
  - **Be aware:** an empty observed value is a real answer — "nothing was missing" — so it is
    drawn as a dash rather than left as blank space that reads like a rendering bug.

- [x] UI-8 — The claim context: what the order was worth, whether that counts as high value, how
  many days passed between delivery and the claim, and anything a rep corrected for this
  merchant before.
  - **Conclusion:** an unknown order value is shown as "unknown" with the reason next to it,
    which is deliberately not the same as an order worth nothing.
  - **Be aware:** nothing writes rep corrections yet — that belongs to a later stage — so on a
    fresh machine this panel is always empty and the feature cannot be seen at all. `make seed`
    puts a few in. See UI-11.

- [x] UI-9 — The stopped-claim report: the findings, and the drafted merchant email shown plainly
  as a draft. No send action — nothing exists to send it.
  - **Conclusion:** the draft warning sits above the email, because the email's own words never
    say "draft" and this screen is therefore the only place that state is visible.
  - **Be aware:** there is no send button and nothing behind one. The check for that is not a
    test but the architecture: no endpoint exists that could send anything.

- [x] UI-10 — Failure: a case that does not exist, ShipBob being unreachable, and the network
  dropping each have to render something a rep can act on.
  - **Conclusion:** four named kinds of failure, each with its own heading and its own suggestion.
    The sentence explaining what happened comes from the service where it sent one, because it
    says it more precisely than the page could guess; what to do about it is the page's own.
  - **Be aware:** a result and a failure are never on screen together — a new screening clears
    whatever the last one left — because a stale verdict next to a fresh error is worse than
    showing nothing.

- [x] UI-11 — A way to actually run the demo. The backend calls a real ShipBob address and there
  is no mock server in this repo, so today the UI has nothing to talk to.
  - **Conclusion:** `tools/shipbob_mock.py` serves the nine sample claims from the very same
    fixtures the tests use, so the screen and the tests can never disagree about what CASE-1001
    looks like. `tools/seed_demo_memory.py` puts a few past rep corrections in so UI-8 has
    something to show.
  - **Be aware:** the stand-in restores the cents on every price before answering, because the
    fixtures hold prices as ordinary numbers where 38.00 and 38.0 are the same thing, and the
    real API sends money with its cents. Without that, the stand-in would quietly stop exercising
    the one thing the client is most carefully written to get right. Making this import from
    `tests/` also meant making `tests/` a package and its own imports absolute.

- [x] UI-12 — `make ui-*` targets and a UI quickstart.
  - **Conclusion:** `ui-install`, `ui-dev`, `ui-build`, `ui-lint`, plus `mock` and `seed`, with
    the whole demo written up in the README.
  - **Be aware:** the UI targets are deliberately not part of `make check` or CI, so nothing
    catches a broken UI for you.

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

Money is a string on purpose. Line totals and the order total are computed in Python and are not
in the JSON, so there is nothing to multiply in the browser — see
[CLAUDE.md](CLAUDE.md#the-ui).

`layer0-http-transcript.txt` holds six real responses — both verdicts, a missing case and an
outage — which is enough to build every screen against without inventing sample data.

## Not built

Everything past the quick checks, because everything past the quick checks does not exist in the
service either. There is no approving, no sending feedback back, no editing an email's wording,
no view over a claim's separate products, and no way to fetch back a screening once the page is
closed. Those are Layer 2 and Layer R requirements with nothing behind them yet.

There are also **no tests for the UI at all**, and it is not covered by the checks that run
before a push. That was deliberate — see UI-12 — but it means a change to `web/` is only as safe
as the person making it.
