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
- `invoice_from_order`, which prices a sample order the way ShipBob's invoice endpoint
  does. It is how every sample invoice here is made, so an invoice can never claim a
  shipment held something its order does not.
- The five sample cases' attachment listings, `ATTACHMENTS_1001` through
  `ATTACHMENTS_1005`, and the invoice the requirements quote, `INVOICE_342578703`.

**Dropping a field entirely is `without`, in `tests/fixtures/shipbob.py`.** There is
deliberately no second copy of it here: a field that is absent behaves differently from a
field that is present and empty, and one helper for that difference is enough.

Real values and invented ones — read this before trusting a field
-----------------------------------------------------------------

**The five attachment listings are ShipBob's own, fetched from the mock API.** Every
attachment id, file name, content type and address below is the real thing. Nothing about
them is invented any more. That was not always true: an earlier version of this file made
up every URL, pointing them at a stand-in image server on port 9001 that never existed.
Any test still asserting on one of those is asserting on nothing.

The addresses are signed links to Azure blob storage whose signatures run until 2036, so
they can genuinely be fetched, and can be cached locally for offline work (FR-1.4).

Four things about the real listings are worth knowing before writing a test:

- **CASE-1001's fourth attachment is named `kgray4.jpeg` and its address points into the
  `case-1002/` folder**, at the very image CASE-1002's fourth attachment uses. That is
  what ShipBob serves. It is left exactly as it arrived, because it is the sharpest
  illustration in the whole set of why a file name settles nothing about what an image
  holds or which case it belongs to (FR-1.4).
- **CASE-1003's two screenshot names are not quite what REQUIREMENTS.md prints.** The
  requirements quote `Screenshot_at_Feb_26_20-45-24.png`; the API returns
  `Screenshot_Feb_26_20-45-24.png`, without the `at_`, while the stored file behind it
  keeps it. The names here are the API's, since that is what our code will read.
- **CASE-1004's fourth stored file ends `.png.png`.** The doubled extension is in
  ShipBob's address, not a slip here.
- **CASE-1005 has no attachments at all.** Its listing is `{"attachments": []}` and
  nothing else, which is an ordinary answer and never a failure (FR-1.6).

**The invoice is real too, and carries one field the requirements do not print.** The
reply quoted in REQUIREMENTS.md shows an invoice line as a name, a SKU, a quantity and a
price; the endpoint actually returns a `product_id` on every line as well, the same
`product_id` the order carries. Invoice lines here therefore match order lines field for
field, and a test may match one to the other on the product id rather than on the name.

**Ours, and it could not be otherwise:**

- **The body of a refusal.** REQUIREMENTS.md says the invoice endpoint can answer
  `422 invoice_unavailable` and must be handled, but does not print the reply. The code
  in `INVOICE_UNAVAILABLE_BODY` is the requirements' word; the two fields around it are
  copied from the shape ShipBob uses for a missing record, which is a guess.
- **Any identifier we make up starts with a 9**, the same rule the case fixtures follow,
  so ours can be told from ShipBob's at a glance. Nothing in this file needs one today.

The constants below are ordinary dictionaries, and Python hands every test the same one.
Read them; never change one in place. A test that needs a variant calls a builder.
"""

from __future__ import annotations

from tests.fixtures.shipbob import ORDER_1001, order_line_item

# ShipBob's own short name for "I will not price this shipment" (FR-1.18). The fields
# around it are our guess at the shape; this string is the requirements'.
INVOICE_UNAVAILABLE_BODY: dict[str, object] = {
    "error": "invoice_unavailable",
    "message": "No invoice could be generated for the provided shipment.",
}

# Every invoice in the sample set says it was generated at this same moment, which
# postdates every delivery date in it. It is a claim-time snapshot rather than a record
# frozen at fulfilment, and REQUIREMENTS.md flags that as an open question (FR-1.18).
INVOICE_GENERATED_AT = "2026-03-21T10:00:00.000+0000"

# The Azure blob storage the sample images are served from, and the signature every one of
# their addresses carries. The expiry and the signature are ShipBob's, copied exactly:
# the links work, and they keep working until 2036.
_BLOB_CONTAINER = "https://sa032101pubdevuc.blob.core.windows.net/shipbob-fde-mock"
_BLOB_EXPIRY = "2036-07-26T20%3A59%3A50Z"


def _blob_url(stored_path: str, signature: str) -> str:
    """Assemble one image address exactly as ShipBob serves it.

    Every sample address is the same container, the same expiry and the same handful of
    signing options, differing only in the stored file and the signature over it. Writing
    the shared part once keeps the fifteen addresses readable without changing a single
    character of any of them.

    Args:
        stored_path: The file's path inside the container, such as `case-1003/01_Inv.png`.
            It is not always the attachment's own file name, and for one attachment it is
            not even its own case's folder.
        signature: The signature ShipBob signed that file with, already percent-encoded.
    """
    return (
        f"{_BLOB_CONTAINER}/{stored_path}?se={_BLOB_EXPIRY}&sp=r&sv=2021-12-02&sr=b&sig={signature}"
    )


def attachment_payload(**overrides: object) -> dict[str, object]:
    """Build one attachment record — an image the merchant uploaded to a case.

    The defaults are the first of CASE-1003's three attachments, exactly as ShipBob serves
    it. A test changes what it cares about and leaves the rest alone:
    `attachment_payload(content_type="image/jpeg")` gives a photograph rather than a
    screenshot, which must make no difference to anything (FR-1.4).

    Returns a fresh dictionary each call, so a test may change the result freely.
    """
    payload: dict[str, object] = {
        "attachment_id": "ATT-CASE-1003-01",
        "file_name": "Inv.png",
        "content_type": "image/png",
        "url": _blob_url(
            "case-1003/01_Inv.png", "TbWWqD4UI0SPy95LGKIZLc4zxTp3%2BywqBkq%2B5rtfkIM%3D"
        ),
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

    An invoice line and an order line are the same record: ShipBob's generated invoice
    applies no discount and adds no field, so this builds an order line and lets the
    caller change what it needs. Building it any other way would let the two drift apart
    in a fixture file whose whole job is to stop that happening.

    The defaults are therefore the first line of CASE-1001's order, which is also the
    first line of the invoice for its shipment: one Additional Collagen Ampoule Duo at
    $38.00. Prices are plain numbers, never strings, because that is how the API returns
    them and the reading of them is what tests are checking — a price has to keep its
    cents all the way through (FR-1.18).

    Returns a fresh dictionary each call.
    """
    payload = order_line_item()
    payload.update(overrides)
    return payload


def invoice_from_order(order: dict[str, object], *, shipment_id: str) -> dict[str, object]:
    """Price a sample order the way ShipBob's invoice endpoint prices a shipment.

    The generated invoice's lines are identical to the order's, so the honest way to write
    a sample invoice is to take the order that shipment came from and copy its lines. Then
    an invoice can never say a shipment held something its order does not, which is the
    one disagreement that would matter: a recommended amount is worked out from the
    invoice and from nothing else (FR-1.18).

    Args:
        order: A sample order record, which must carry its list of line items.
        shipment_id: The shipment being priced. It names the invoice too, the way
            ShipBob's ids do — shipment 342578703 gets invoice INV-342578703.

    Raises:
        TypeError: If the order carries no list of line items, which would silently
            produce an invoice priced at nothing.
    """
    order_lines = order.get("line_items")
    if not isinstance(order_lines, list):
        raise TypeError("An order must carry a list of line items before it can be priced.")
    return {
        "invoice_id": f"INV-{shipment_id}",
        "shipment_id": shipment_id,
        "line_items": [invoice_line_item(**line) for line in order_lines],
        "generated_at": INVOICE_GENERATED_AT,
    }


def invoice_payload(**overrides: object) -> dict[str, object]:
    """Build one invoice record — what ShipBob says a shipment contained, priced.

    The defaults are the invoice for shipment 342578703, priced from CASE-1001's order:
    two lines coming to $90.00, generated at the moment every sample invoice claims. The
    invoice is the only thing a recommended amount may be worked out from (FR-1.18).

    Returns a fresh dictionary each call, and a fresh list of lines with it, so a test can
    append to or edit the list without affecting anyone else.
    """
    payload = invoice_from_order(ORDER_1001, shipment_id="342578703")
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# The five sample cases' attachments, exactly as ShipBob serves them
# ---------------------------------------------------------------------------

# CASE-1001, Best Paw Nutrition — four images, three of them named for the same person and
# numbered out of order, and a fourth whose name says `kgray4.jpeg` while its address
# fetches CASE-1002's fourth image. Both oddities are ShipBob's and are kept: a file name
# does not settle what an image holds, and here it does not even settle whose case it came
# from (FR-1.4).
ATTACHMENTS_1001 = attachments_payload(
    attachment_payload(
        attachment_id="ATT-CASE-1001-01",
        file_name="kgray2.png",
        url=_blob_url(
            "case-1001/01_kgray2.png", "308DzNTUY7S2TD2defIIzEQsG7opGfCEDPMTjX%2BD8jk%3D"
        ),
    ),
    attachment_payload(
        attachment_id="ATT-CASE-1001-02",
        file_name="kgray1.png",
        url=_blob_url(
            "case-1001/02_kgray1.png", "n1ObzqY%2B3AdYIkLmF8sTEjyW7BhdNDmuX82E56MogwU%3D"
        ),
    ),
    attachment_payload(
        attachment_id="ATT-CASE-1001-03",
        file_name="kgray3.png",
        url=_blob_url("case-1001/03_kgray3.png", "eckWvxw6NeQ6cg615LNylhQQKPkjozoN9R1W62eyLAU%3D"),
    ),
    attachment_payload(
        attachment_id="ATT-CASE-1001-04",
        file_name="kgray4.jpeg",
        content_type="image/jpeg",
        url=_blob_url(
            "case-1002/04_IMG_9722-b8ad8406-d79f-40ad-9f54-5dbc663.jpeg",
            "tDGDb1tfBHJOOIm4rhbi4RNVhLtzYEJuS8GevnvNyNw%3D",
        ),
    ),
)

# CASE-1002, CleanBoss — four images: two photographs from a phone, a screenshot, and a
# file called `329233.png`. Three of the four names carry no hint of content at all, which
# is the point REQUIREMENTS.md makes with them (FR-1.4). Its fourth image is the one
# CASE-1001's fourth attachment also points at.
ATTACHMENTS_1002 = attachments_payload(
    attachment_payload(
        attachment_id="ATT-CASE-1002-01",
        file_name="IMG_9726.jpeg",
        content_type="image/jpeg",
        url=_blob_url(
            "case-1002/01_IMG_9726-e3f5ae0b-55f9-43d8-bc7b-5fc9c8e.jpeg",
            "33T78S7vLBPa%2B5nTpvwMOXhpUDEd%2FiZCIHQWmD8mtkc%3D",
        ),
    ),
    attachment_payload(
        attachment_id="ATT-CASE-1002-02",
        file_name="Screenshot_2026-02-26.png",
        url=_blob_url(
            "case-1002/02_Screenshot_2026-02-26_at_10.14.50%E2%80%AFPM.png",
            "X1oNAxyvsQdHU7XXRhxQj7UZoAd0kEUvKolddYYQ%2Fpc%3D",
        ),
    ),
    attachment_payload(
        attachment_id="ATT-CASE-1002-03",
        file_name="329233.png",
        url=_blob_url(
            "case-1002/03_329233.png", "ft2BowSGYi%2B9mmBReVORZumjBFtnlI7%2F75kjvp%2FQEEU%3D"
        ),
    ),
    attachment_payload(
        attachment_id="ATT-CASE-1002-04",
        file_name="IMG_9722.jpeg",
        content_type="image/jpeg",
        url=_blob_url(
            "case-1002/04_IMG_9722-b8ad8406-d79f-40ad-9f54-5dbc663.jpeg",
            "tDGDb1tfBHJOOIm4rhbi4RNVhLtzYEJuS8GevnvNyNw%3D",
        ),
    ),
)

# CASE-1003, Huge Supplements — three attachments, and the listing REQUIREMENTS.md quotes
# to show why a file name proves nothing (FR-1.4). The first is named `Inv.png` and the
# other two are screenshots taken thirteen seconds apart whose names are near-identical,
# yet they are different kinds of evidence.
ATTACHMENTS_1003 = attachments_payload(
    attachment_payload(),
    attachment_payload(
        attachment_id="ATT-CASE-1003-02",
        file_name="Screenshot_Feb_26_20-45-24.png",
        url=_blob_url(
            "case-1003/02_Screenshot_at_Feb_26_20-45-24.png",
            "6rXSHnLTJ22A%2FGLnt%2BoNVk9O90RZ%2BlXSSePpLm6NEV0%3D",
        ),
    ),
    attachment_payload(
        attachment_id="ATT-CASE-1003-03",
        file_name="Screenshot_Feb_26_20-45-11.png",
        url=_blob_url(
            "case-1003/03_Screenshot_at_Feb_26_20-45-11.png",
            "YiKIFhiQOvg%2FYBb9kcxEoyjGhS0AnRAX5saMSW9va3I%3D",
        ),
    ),
)

# CASE-1004, Catalyze-X — four images that are never looked at, because the claim is
# turned away for its age before any of them is fetched (FR-0.4, NFR-8). They are here so
# a test can prove that no image was read, which needs images that could have been.
ATTACHMENTS_1004 = attachments_payload(
    attachment_payload(
        attachment_id="ATT-CASE-1004-01",
        file_name="Screenshot_2026-03-10_025020.png",
        url=_blob_url(
            "case-1004/01_Screenshot_2026-03-10_025020.png",
            "NHXsCaMHJL3J9fTdaNaT7gqpjEY4nZofzLxQPU3qZ8s%3D",
        ),
    ),
    attachment_payload(
        attachment_id="ATT-CASE-1004-02",
        file_name="Screenshot_2026-03-10_024959.png",
        url=_blob_url(
            "case-1004/02_Screenshot_2026-03-10_024959.png",
            "Tm2EU3Gk8gBTpcWnjMqkqwbjsXnhO3oDzJXwjZbsv5k%3D",
        ),
    ),
    attachment_payload(
        attachment_id="ATT-CASE-1004-03",
        file_name="Screenshot_2026-03-10_025032.png",
        url=_blob_url(
            "case-1004/03_Screenshot_2026-03-10_025032.png",
            "a37uSnDWR8YYtaZUdACUVc6g98f06KQEeh3EhThQbnw%3D",
        ),
    ),
    attachment_payload(
        attachment_id="ATT-CASE-1004-04",
        file_name="Image_2026-03-10_08-57-31.png",
        # The stored file really does end `.png.png`. That is ShipBob's address, not a
        # slip here, and correcting it would break the link.
        url=_blob_url(
            "case-1004/04_Image_2026-03-10_08-57-31.png.png",
            "3drtlv388Renp8tq7YcH0CI%2FeFTdFgzWf3u3YkyYFc4%3D",
        ),
    ),
)

# CASE-1005, Loam Science — no attachments at all, which is the whole of ShipBob's reply
# and the whole point of this fixture. Every one of the four evidence items is missing, so
# the only possible outcome is a request for information, and the empty listing must reach
# our code as an empty listing rather than as an error (FR-1.6).
ATTACHMENTS_1005 = attachments_payload()

# The invoice for CASE-1001's shipment, priced from CASE-1001's order. This is the reply
# REQUIREMENTS.md quotes in full, plus the `product_id` on each line that the endpoint
# returns and the printed reply leaves out.
INVOICE_342578703 = invoice_from_order(ORDER_1001, shipment_id="342578703")
