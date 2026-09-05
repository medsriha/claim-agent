from __future__ import annotations

import respx

DAMAGED_IN_TRANSIT = "Claim | Damaged in Transit"

CASE_NOT_FOUND_BODY: dict[str, object] = {
    "error": "case_not_found",
    "message": "No case found with the provided ID.",
}
SHIPMENT_NOT_FOUND_BODY: dict[str, object] = {
    "error": "shipment_not_found",
    "message": "No shipment found with the provided ID.",
}
ORDER_NOT_FOUND_BODY: dict[str, object] = {
    "error": "order_not_found",
    "message": "No order found with the provided ID.",
}

NOT_FOUND_BODY: dict[str, object] = CASE_NOT_FOUND_BODY


def case_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "case_id": "CASE-1001",
        "case_number": "01838218",
        "status": "New",
        "origin": "Case Portal - Claim",
        "sub_category": DAMAGED_IN_TRANSIT,
        "subject": "ShipBob Claim",
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
    return {name: value for name, value in payload.items() if name not in field_names}


CASE_1001 = case_payload()
SHIPMENT_1001 = shipment_payload()
ORDER_1001 = order_payload()

CASE_1002 = case_payload(
    case_id="CASE-1002",
    case_number="01838273",
    status="New",
    description=(
        "Shipment ID: 344745459. Date of Last Carrier Tracking: February 22, 2026. "
        "Carrier: Other. Damaged. Damage Type: Damage due to poor/bad packaging. "
        "Defect Type: Both product and shipping box damaged. Number of affected orders: 1."
    ),
    order_id="336431771",
    user_id="283959",
    shipment_id="344745459",
    delivered_date="2026-02-22T17:40:30.000+0000",
    contact_email="mtaparia@shipbob.com",
    account_name="CleanBoss",
    created_date="2026-02-26T18:20:11.000+0000",
)
SHIPMENT_1002 = shipment_payload(
    shipment_id="344745459",
    order_id="336431771",
    carrier="CirroECommerce",
    tracking_number="CR000441735725",
    delivered_date="2026-02-22T17:40:30.000+0000",
)
ORDER_1002 = order_payload(
    order_id="336431771",
    user_id="283959",
    line_items=[
        order_line_item(
            product_id="897092060",
            name="CleanBoss Botanical Disinfectant & Cleaner 24oz 2 Pack",
            sku="A00360",
            quantity=1,
            unit_price=24.99,
        ),
        order_line_item(
            product_id="897518713",
            name="CleanBoss Multi Surface Cleaner 24oz",
            sku="A00300",
            quantity=2,
            unit_price=12.99,
        ),
        order_line_item(
            product_id="1377567317",
            name="CleanBoss Foaming Cleaning Wipes 70 pack",
            sku="A00299",
            quantity=1,
            unit_price=14.99,
        ),
    ],
    created_date="2026-02-16T02:23:01.000+0000",
)

CASE_1003 = case_payload(
    case_id="CASE-1003",
    case_number="01838282",
    status="New",
    description=(
        "Shipment ID: 346106093. Date of Last Carrier Tracking: February 24, 2026. "
        "Carrier: Other. Damaged. Damage Type: Damage due to carrier mishandling. "
        "Number of affected orders: 2."
    ),
    order_id="337761802",
    user_id="373103",
    shipment_id="346106093",
    delivered_date="2026-02-25T21:51:46.000+0000",
    contact_email="sakukreja+4@shipbob.com",
    account_name="Huge Supplements",
    created_date="2026-02-26T18:20:11.000+0000",
)
SHIPMENT_1003 = shipment_payload(
    shipment_id="346106093",
    order_id="337761802",
    carrier="USPS",
    tracking_number="9234690244541403638849",
    delivered_date="2026-02-25T21:51:46.000+0000",
)
ORDER_1003 = order_payload(
    order_id="337761802",
    user_id="373103",
    line_items=[
        order_line_item(
            product_id="101786572",
            name="Bomb Popsicle Wrecked Pre-Workout",
            sku="0041",
            quantity=1,
            unit_price=49.99,
        ),
        order_line_item(
            product_id="1303441538",
            name="Blue Razz Liquid Carnitine",
            sku="0199",
            quantity=1,
            unit_price=34.99,
        ),
        order_line_item(
            product_id="101786630",
            name="Red/Black HUGE Shaker",
            sku="0157",
            quantity=1,
            unit_price=12.99,
        ),
        order_line_item(
            product_id="101786566",
            name="2.5LBS White Chocolate Raspberry Huge Whey",
            sku="0159",
            quantity=1,
            unit_price=59.99,
        ),
        order_line_item(
            product_id="196409482",
            name="Green Apple Wrecked Core Sample",
            sku="0180",
            quantity=1,
            unit_price=9.99,
        ),
        order_line_item(
            product_id="136125958",
            name="Unflavored Liquid Glycerol",
            sku="0179",
            quantity=1,
            unit_price=27.99,
        ),
    ],
    created_date="2026-02-21T02:08:41.000+0000",
)

CASE_1004 = case_payload(
    case_id="CASE-1004",
    case_number="02564294",
    status="Closed",
    description=(
        "Shipment ID: 330936165. Date of Last Carrier Tracking: March 6, 2026. "
        "Carrier: Other. Damaged. Damage Type: Damage due to poor/bad packaging. "
        "Defect Type: Product damaged, but shipping box is intact. "
        "Number of affected orders: 1."
    ),
    order_id="322882110",
    user_id="374167",
    shipment_id="330936165",
    delivered_date="2025-12-26T12:13:36.000+0000",
    contact_email="sakukreja+6@shipbob.com",
    account_name="Catalyze-X",
    created_date="2026-03-09T18:51:42.000+0000",
)
SHIPMENT_1004 = shipment_payload(
    shipment_id="330936165",
    order_id="322882110",
    carrier="CirroECommerce",
    tracking_number="CR000498369287",
    delivered_date="2025-12-26T12:13:36.000+0000",
)
ORDER_1004 = order_payload(
    order_id="322882110",
    user_id="374167",
    line_items=[
        order_line_item(
            product_id="897531023",
            name="Organic Castor Oil Roll-on with Frankincense",
            sku="HG-FRCAST-KITTEDROLL",
            quantity=1,
            unit_price=24.99,
        ),
    ],
    created_date="2025-12-22T16:24:28.000+0000",
)

CASE_1005 = case_payload(
    case_id="CASE-1005",
    case_number="02584387",
    status="Waiting on Client",
    description=(
        "Shipment ID: 349164073. Date of Last Carrier Tracking: March 10, 2026. "
        "Carrier: Other. Damaged. Damage Type: Damage due to carrier mishandling. "
        "Number of affected orders: 1."
    ),
    order_id="340775987",
    user_id="398045",
    shipment_id="349164073",
    delivered_date="2026-03-10T22:54:36.000+0000",
    contact_email="sakukreja+5@shipbob.com",
    account_name="Loam Science",
    created_date="2026-03-18T17:52:59.000+0000",
)
SHIPMENT_1005 = shipment_payload(
    shipment_id="349164073",
    order_id="340775987",
    carrier="UniUni",
    tracking_number="UUS6342760220893606",
    delivered_date="2026-03-10T22:54:36.000+0000",
)
ORDER_1005 = order_payload(
    order_id="340775987",
    user_id="398045",
    line_items=[
        order_line_item(
            product_id="1130664154",
            name="30-day Pouch LOAM Prebiotic Fiber Formula",
            sku="LOAM-30DAY-001",
            quantity=1,
            unit_price=45.00,
        ),
        order_line_item(
            product_id="1374224271",
            name="Insert Card",
            sku="Health Grows Here - Insert",
            quantity=1,
            unit_price=0.00,
        ),
    ],
    created_date="2026-03-04T03:59:08.000+0000",
)


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


CONSTRUCTED_REPEAT_MERCHANT_CASE = case_payload(
    case_id="CASE-9005",
    description=(
        "Shipment ID: 990000005. Customer received order and product arrived damaged. "
        "Bottle cracked in transit and leaked over the rest of the box. 1 order affected."
    ),
    order_id="990000005",
    user_id="334430",
    shipment_id="990000005",
    delivered_date="2026-03-14T09:20:00.000+0000",
    contact_email="sakukreja@shipbob.com",
    account_name="Best Paw Nutrition",
    created_date="2026-03-18T11:05:00.000+0000",
)
CONSTRUCTED_REPEAT_MERCHANT_SHIPMENT = shipment_payload(
    shipment_id="990000005",
    order_id="990000005",
    carrier="Royal Mail Tracked 48",
    tracking_number="TRK990000005",
    delivered_date="2026-03-14T09:20:00.000+0000",
)
CONSTRUCTED_REPEAT_MERCHANT_ORDER = order_payload(
    order_id="990000005",
    user_id="334430",
    line_items=[
        order_line_item(
            product_id="990000051",
            name="Marine Collagen Peptides 250g",
            sku="PEPT1",
            quantity=1,
            unit_price=44.00,
        ),
        order_line_item(
            product_id="990000052",
            name="Additional Collagen Ampoule Duo",
            sku="AMP1",
            quantity=2,
            unit_price=38.00,
        ),
    ],
    created_date="2026-03-10T08:00:00.000+0000",
)


def mock_shipbob(
    router: respx.Router,
    *,
    case: dict[str, object],
    shipment: dict[str, object] | None = None,
    order: dict[str, object] | None = None,
    shipment_status: int = 200,
    order_status: int = 200,
) -> None:
    router.get(f"/cases/{case['case_id']}").respond(200, json=case)

    shipment_id = case.get("shipment_id") or (shipment or {}).get("shipment_id")
    if shipment_id is not None:
        _serve(
            router,
            f"/shipments/{shipment_id}",
            shipment,
            shipment_status,
            SHIPMENT_NOT_FOUND_BODY,
        )

    order_id = case.get("order_id") or (order or {}).get("order_id")
    if order_id is not None:
        _serve(router, f"/orders/{order_id}", order, order_status, ORDER_NOT_FOUND_BODY)


def _serve(
    router: respx.Router,
    path: str,
    payload: dict[str, object] | None,
    status_code: int,
    missing_body: dict[str, object],
) -> None:
    if payload is not None and status_code == 200:
        router.get(path).respond(200, json=payload)
        return

    error_status = status_code if status_code != 200 else 404
    router.get(path).respond(error_status, json=missing_body)
