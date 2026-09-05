from __future__ import annotations

from tests.fixtures.shipbob import ORDER_1001, order_line_item

INVOICE_UNAVAILABLE_BODY: dict[str, object] = {
    "error": "invoice_unavailable",
    "message": "No invoice could be generated for the provided shipment.",
}

INVOICE_GENERATED_AT = "2026-03-21T10:00:00.000+0000"

_BLOB_CONTAINER = "https://sa032101pubdevuc.blob.core.windows.net/shipbob-fde-mock"
_BLOB_EXPIRY = "2036-07-26T20%3A59%3A50Z"


def _blob_url(stored_path: str, signature: str) -> str:
    return (
        f"{_BLOB_CONTAINER}/{stored_path}?se={_BLOB_EXPIRY}&sp=r&sv=2021-12-02&sr=b&sig={signature}"
    )


def attachment_payload(**overrides: object) -> dict[str, object]:
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
    return {"attachments": list(attachments)}


def invoice_line_item(**overrides: object) -> dict[str, object]:
    payload = order_line_item()
    payload.update(overrides)
    return payload


def invoice_from_order(order: dict[str, object], *, shipment_id: str) -> dict[str, object]:
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
    payload = invoice_from_order(ORDER_1001, shipment_id="342578703")
    payload.update(overrides)
    return payload


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
        url=_blob_url(
            "case-1004/04_Image_2026-03-10_08-57-31.png.png",
            "3drtlv388Renp8tq7YcH0CI%2FeFTdFgzWf3u3YkyYFc4%3D",
        ),
    ),
)

ATTACHMENTS_1005 = attachments_payload()

INVOICE_342578703 = invoice_from_order(ORDER_1001, shipment_id="342578703")
