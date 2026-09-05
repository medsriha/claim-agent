from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from claim_agent.app import create_app
from claim_agent.domain.claim_line import MatchOutcome
from claim_agent.domain.evidence import EvidenceKind, EvidenceState
from claim_agent.domain.outcome import Recommendation
from claim_agent.domain.precedent import PrecedentRecord
from claim_agent.settings import Settings
from claim_agent.storage.precedent_store import PrecedentStore

WRITTEN_AT = datetime(2026, 2, 19, 14, 20, 16, tzinfo=UTC)

CRUSHED_IN_A_BAD_BOX = (
    "Customer received order and product arrived damaged. Both product and shipping box "
    "damaged. Damage due to poor packaging."
)


def a_record(**overrides: Any) -> PrecedentRecord:
    """One past claim, so a test writes down only the part it is about."""
    fields: dict[str, Any] = {
        "precedent_id": "PREC-CASE-0900-L01",
        "case_id": "CASE-0900",
        "claim_line_id": "CASE-0900-L01",
        "user_id": "283959",
        "product_name": "Liposomal Tripeptide Collagen",
        "sku": "COLLAGEN1",
        "unit_price": Decimal("52.00"),
        "merchant_account": CRUSHED_IN_A_BAD_BOX,
        "match": MatchOutcome.MATCHED,
        "evidence": (),
        "assessments": (),
        "outcome": Recommendation.APPROVE,
        "amount_usd": Decimal("52.00"),
        "cap_applied": False,
        "rep_note": None,
        "withdrawn": False,
        "closed_at": WRITTEN_AT,
    }
    fields.update(overrides)
    return PrecedentRecord(**fields)


@pytest.fixture
def store(settings: Settings) -> PrecedentStore:
    """The store the application will read, on this test's own database file."""
    return PrecedentStore(settings.database_path)


@pytest.fixture
def app(settings: Settings, store: PrecedentStore) -> FastAPI:
    """An application reading the same store the test writes to."""
    return create_app(settings, precedent_store=store)


@pytest.fixture
async def client(app: FastAPI) -> Any:
    """An HTTP client bound to that application, no network involved."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
        yield http


def a_search(**overrides: Any) -> dict[str, Any]:
    """A search body describing a claim much like the record above."""
    body: dict[str, Any] = {
        "merchant_account": CRUSHED_IN_A_BAD_BOX,
        "product_name": "Liposomal Tripeptide Collagen",
        "unit_price": "52.00",
    }
    body.update(overrides)
    return body


# --- Finding claims like this one -------------------------------------------


async def test_a_similar_past_claim_is_returned_with_why_it_is_similar(
    client: AsyncClient, store: PrecedentStore
) -> None:
    """FR-S.4: a caller sees the comparison, not just the verdict, so they can disagree with it."""
    store.record(a_record())

    response = await client.post("/precedent/search", json=a_search())

    assert response.status_code == 200
    body = response.json()
    (found,) = body["retrieved"]
    assert found["record"]["case_id"] == "CASE-0900"
    assert found["similarity"]["score"] > 0.35
    assert found["similarity"]["reasons"]


async def test_a_different_product_at_a_similar_price_still_comes_back(
    client: AsyncClient, store: PrecedentStore
) -> None:
    """FR-S.4: two claims do not have to match on anything to be alike."""
    store.record(
        a_record(
            product_name="Additional Collagen Ampoule Duo",
            unit_price=Decimal("38.00"),
            merchant_account="Product arrived damaged, shipping box crushed by poor packaging.",
        )
    )

    body = (await client.post("/precedent/search", json=a_search())).json()

    assert len(body["retrieved"]) == 1


async def test_a_claim_about_something_else_entirely_is_not_returned(
    client: AsyncClient, store: PrecedentStore
) -> None:
    """FR-S.5: a record that is not close enough does not come back at all."""
    store.record(
        a_record(
            product_name="Red/Black HUGE Shaker",
            unit_price=Decimal("12.99"),
            merchant_account="The wrong item was sent to the customer. Nothing was broken.",
        )
    )

    body = (await client.post("/precedent/search", json=a_search())).json()

    assert body["retrieved"] == []
    assert body["was_read"] is True


async def test_a_search_may_describe_nothing_but_the_damage(
    client: AsyncClient, store: PrecedentStore
) -> None:
    """FR-S.4: every signal is optional, so a description on its own is a valid search."""
    store.record(a_record())

    response = await client.post(
        "/precedent/search", json={"merchant_account": CRUSHED_IN_A_BAD_BOX}
    )

    assert response.status_code == 200
    assert len(response.json()["retrieved"]) == 1


async def test_the_evidence_a_caller_knows_about_shapes_the_search(
    client: AsyncClient, store: PrecedentStore
) -> None:
    """FR-S.4: the pattern of what is missing is part of the shape of a claim."""
    store.record(a_record())

    response = await client.post(
        "/precedent/search",
        json=a_search(evidence={EvidenceKind.INVOICE.value: EvidenceState.MISSING.value}),
    )

    assert response.status_code == 200


async def test_a_caller_may_ask_for_fewer_records_than_the_policy_allows(
    client: AsyncClient, store: PrecedentStore
) -> None:
    """FR-S.5: the policy sets the default; a caller may still narrow it."""
    for index in range(4):
        store.record(a_record(precedent_id=f"PREC-{index}", case_id=f"CASE-{index}"))

    body = (await client.post("/precedent/search", json=a_search(limit=2))).json()

    assert len(body["retrieved"]) == 2


async def test_raising_the_bar_leaves_a_weaker_match_out(
    client: AsyncClient, store: PrecedentStore
) -> None:
    """FR-S.5: how close is close enough is a judgement call, and a caller may override it."""
    store.record(
        a_record(
            product_name="Additional Collagen Ampoule Duo",
            unit_price=Decimal("38.00"),
            merchant_account="Product arrived damaged, shipping box crushed by poor packaging.",
        )
    )

    lenient = await client.post("/precedent/search", json=a_search(minimum_similarity=0.35))
    strict = await client.post("/precedent/search", json=a_search(minimum_similarity=0.9))

    assert len(lenient.json()["retrieved"]) == 1
    assert strict.json()["retrieved"] == []


async def test_the_more_recently_closed_of_two_equally_alike_records_comes_first(
    client: AsyncClient, store: PrecedentStore
) -> None:
    """FR-S.5: every record was decided by a person, so recency is what settles a tie."""
    store.record(a_record(precedent_id="PREC-OLD", case_id="CASE-OLD", closed_at=WRITTEN_AT))
    store.record(
        a_record(
            precedent_id="PREC-NEW",
            case_id="CASE-NEW",
            closed_at=WRITTEN_AT.replace(month=6),
        )
    )

    body = (await client.post("/precedent/search", json=a_search())).json()

    assert body["retrieved"][0]["record"]["case_id"] == "CASE-NEW"


async def test_what_a_claim_closed_on_is_part_of_what_comes_back(
    client: AsyncClient, store: PrecedentStore
) -> None:
    """FR-S.1: the store holds decisions, so the outcome is the thing a caller needs."""
    store.record(a_record())

    body = (await client.post("/precedent/search", json=a_search())).json()

    assert body["retrieved"][0]["record"]["outcome"] == "approve"


# --- Nothing found and nothing readable are different (FR-S.13) --------------


async def test_an_empty_store_answers_with_nothing_found_rather_than_an_error(
    client: AsyncClient,
) -> None:
    """FR-S.13: the ordinary answer for the first claim ever filed."""
    response = await client.post("/precedent/search", json=a_search())

    assert response.status_code == 200
    body = response.json()
    assert body["retrieved"] == []
    assert body["was_read"] is True
    assert body["unavailable_reason"] is None


async def test_a_store_that_cannot_be_read_says_so_rather_than_saying_there_is_nothing(
    settings: Settings,
) -> None:
    """FR-S.13: telling a rep there is no history when nobody looked is worse than silence."""
    settings.database_path.parent.mkdir(parents=True, exist_ok=True)
    settings.database_path.write_text("this is not a database at all")
    app = create_app(settings, precedent_store=PrecedentStore(settings.database_path))

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
        response = await http.post("/precedent/search", json=a_search())

    assert response.status_code == 200
    body = response.json()
    assert body["retrieved"] == []
    assert body["was_read"] is False
    assert body["unavailable_reason"] is not None


# --- Money never travels as a number (FR-1.21, NFR-2) ------------------------


async def test_every_amount_that_comes_back_is_text(
    client: AsyncClient, store: PrecedentStore
) -> None:
    """FR-1.21, NFR-2: money is a string end to end, so it never becomes a float."""
    store.record(a_record())

    record = (await client.post("/precedent/search", json=a_search())).json()["retrieved"][0][
        "record"
    ]

    assert record["unit_price"] == "52.00"
    assert record["amount_usd"] == "52.00"


async def test_a_price_that_is_not_an_amount_is_refused_with_a_complaint(
    client: AsyncClient,
) -> None:
    """FR-1.21: a price silently treated as unknown would drop a signal the caller meant to send."""
    response = await client.post("/precedent/search", json=a_search(unit_price="about fifty"))

    assert response.status_code == 400
    error = response.json()["error"]
    assert error["code"] == "invalid_request"
    assert error["details"]["unit_price"] == "about fifty"


async def test_a_field_the_search_does_not_have_is_refused(client: AsyncClient) -> None:
    """NFR-2: a misspelled field silently ignored would search on less than the caller thought."""
    response = await client.post("/precedent/search", json=a_search(prodcut_name="Collagen"))

    assert response.status_code == 422


# --- Reading one stored claim ------------------------------------------------


async def test_one_past_claim_can_be_read_in_full(
    client: AsyncClient, store: PrecedentStore
) -> None:
    """FR-S.3: a cited precedent has to be checkable, or it carries weight nobody can audit."""
    store.record(a_record())

    response = await client.get("/precedent/PREC-CASE-0900-L01")

    assert response.status_code == 200
    body = response.json()
    assert body["case_id"] == "CASE-0900"
    assert body["merchant_account"] == CRUSHED_IN_A_BAD_BOX
    assert body["outcome"] == "approve"


async def test_a_record_nobody_stored_is_a_404(client: AsyncClient) -> None:
    """NFR-4: a name that is not there is answered plainly, not with an empty record."""
    response = await client.get("/precedent/PREC-NOTHING")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


async def test_a_withdrawn_record_is_gone_from_search_but_can_still_be_read(
    client: AsyncClient, store: PrecedentStore
) -> None:
    """FR-S.14: withdrawal takes a record out of searches without making it uninspectable."""
    store.record(a_record())
    store.withdraw("PREC-CASE-0900-L01")

    searched = (await client.post("/precedent/search", json=a_search())).json()
    read = await client.get("/precedent/PREC-CASE-0900-L01")

    assert searched["retrieved"] == []
    assert read.status_code == 200
    assert read.json()["withdrawn"] is True
