from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest

from claim_agent.domain.assessment import Assessment, AssessmentName
from claim_agent.domain.claim_line import ClaimedProduct, ClaimLine, MatchOutcome
from claim_agent.domain.evidence import EvidenceFinding, EvidenceKind, EvidenceState
from claim_agent.domain.models import Case, OrderLineItem
from claim_agent.domain.outcome import Recommendation
from claim_agent.domain.precedent import (
    PrecedentQuery,
    PrecedentRecord,
    capture_closed_line,
    meaningful_words,
    precedent_id_for,
    query_for_line,
    similarity,
)
from claim_agent.domain.reimbursement import AmountDerivation

FILED_AT = datetime(2026, 2, 19, 14, 20, 16, tzinfo=UTC)


CRUSHED_IN_A_BAD_BOX = (
    "Shipment ID: 342578703. Customer received order and product arrived damaged. "
    "Both product and shipping box damaged. Damage due to poor/bad packaging. 1 order affected."
)


def a_case(**overrides: Any) -> Case:
    fields: dict[str, Any] = {
        "case_id": "CASE-1001",
        "created_date": FILED_AT,
        "user_id": "334430",
        "description": CRUSHED_IN_A_BAD_BOX,
    }
    fields.update(overrides)
    return Case(**fields)


def a_line(
    name: str = "Liposomal Tripeptide Collagen",
    price: str | None = "52.00",
    *,
    match: MatchOutcome = MatchOutcome.MATCHED,
    claim_line_id: str = "CASE-1001-L01",
) -> ClaimLine:
    order_line = (
        OrderLineItem(product_id="1", name=name, sku="SKU1", quantity=1, unit_price=Decimal(price))
        if price is not None and match is MatchOutcome.MATCHED
        else None
    )
    return ClaimLine(
        claim_line_id=claim_line_id,
        claimed=ClaimedProduct(name=name, quantity=1),
        match=match,
        order_line=order_line,
    )


def a_record(**overrides: Any) -> PrecedentRecord:
    fields: dict[str, Any] = {
        "precedent_id": "PREC-CASE-0900-L01",
        "case_id": "CASE-0900",
        "claim_line_id": "CASE-0900-L01",
        "user_id": "999999",
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
        "closed_at": FILED_AT,
    }
    fields.update(overrides)
    return PrecedentRecord(**fields)


def a_query(**overrides: Any) -> PrecedentQuery:
    fields: dict[str, Any] = {
        "merchant_account": CRUSHED_IN_A_BAD_BOX,
        "product_name": "Liposomal Tripeptide Collagen",
        "unit_price": Decimal("52.00"),
        "match": MatchOutcome.MATCHED,
    }
    fields.update(overrides)
    return PrecedentQuery(**fields)


def found(kind: EvidenceKind, state: EvidenceState) -> EvidenceFinding:
    return EvidenceFinding(kind=kind, state=state, observed="what was seen")


def test_a_closed_line_is_captured_with_the_outcome_it_closed_on() -> None:
    record = capture_closed_line(
        case=a_case(),
        line=a_line(),
        evidence=[found(EvidenceKind.INVOICE, EvidenceState.MISSING)],
        assessments=[],
        outcome=Recommendation.REQUEST_INFO,
        amount=None,
        closed_at=FILED_AT,
    )

    assert record.outcome is Recommendation.REQUEST_INFO
    assert record.case_id == "CASE-1001"
    assert record.claim_line_id == "CASE-1001-L01"


def test_a_record_carries_no_notion_of_being_unreviewed() -> None:
    stored = set(PrecedentRecord.model_fields)

    assert "review_state" not in stored
    assert "authority" not in stored


def test_a_record_keeps_enough_for_a_person_to_judge_whether_two_claims_are_alike() -> None:
    amount = AmountDerivation(
        components=(),
        items_total_usd=Decimal("0.00"),
        proposed_usd=Decimal("120.00"),
        amount_usd=Decimal("100.00"),
        cap_usd=Decimal("100.00"),
        cap_applied=True,
        priced_from="INV-1",
    )
    record = capture_closed_line(
        case=a_case(),
        line=a_line(),
        evidence=[found(EvidenceKind.INVOICE, EvidenceState.PRESENT)],
        assessments=[
            Assessment(
                name=AssessmentName.DAMAGE_VISIBLE,
                passed=True,
                reasoning="The bottle is cracked.",
                confidence=0.9,
            )
        ],
        outcome=Recommendation.APPROVE,
        amount=amount,
        closed_at=FILED_AT,
    )

    assert record.merchant_account == CRUSHED_IN_A_BAD_BOX
    assert record.product_name == "Liposomal Tripeptide Collagen"
    assert record.unit_price == Decimal("52.00")
    assert record.amount_usd == Decimal("100.00")
    assert record.cap_applied is True
    assert record.evidence[0].kind is EvidenceKind.INVOICE
    assert record.assessments[0].name is AssessmentName.DAMAGE_VISIBLE


def test_investigating_the_same_line_twice_names_the_same_record() -> None:
    assert precedent_id_for("CASE-1001-L01") == "PREC-CASE-1001-L01"


def test_a_different_product_at_a_similar_price_is_still_similar() -> None:
    scored = similarity(
        a_query(),
        a_record(
            product_name="Additional Collagen Ampoule Duo",
            unit_price=Decimal("38.00"),
            merchant_account="Product arrived damaged, shipping box crushed by poor packaging.",
        ),
    )

    assert scored.score > 0.35
    assert any("product names share" in reason for reason in scored.reasons)


def test_an_unrelated_claim_scores_far_below_a_related_one() -> None:
    alike = similarity(a_query(), a_record(product_name="Additional Collagen Ampoule Duo"))
    unrelated = similarity(
        a_query(),
        a_record(
            product_name="Red/Black HUGE Shaker",
            unit_price=Decimal("12.99"),
            merchant_account="The wrong item was sent to the customer entirely.",
        ),
    )

    assert unrelated.score < alike.score
    assert unrelated.score < 0.35


def test_the_same_claim_at_a_very_different_price_is_less_alike() -> None:
    same_price = similarity(a_query(), a_record())
    far_dearer = similarity(a_query(), a_record(unit_price=Decimal("499.00")))

    assert far_dearer.score < same_price.score


def test_a_price_nobody_knows_leaves_the_claim_comparable_on_everything_else() -> None:
    priced = similarity(a_query(), a_record())
    unpriced = similarity(a_query(unit_price=None), a_record(unit_price=None))

    assert unpriced.score == pytest.approx(priced.score, abs=0.05)


def test_two_claims_short_of_the_same_evidence_are_alike_in_that() -> None:
    missing_confirmation = (found(EvidenceKind.CUSTOMER_CONFIRMATION, EvidenceState.MISSING),)
    scored = similarity(
        a_query(evidence=missing_confirmation),
        a_record(evidence=missing_confirmation),
    )

    assert any("same evidence was short" in reason for reason in scored.reasons)


def test_two_claims_for_something_never_ordered_are_alike_in_that() -> None:
    scored = similarity(
        a_query(match=MatchOutcome.NOT_ON_ORDER),
        a_record(match=MatchOutcome.NOT_ON_ORDER),
    )

    assert any("on no line of the order" in reason for reason in scored.reasons)


def test_scoring_the_same_pair_twice_gives_the_same_answer() -> None:
    first = similarity(a_query(), a_record())
    second = similarity(a_query(), a_record())

    assert first == second


def test_an_identifier_in_the_description_is_never_what_makes_two_claims_alike() -> None:
    assert "342578703" not in meaningful_words(CRUSHED_IN_A_BAD_BOX)
    assert "damaged" in meaningful_words(CRUSHED_IN_A_BAD_BOX)


def test_a_claim_with_no_description_is_not_thereby_unlike_everything() -> None:
    scored = similarity(a_query(merchant_account=None), a_record())

    assert scored.score > 0.0


def test_the_question_asked_of_the_store_is_built_from_what_is_known_before_the_run() -> None:
    shared = (found(EvidenceKind.INVOICE, EvidenceState.PRESENT),)

    query = query_for_line(case=a_case(), line=a_line(), shared_evidence=shared)

    assert query.merchant_account == CRUSHED_IN_A_BAD_BOX
    assert query.product_name == "Liposomal Tripeptide Collagen"
    assert query.unit_price == Decimal("52.00")
    assert query.evidence == shared


def test_the_question_never_carries_the_merchant_it_came_from() -> None:
    query = query_for_line(case=a_case(), line=a_line())

    assert "user_id" not in query.model_dump()
    assert "case_id" not in query.model_dump()
