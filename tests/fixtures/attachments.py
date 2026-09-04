"""Records shaped like the evidence endpoints' replies, for tests to work from.

An investigation reads two things beyond the case itself: the images a merchant uploaded
to the case, and an invoice ShipBob prices the shipment with. The replies for both live
here once, so two tests can never disagree about what a listing looks like, and so a
change in the shape of either reply is a change in one file.

This module deals in plain dictionaries and strings on purpose. It knows nothing about the
rest of the project, so a test that uses it is checking our code against the shape of the
API rather than against our own idea of that shape.

What is here:

- Builders — `attachment_payload`, `attachments_payload`, `invoice_line_item`,
  `invoice_payload` — each returning one complete, valid record. Any keyword argument
  replaces the matching field, so a test that cares about a single field writes only that
  field: `invoice_payload(line_items=[])`.
- `attachments_payload` takes the attachments themselves rather than keywords, and with
  none given returns the empty listing — which is exactly what CASE-1005 returns, and the
  case a test is most often written about.
- The listings and the invoice the requirements quote, `ATTACHMENTS_1003`,
  `ATTACHMENTS_1005` and `INVOICE_342578703`.

**Dropping a field entirely is `without`, in `tests/fixtures/shipbob.py`.** There is
deliberately no second copy of it here: a field that is absent behaves differently from a
field that is present and empty, and one helper for that difference is enough.

Real values and invented ones — read this before trusting a field
-----------------------------------------------------------------

**Real, copied from REQUIREMENTS.md:**

- CASE-1003's three attachment ids, file names and content types, exactly as the
  requirements quote them (FR-1.4).
- CASE-1005's listing, which is `{"attachments": []}` and nothing else. That case has no
  evidence at all, and an empty listing must never be treated as a failure (FR-1.6).
- The whole of the invoice for shipment 342578703 — its id, its two priced lines and the
  moment it says it was generated (FR-1.18).

**Ours, and it could not be otherwise:**

- **Every attachment URL.** The real ones are signed links to Azure blob storage, valid
  until 2036, and REQUIREMENTS.md prints them truncated (`https://...`). They cannot be
  reproduced from what we were given, so the ones here are obviously-local stand-ins on
  port 9001 that no test should read anything into beyond "this is where the image is".
- **The body of a refusal.** REQUIREMENTS.md says the invoice endpoint can answer
  `422 invoice_unavailable` and must be handled, but does not print the reply. The code
  in `INVOICE_UNAVAILABLE_BODY` is the requirements' word; the two fields around it are
  copied from the shape ShipBob uses for a missing record, which is a guess.
- **Any identifier we made up starts with a 9**, the same rule the case fixtures follow,
  so ours can be told from ShipBob's at a glance.

One more real detail worth knowing before writing a test. REQUIREMENTS.md says the invoice
lines are identical to the order's, and then prints them without the `product_id` the
order carries. The builders here follow the printed reply, so an invoice line names a
product by `sku` and by name only. A test that needs to match an invoice line to an order
line has to do it on one of those.

Three real file names — `kgray1.png`, `IMG_9726.jpeg` and `329233.png` — are quoted by the
requirements without saying which cases they belong to, so no record here uses them.

The constants below are ordinary dictionaries, and Python hands every test the same one.
Read them; never change one in place. A test that needs a variant calls a builder.
"""

from __future__ import annotations

# ShipBob's own short name for "I will not price this shipment" (FR-1.18). The fields
# around it are our guess at the shape; this string is the requirements'.
INVOICE_UNAVAILABLE_BODY: dict[str, object] = {
    "error": "invoice_unavailable",
    "message": "No invoice could be generated for the provided shipment.",
}

# Where our stand-in attachment images live. Local and on a port starting with 9, so
# nobody mistakes it for one of ShipBob's signed Azure links.
_LOCAL_ATTACHMENT_HOST = "http://localhost:9001"


def attachment_payload(**overrides: object) -> dict[str, object]:
    """Build one attachment record — an image the merchant uploaded to a case.

    The defaults are the first of CASE-1003's three attachments: its id, file name and
    content type are ShipBob's, and its URL is ours. A test changes what it cares about
    and leaves the rest alone: `attachment_payload(content_type="image/jpeg")` gives a
    photograph rather than a screenshot, which must make no difference to anything
    (FR-1.4).

    Returns a fresh dictionary each call, so a test may change the result freely.
    """
    payload: dict[str, object] = {
        "attachment_id": "ATT-CASE-1003-01",
        "file_name": "Inv.png",
        "content_type": "image/png",
        "url": f"{_LOCAL_ATTACHMENT_HOST}/attachments/case-1003/01_Inv.png",
    }
    payload.update(overrides)
    return payload


def attachments_payload(*attachments: dict[str, object]) -> dict[str, object]:
    """Wrap attachment records in the object the listing endpoint returns.

    The endpoint answers with `{"attachments": [...]}` rather than a bare list, and the
    wrapper is part of what our code has to read, so tests build it here rather than by
    hand.

    Called with nothing it returns the empty listing — a case with no evidence at all,
    which is an ordinary answer and not a failure (FR-1.6). That is deliberately the
    default, because it is the answer most worth writing a test about.

    Returns a fresh dictionary and a fresh list each call.
    """
    return {"attachments": list(attachments)}


def invoice_line_item(**overrides: object) -> dict[str, object]:
    """Build one line of an invoice — a product, how many of it, and what each cost.

    The defaults are the first line of the invoice for shipment 342578703: one Additional
    Collagen Ampoule Duo at $38.00. Prices are plain numbers, never strings, because that
    is how the API returns them and the reading of them is what tests are checking — a
    price has to keep its cents all the way through (FR-1.18).

    There is no `product_id`, because the reply the requirements print does not carry one.

    Returns a fresh dictionary each call.
    """
    payload: dict[str, object] = {
        "name": "Additional Collagen Ampoule Duo",
        "sku": "AMP1",
        "quantity": 1,
        "unit_price": 38.00,
    }
    payload.update(overrides)
    return payload


def invoice_payload(**overrides: object) -> dict[str, object]:
    """Build one invoice record — what ShipBob says a shipment contained, priced.

    The defaults are the invoice for shipment 342578703 exactly as REQUIREMENTS.md quotes
    it: two lines coming to $90.00, generated at a fixed moment. The invoice is the only
    thing a recommended amount may be worked out from (FR-1.18).

    Returns a fresh dictionary each call, and a fresh list of lines with it, so a test can
    append to or edit the list without affecting anyone else.
    """
    payload: dict[str, object] = {
        "invoice_id": "INV-342578703",
        "shipment_id": "342578703",
        "line_items": [
            invoice_line_item(),
            invoice_line_item(
                name="Liposomal Tripeptide Collagen",
                sku="COLLAGEN1",
                quantity=1,
                unit_price=52.00,
            ),
        ],
        "generated_at": "2026-03-21T10:00:00.000+0000",
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# The replies the requirements quote
# ---------------------------------------------------------------------------

# CASE-1003, Huge Supplements — three attachments, and the listing that shows why a file
# name proves nothing (FR-1.4). The first is named `Inv.png` and the other two are
# screenshots taken fifteen seconds apart whose names are near-identical, yet they are
# different kinds of evidence. Every id, name and content type is ShipBob's; every URL is
# ours, because the real ones are printed truncated and cannot be reproduced.
ATTACHMENTS_1003 = attachments_payload(
    attachment_payload(),
    attachment_payload(
        attachment_id="ATT-CASE-1003-02",
        file_name="Screenshot_at_Feb_26_20-45-24.png",
        url=f"{_LOCAL_ATTACHMENT_HOST}/attachments/case-1003/02_Screenshot.png",
    ),
    attachment_payload(
        attachment_id="ATT-CASE-1003-03",
        file_name="Screenshot_at_Feb_26_20-45-11.png",
        url=f"{_LOCAL_ATTACHMENT_HOST}/attachments/case-1003/03_Screenshot.png",
    ),
)

# CASE-1005, Loam Science — no attachments at all, which is the whole of ShipBob's reply
# and the whole point of this fixture. Every one of the four evidence items is missing, so
# the only possible outcome is a request for information, and the empty listing must reach
# our code as an empty listing rather than as an error (FR-1.6).
ATTACHMENTS_1005 = attachments_payload()

# The invoice for CASE-1001's shipment, as REQUIREMENTS.md quotes it in full.
INVOICE_342578703 = invoice_payload()
