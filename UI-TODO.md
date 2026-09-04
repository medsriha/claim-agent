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

- [x] UI-2 — The ShipBob look: one token file, a logo, values marked provisional.
  - **Conclusion:** every colour is a custom property in `web/src/theme/shipbob.css`, and the
    stylesheet beside it holds no literal colour at all.
  - **Be aware:** the values are our approximation and the logo is a drawn stand-in.

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

- [x] UI-6 — The verdict, with the reasons in the order the service ranked them.
  - **Be aware:** never sorted on screen. The first reason heads the merchant's email.

- [x] UI-7 — The four checks, all shown, each opening to reveal the values it looked at.
  - **Be aware:** an empty observed value is a real answer — "nothing was missing" — so it is
    drawn as a dash rather than blank space that reads like a bug.

- [x] UI-8 — The claim in numbers, and past rep corrections.
  - **Be aware:** nothing writes corrections yet, so on a fresh machine this is always empty.
    `make seed` puts a few in.

- [x] UI-9 — The stopped-claim findings and the drafted email, marked as a draft.
  - **Conclusion:** the draft note sits above the email because the email's own words never say
    it. No send button, and no endpoint behind one.

- [x] UI-10 — Failure: four named kinds, each with its own heading and one line on what to do.
  - **Conclusion:** the explanation comes from the service where it sent one.
  - **Be aware:** a result and a failure are never on screen together.

- [x] UI-11 — Something to run it against: `tools/shipbob_mock.py` and `tools/seed_demo_memory.py`.
  - **Conclusion:** the stand-in serves the same fixtures the tests use, so the screen and the
    tests cannot disagree about what CASE-1001 looks like.
  - **Be aware:** it restores the cents on every price first — the fixtures hold them as ordinary
    numbers, and without that the demo would stop exercising the exact-money handling. Importing
    from `tests/` also meant making `tests/` a package and its imports absolute.

- [x] UI-12 — `make ui-install`, `ui-dev`, `ui-build`, `ui-lint`, plus `mock` and `seed`.
  - **Be aware:** deliberately not part of `make check` or CI, so nothing catches a broken UI.

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

Everything past the quick checks, because it does not exist in the service either: no approving,
no feedback, no editing an email, no view over a claim's separate products, no fetching back a
screening. Those are Layer 2 and Layer R.

There are also **no tests for the UI**, and it is outside the checks that run before a push.
