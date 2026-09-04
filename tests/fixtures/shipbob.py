"""Records shaped like the ShipBob mock API's replies, for tests to work from.

Almost every test needs the same handful of JSON records: a case, its shipment, its
order. They live here once, so that two tests can never disagree about what CASE-1001
looks like, and so that a change in the API's shape is a change in one file.

This module deals in plain dictionaries and strings on purpose. It knows nothing about
the rest of the project, so a test that uses it is checking our code against the shape
of the API rather than against our own idea of that shape.

What is here:

- Builders — `case_payload`, `shipment_payload`, `order_payload`, `order_line_item` —
  each returning one complete, valid record. Any keyword argument replaces the matching
  field, so a test that cares about a single field writes only that field:
  `shipment_payload(is_insured=True)`. `without` drops a field entirely, which is a
  different thing from setting it to nothing.
- The five sample cases ShipBob supplies, `CASE_1001` through `CASE_1005`, each with its
  shipment and its order.
- Four made-up cases, all named `CONSTRUCTED_...`, covering behaviour the five sample
  cases cannot show at all.
- `mock_shipbob`, which serves a chosen set of these records from a stand-in API so that
  a test never reaches the network.

Real values and invented ones — read this before trusting a field
-----------------------------------------------------------------

`shipbob-mock-api.md`, the document holding the full payloads, is not in this repository.
REQUIREMENTS.md quotes parts of it. Everything else here we made up to fill the gaps.
Confusing the two is expensive in both directions: a test that asserts on an invented
value proves nothing, and a test that "corrects" a real value will break against the
real API.

**One rule separates them at a glance: every identifier we invented starts with a 9.**
No identifier quoted in REQUIREMENTS.md does.

Quoted in REQUIREMENTS.md, and therefore trustworthy:

- CASE-1001: every field of the case, of its shipment 342578703, and of its order
  334291211 — including the two line items and their prices.
- CASE-1002: the merchant name CleanBoss, the order id 336431771, that order's three
  line items (name, SKU, quantity, unit price), and the phrase "1 order affected"
  appearing in the case description.
- CASE-1003: the merchant name Huge Supplements, the order id 337761802, that order's
  six line items, and the phrase "Number of affected orders: 2" in the description.
- CASE-1004: the case status "Closed", the merchant name Catalyze-X, and both dates —
  which are 73 days apart and are the worked example for the age gate (FR-0.2).
- CASE-1005: the case status "Waiting on Client".
- All five: the case ids themselves, the claim type "Claim | Damaged in Transit", and an
  uninsured shipment.
- The merchants: the five customer ids 334430, 283959, 373103, 374167 and 398045 all
  exist, and 334430 is CASE-1001's.

Invented by us, so never assert on one as though ShipBob had stated it:

- Which customer id belongs to which case, apart from CASE-1001's 334430.
- Every shipment id, carrier, tracking number and shipment status except CASE-1001's.
- Every delivery date and case creation date except CASE-1001's and CASE-1004's. The
  invented pairs are all less than eight days apart, because REQUIREMENTS.md says every
  case other than CASE-1004 was filed within eight days of delivery.
- Every case description and contact email except CASE-1001's. Invented addresses use
  `example.com`, a reserved domain that cannot receive mail.
- The case status of CASE-1002 and CASE-1003.
- CASE-1005's merchant name — REQUIREMENTS.md never names it.
- The whole order behind CASE-1004 and CASE-1005, line items included: neither is quoted
  anywhere.
- Every product id except CASE-1001's two, and every order creation date except
  CASE-1001's.
- All four `CONSTRUCTED_...` cases, top to bottom.
- The error body `mock_shipbob` returns for a record that is not there. REQUIREMENTS.md
  never shows one.

The constants below are ordinary dictionaries, and Python hands every test the same one.
Read them; never change one in place. A test that needs a variant calls a builder.
"""

from __future__ import annotations

import respx

# Every sample shipment is uninsured and every sample claim is a damage claim, so these
# two values are the same on all five cases (FR-0.2).
DAMAGED_IN_TRANSIT = "Claim | Damaged in Transit"

# The body served when a record is missing. Invented: REQUIREMENTS.md shows error codes
# for other endpoints (`422 invoice_unavailable`, `400 invalid_request`) but never an
# error body for a read, so this follows their shape rather than a quoted example.
NOT_FOUND_BODY: dict[str, object] = {"error": "not_found"}


def case_payload(**overrides: object) -> dict[str, object]:
    """Build one case record — a merchant's claim as ShipBob stores it.

    The defaults are CASE-1001 exactly as REQUIREMENTS.md quotes it (FR-0.1), because it
    is the only case whose every field is written down. A test changes what it cares
    about and leaves the rest alone: `case_payload(sub_category=None)` gives a case whose
    claim type is empty, `case_payload(status="Closed")` a closed one.

    Returns a fresh dictionary each call, so a test may change the result freely.
    """
    payload: dict[str, object] = {
        "case_id": "CASE-1001",
        "status": "New",
        "sub_category": DAMAGED_IN_TRANSIT,
        "description": (
            "Shipment ID: 342578703. Customer received order and product arrived damaged. "
            "Both product and shipping box damaged. Damage due to poor/bad packaging. "
            "1 order affected."
        ),
        "order_id": "334291211",
        "user_id": "334430",
        "shipment_id": "342578703",
        "delivered_date": "2026-02-11T11:36:14.000+0000",
        "contact_email": "sakukreja@shipbob.com",
        "account_name": "Best Paw Nutrition",
        "created_date": "2026-02-19T14:20:16.000+0000",
    }
    payload.update(overrides)
    return payload


def shipment_payload(**overrides: object) -> dict[str, object]:
    """Build one shipment record — how the parcel travelled and whether it was insured.

    The defaults are CASE-1001's shipment 342578703 as REQUIREMENTS.md quotes it. All
    five sample shipments are uninsured, so `shipment_payload(is_insured=True)` is the
    only way to make the insurance gate fire (FR-0.2).

    Returns a fresh dictionary each call.
    """
    payload: dict[str, object] = {
        "shipment_id": "342578703",
        "order_id": "334291211",
        "carrier": "Royal Mail Tracked 48",
        "tracking_number": "XQ607930599GB",
        "status": "Delivered",
        "delivered_date": "2026-02-11T11:36:14.000+0000",
        "is_insured": False,
    }
    payload.update(overrides)
    return payload


def order_line_item(**overrides: object) -> dict[str, object]:
    """Build one line of an order — a product, how many of it, and what each cost.

    The defaults are the first item on CASE-1001's order: one Additional Collagen Ampoule
    Duo at $38.00. Prices are plain numbers, never strings, because that is how the API
    returns them and the reading of them is what tests are checking.

    Returns a fresh dictionary each call.
    """
    payload: dict[str, object] = {
        "product_id": "1374243085",
        "name": "Additional Collagen Ampoule Duo",
        "sku": "AMP1",
        "quantity": 1,
        "unit_price": 38.00,
    }
    payload.update(overrides)
    return payload


def order_payload(**overrides: object) -> dict[str, object]:
    """Build one order record — the products a shipment was meant to contain.

    The defaults are CASE-1001's order 334291211 as REQUIREMENTS.md quotes it: two items
    worth $90.00 together. There is no subtotal, tax, shipping or discount field in this
    schema, so order value is only ever the line items multiplied out and added up
    (FR-0.5).

    Returns a fresh dictionary each call, and a fresh list of line items with it, so a
    test can append to or edit the list without affecting anyone else.
    """
    payload: dict[str, object] = {
        "order_id": "334291211",
        "user_id": "334430",
        "line_items": [
            order_line_item(),
            order_line_item(
                product_id="1309112104",
                name="Liposomal Tripeptide Collagen",
                sku="COLLAGEN1",
                quantity=1,
                unit_price=52.00,
            ),
        ],
        "created_date": "2026-02-07T07:42:48.000+0000",
    }
    payload.update(overrides)
    return payload


def without(payload: dict[str, object], *field_names: str) -> dict[str, object]:
    """Copy a record with some fields dropped out of it altogether.

    A field that is absent is not the same as a field that is present and empty, and the
    difference matters: the pre-flight check for missing key information (FR-0.2) has to
    cope with a case that never carried a shipment id as well as one whose shipment id is
    blank. Passing a keyword to a builder covers the second; this covers the first.

    Names that are not in the record are ignored, so a caller cannot be caught out by a
    field the API dropped. The original is left untouched.
    """
    return {name: value for name, value in payload.items() if name not in field_names}


# ---------------------------------------------------------------------------
# The five sample cases
# ---------------------------------------------------------------------------

# CASE-1001, Best Paw Nutrition. Entirely real: REQUIREMENTS.md quotes this case, its
# shipment and its order in full, which is why they are the builders' defaults.
CASE_1001 = case_payload()
SHIPMENT_1001 = shipment_payload()
ORDER_1001 = order_payload()

# CASE-1002, CleanBoss — the case where it is unclear which product was damaged, because
# the order holds two different 24oz bottles at different prices (FR-1.13).
# Real: the merchant name, the order id 336431771, the three line items exactly as quoted,
# and the phrase "1 order affected" in the description.
# Invented: the status, the customer id (the number exists; pairing it with this case does
# not), the shipment id and everything on the shipment, both dates, the contact email, the
# wording of the description around that phrase, and the product ids.
CASE_1002 = case_payload(
    case_id="CASE-1002",
    status="New",
    description=(
        "Shipment ID: 900000002. Customer received order and product arrived damaged. "
        "1 order affected."
    ),
    order_id="336431771",
    user_id="283959",
    shipment_id="900000002",
    delivered_date="2026-02-18T09:14:22.000+0000",
    contact_email="claims@cleanboss.example.com",
    account_name="CleanBoss",
    created_date="2026-02-21T16:03:45.000+0000",
)
SHIPMENT_1002 = shipment_payload(
    shipment_id="900000002",
    order_id="336431771",
    carrier="USPS Priority Mail",
    tracking_number="TRK900000002",
    delivered_date="2026-02-18T09:14:22.000+0000",
)
ORDER_1002 = order_payload(
    order_id="336431771",
    user_id="283959",
    line_items=[
        order_line_item(
            product_id="920000021",
            name="CleanBoss Botanical Disinfectant & Cleaner 24oz 2 Pack",
            sku="A00360",
            quantity=1,
            unit_price=24.99,
        ),
        order_line_item(
            product_id="920000022",
            name="CleanBoss Multi Surface Cleaner 24oz",
            sku="A00300",
            quantity=2,
            unit_price=12.99,
        ),
        order_line_item(
            product_id="920000023",
            name="CleanBoss Foaming Cleaning Wipes 70 pack",
            sku="A00299",
            quantity=1,
            unit_price=14.99,
        ),
    ],
    created_date="2026-02-14T10:05:11.000+0000",
)

# CASE-1003, Huge Supplements — six products, and the only sample claim that can reach the
# $100 reimbursement cap, since its two dearest items come to $109.98 (FR-1.20).
# Real: the merchant name, the order id 337761802, all six line items as quoted, and the
# phrase "Number of affected orders: 2" in the description.
# Invented: everything else, as for CASE-1002. The dates are set around late February
# because this case's attachments are named "Screenshot_at_Feb_26...".
CASE_1003 = case_payload(
    case_id="CASE-1003",
    status="New",
    description=(
        "Shipment ID: 900000003. Customer received order and products arrived damaged. "
        "Number of affected orders: 2."
    ),
    order_id="337761802",
    user_id="373103",
    shipment_id="900000003",
    delivered_date="2026-02-25T15:47:09.000+0000",
    contact_email="claims@hugesupplements.example.com",
    account_name="Huge Supplements",
    created_date="2026-03-01T10:12:33.000+0000",
)
SHIPMENT_1003 = shipment_payload(
    shipment_id="900000003",
    order_id="337761802",
    carrier="FedEx Ground",
    tracking_number="TRK900000003",
    delivered_date="2026-02-25T15:47:09.000+0000",
)
ORDER_1003 = order_payload(
    order_id="337761802",
    user_id="373103",
    line_items=[
        order_line_item(
            product_id="920000031",
            name="Bomb Popsicle Wrecked Pre-Workout",
            sku="0041",
            quantity=1,
            unit_price=49.99,
        ),
        order_line_item(
            product_id="920000032",
            name="Blue Razz Liquid Carnitine",
            sku="0199",
            quantity=1,
            unit_price=34.99,
        ),
        order_line_item(
            product_id="920000033",
            name="Red/Black HUGE Shaker",
            sku="0157",
            quantity=1,
            unit_price=12.99,
        ),
        order_line_item(
            product_id="920000034",
            name="2.5LBS White Chocolate Raspberry Huge Whey",
            sku="0159",
            quantity=1,
            unit_price=59.99,
        ),
        order_line_item(
            product_id="920000035",
            name="Green Apple Wrecked Core Sample",
            sku="0180",
            quantity=1,
            unit_price=9.99,
        ),
        order_line_item(
            product_id="920000036",
            name="Unflavored Liquid Glycerol",
            sku="0179",
            quantity=1,
            unit_price=27.99,
        ),
    ],
    created_date="2026-02-21T13:38:02.000+0000",
)

# CASE-1004, Catalyze-X — the age-gate example. Delivered 26 December, opened 9 March:
# 73 days, well past any reasonable limit, so the claim is turned away before the agent
# runs and its four attachments are never looked at (FR-0.4, NFR-8).
# Real: the status "Closed", the merchant name, and both dates. Those dates are the whole
# point of this case; do not adjust them.
# Invented: everything else, order and shipment included — REQUIREMENTS.md quotes neither.
CASE_1004 = case_payload(
    case_id="CASE-1004",
    status="Closed",
    description=(
        "Shipment ID: 900000004. Customer received order and product arrived damaged. "
        "1 order affected."
    ),
    order_id="910000004",
    user_id="374167",
    shipment_id="900000004",
    delivered_date="2025-12-26T12:13:36.000+0000",
    contact_email="claims@catalyze-x.example.com",
    account_name="Catalyze-X",
    created_date="2026-03-09T18:51:42.000+0000",
)
SHIPMENT_1004 = shipment_payload(
    shipment_id="900000004",
    order_id="910000004",
    carrier="UPS Ground",
    tracking_number="TRK900000004",
    delivered_date="2025-12-26T12:13:36.000+0000",
)
ORDER_1004 = order_payload(
    order_id="910000004",
    user_id="374167",
    line_items=[
        order_line_item(
            product_id="920000041",
            name="Catalyze-X Daily Enzyme Complex",
            sku="CX-100",
            quantity=1,
            unit_price=42.50,
        ),
        order_line_item(
            product_id="920000042",
            name="Catalyze-X Travel Case",
            sku="CX-200",
            quantity=1,
            unit_price=18.00,
        ),
    ],
    created_date="2025-12-20T09:05:44.000+0000",
)

# CASE-1005 — the case with no evidence at all. It has zero attachments and its status is
# already "Waiting on Client", so the only possible outcome is a request for information
# (FR-1.6). An empty attachment list must not be treated as an error.
# Real: the status "Waiting on Client".
# Invented: everything else, the merchant name included — REQUIREMENTS.md never names this
# merchant, and never quotes its order or its shipment.
CASE_1005 = case_payload(
    case_id="CASE-1005",
    status="Waiting on Client",
    description=(
        "Shipment ID: 900000005. Customer says the product arrived damaged. 1 order affected."
    ),
    order_id="910000005",
    user_id="398045",
    shipment_id="900000005",
    delivered_date="2026-03-02T08:21:55.000+0000",
    contact_email="claims@northwind-naturals.example.com",
    account_name="Northwind Naturals",
    created_date="2026-03-06T12:44:07.000+0000",
)
SHIPMENT_1005 = shipment_payload(
    shipment_id="900000005",
    order_id="910000005",
    carrier="DHL Express",
    tracking_number="TRK900000005",
    delivered_date="2026-03-02T08:21:55.000+0000",
)
ORDER_1005 = order_payload(
    order_id="910000005",
    user_id="398045",
    line_items=[
        order_line_item(
            product_id="920000051",
            name="Northwind Elderberry Syrup 8oz",
            sku="NW-880",
            quantity=2,
            unit_price=21.50,
        ),
    ],
    created_date="2026-02-26T11:19:37.000+0000",
)


# ---------------------------------------------------------------------------
# Constructed cases — none of this data came from ShipBob
# ---------------------------------------------------------------------------
# Three pre-flight behaviours cannot be shown on the sample data at all, because every
# sample case is an uninsured damage claim under $200. Each one below exists to make one
# of those behaviours reachable. Every field is invented, and the case ids start at
# CASE-9001 so nobody mistakes them for cases ShipBob supplied.

# An insured shipment. Insured claims follow a different process entirely and must be
# routed away rather than investigated (FR-0.2, gate 4). All five sample shipments are
# uninsured, so without this the gate could never fire in a test.
CONSTRUCTED_INSURED_CASE = case_payload(
    case_id="CASE-9001",
    description=(
        "Shipment ID: 990000001. Customer received order and product arrived damaged. "
        "1 order affected."
    ),
    order_id="990000001",
    user_id="990000001",
    shipment_id="990000001",
    delivered_date="2026-03-02T10:00:00.000+0000",
    contact_email="claims@constructed-insured.example.com",
    account_name="Constructed Insured Merchant",
    created_date="2026-03-04T10:00:00.000+0000",
)
CONSTRUCTED_INSURED_SHIPMENT = shipment_payload(
    shipment_id="990000001",
    order_id="990000001",
    carrier="UPS Ground",
    tracking_number="TRK990000001",
    delivered_date="2026-03-02T10:00:00.000+0000",
    is_insured=True,
)
CONSTRUCTED_INSURED_ORDER = order_payload(
    order_id="990000001",
    user_id="990000001",
    created_date="2026-02-27T10:00:00.000+0000",
)

# A claim that is not a damage claim. Only damaged-in-transit claims are handled here
# (FR-0.2, gate 2), and every sample case is one, so the wrong-type path needs a case of
# its own.
CONSTRUCTED_LOST_IN_TRANSIT_CASE = case_payload(
    case_id="CASE-9002",
    sub_category="Claim | Lost in Transit",
    description="Shipment ID: 990000002. Customer never received the order.",
    order_id="990000002",
    user_id="990000002",
    shipment_id="990000002",
    delivered_date="2026-03-02T10:00:00.000+0000",
    contact_email="claims@constructed-lost.example.com",
    account_name="Constructed Lost Merchant",
    created_date="2026-03-04T10:00:00.000+0000",
)
CONSTRUCTED_LOST_IN_TRANSIT_SHIPMENT = shipment_payload(
    shipment_id="990000002",
    order_id="990000002",
    carrier="UPS Ground",
    tracking_number="TRK990000002",
    delivered_date="2026-03-02T10:00:00.000+0000",
)
CONSTRUCTED_LOST_IN_TRANSIT_ORDER = order_payload(
    order_id="990000002",
    user_id="990000002",
    created_date="2026-02-27T10:00:00.000+0000",
)

# A claim type that begins with the handled one and is still a different thing. Matching
# claim type by "starts with" would let this through, and an insured claim must never be
# processed here (FR-0.2, gates 2 and 4). It is the trap case for that check.
CONSTRUCTED_INSURED_SUBCATEGORY_CASE = case_payload(
    case_id="CASE-9003",
    sub_category="Claim | Damaged in Transit - Insured",
    description=(
        "Shipment ID: 990000003. Customer received order and product arrived damaged. "
        "1 order affected."
    ),
    order_id="990000003",
    user_id="990000003",
    shipment_id="990000003",
    delivered_date="2026-03-02T10:00:00.000+0000",
    contact_email="claims@constructed-subcategory.example.com",
    account_name="Constructed Subcategory Merchant",
    created_date="2026-03-04T10:00:00.000+0000",
)
CONSTRUCTED_INSURED_SUBCATEGORY_SHIPMENT = shipment_payload(
    shipment_id="990000003",
    order_id="990000003",
    carrier="UPS Ground",
    tracking_number="TRK990000003",
    delivered_date="2026-03-02T10:00:00.000+0000",
)
CONSTRUCTED_INSURED_SUBCATEGORY_ORDER = order_payload(
    order_id="990000003",
    user_id="990000003",
    created_date="2026-02-27T10:00:00.000+0000",
)

# An order worth $600.00, which is above the high-value mark a rep is warned about
# (FR-0.5). The dearest sample order is CASE-1003's at $195.94, so no sample case can
# raise the flag. The threshold itself is a provisional judgement call and lives in the
# policy configuration: if it is ever set above $600 this order stops being high value and
# has to grow with it.
CONSTRUCTED_HIGH_VALUE_CASE = case_payload(
    case_id="CASE-9004",
    description=(
        "Shipment ID: 990000004. Customer received order and product arrived damaged. "
        "1 order affected."
    ),
    order_id="990000004",
    user_id="990000004",
    shipment_id="990000004",
    delivered_date="2026-03-02T10:00:00.000+0000",
    contact_email="claims@constructed-high-value.example.com",
    account_name="Constructed High Value Merchant",
    created_date="2026-03-04T10:00:00.000+0000",
)
CONSTRUCTED_HIGH_VALUE_SHIPMENT = shipment_payload(
    shipment_id="990000004",
    order_id="990000004",
    carrier="UPS Ground",
    tracking_number="TRK990000004",
    delivered_date="2026-03-02T10:00:00.000+0000",
)
CONSTRUCTED_HIGH_VALUE_ORDER = order_payload(
    order_id="990000004",
    user_id="990000004",
    line_items=[
        order_line_item(
            product_id="990000041",
            name="Constructed Premium Serum 100ml",
            sku="HV-001",
            quantity=3,
            unit_price=180.00,
        ),
        order_line_item(
            product_id="990000042",
            name="Constructed Gift Box",
            sku="HV-002",
            quantity=1,
            unit_price=60.00,
        ),
    ],
    created_date="2026-02-27T10:00:00.000+0000",
)


# ---------------------------------------------------------------------------
# Serving the records from a stand-in API
# ---------------------------------------------------------------------------


def mock_shipbob(
    router: respx.Router,
    *,
    case: dict[str, object],
    shipment: dict[str, object] | None = None,
    order: dict[str, object] | None = None,
    shipment_status: int = 200,
    order_status: int = 200,
) -> None:
    """Answer the three pre-flight reads with the records given, so no request leaves.

    Pre-flight reads a case, then the shipment and order the case points at (FR-0.1).
    This registers all three addresses on a stand-in API, taking the shipment and order
    ids from the case itself — the same way the real code finds them.

    Leaving out the shipment or the order, or asking for a status other than 200, serves
    that address as an error instead, which is how a test exercises a record that is not
    there or an API having a bad day (NFR-6). The case itself is always served, since
    without it there is nothing to look up.

    Args:
        router: The stand-in API to register on. The `shipbob` fixture in `conftest.py`
            supplies one already pointed at the address the settings use.
        case: The case record, which must carry a `case_id`.
        shipment: The shipment record, or nothing to serve that address as missing.
        order: The order record, or nothing to serve that address as missing.
        shipment_status: Status to answer the shipment read with. Anything but 200 is an
            error response.
        order_status: The same, for the order read.

    Nothing is registered for an address the case does not name: a case with no shipment
    id has no shipment address to answer on, and a request that escapes to one is meant
    to fail loudly.
    """
    router.get(f"/cases/{case['case_id']}").respond(200, json=case)

    shipment_id = case.get("shipment_id") or (shipment or {}).get("shipment_id")
    if shipment_id is not None:
        _serve(router, f"/shipments/{shipment_id}", shipment, shipment_status)

    order_id = case.get("order_id") or (order or {}).get("order_id")
    if order_id is not None:
        _serve(router, f"/orders/{order_id}", order, order_status)


def _serve(
    router: respx.Router,
    path: str,
    payload: dict[str, object] | None,
    status_code: int,
) -> None:
    """Register one address on the stand-in API, with a record or with an error.

    A record and a status of 200 serve the record. Anything else — no record, or a status
    the caller asked for — serves an error body instead, defaulting to 404 when the record
    is simply absent.
    """
    if payload is not None and status_code == 200:
        router.get(path).respond(200, json=payload)
        return

    error_status = status_code if status_code != 200 else 404
    router.get(path).respond(error_status, json=NOT_FOUND_BODY)
