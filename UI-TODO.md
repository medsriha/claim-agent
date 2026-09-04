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

- [ ] UI-1 — The `web/` project itself: Vite, React, TypeScript in strict mode, eslint. Add
  `node_modules` to `.gitignore`, which does not mention it today.
- [ ] UI-2 — The ShipBob look: one theme file holding every colour and font, plus the logo. The
  values are our approximation of public branding and the file has to say so.
- [ ] UI-3 — A typed client for the backend: TypeScript types mirroring the screening result and
  the error shape, in one place, so no screen parses raw JSON.
- [ ] UI-4 — Getting the browser to the API: a Vite dev proxy, or cross-origin middleware on the
  backend. Nothing configures this today.
- [ ] UI-5 — Case lookup: enter a case id, call the endpoint, show that something is happening
  while it runs.
- [ ] UI-6 — The verdict: carry on, or stopped with every reason, in the order the backend
  ranked them.
- [ ] UI-7 — The four checks: all four always shown, passed and failed alike, each with its
  plain-sentence explanation and the values it looked at.
- [ ] UI-8 — The claim context: what the order was worth, whether that counts as high value, how
  many days passed between delivery and the claim, and anything a rep corrected for this
  merchant before.
- [ ] UI-9 — The stopped-claim report: the findings, and the drafted merchant email shown plainly
  as a draft. No send action — nothing exists to send it.
- [ ] UI-10 — Failure: a case that does not exist, ShipBob being unreachable, and the network
  dropping each have to render something a rep can act on.
- [ ] UI-11 — A way to actually run the demo. The backend calls a real ShipBob address and there
  is no mock server in this repo, so today the UI has nothing to talk to.
- [ ] UI-12 — `make ui-install`, `ui-dev`, `ui-build`, `ui-lint`, and a quickstart in the README.

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
