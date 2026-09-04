"""Gathering precedent before the investigation starts (FR-S.5, FR-S.6, FR-S.13).

The point of these tests is that precedent arrives *with* the claim rather than
being something the model may decide to look up, and that a store which cannot be
read never stops a claim.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from claim_agent.agent.precedent_context import precedent_for_line
from claim_agent.domain.claim_line import ClaimedProduct, ClaimLine, MatchOutcome
from claim_agent.domain.evidence import EvidenceFinding, EvidenceKind, EvidenceState
from claim_agent.domain.models import Case, OrderLineItem
from claim_agent.domain.outcome import Recommendation
from claim_agent.domain.precedent import PrecedentRecord
from claim_agent.policy import Policy
from claim_agent.storage.precedent_store import PrecedentStore

FILED_AT = datetime(2026, 2, 19, 14, 20, 16, tzinfo=UTC)

CRUSHED_IN_A_BAD_BOX = (
    "Customer received order and product arrived damaged. Both product and shipping box "
    "damaged. Damage due to poor packaging."
)


def a_case() -> Case:
    """The claim in hand."""
    return Case(
        case_id="CASE-1001",
        created_date=FILED_AT,
        user_id="334430",
        description=CRUSHED_IN_A_BAD_BOX,
    )


def a_line(claim_line_id: str = "CASE-1001-L01") -> ClaimLine:
    """The one product about to be investigated."""
    return ClaimLine(
        claim_line_id=claim_line_id,
        claimed=ClaimedProduct(name="Liposomal Tripeptide Collagen", quantity=1),
        match=MatchOutcome.MATCHED,
        order_line=OrderLineItem(
            product_id="1",
            name="Liposomal Tripeptide Collagen",
            sku="COLLAGEN1",
            quantity=1,
            unit_price=Decimal("52.00"),
        ),
    )


def a_record(**overrides: Any) -> PrecedentRecord:
    """One past claim much like the one in hand."""
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


def test_the_claim_in_hand_is_given_its_precedent_before_it_is_investigated(
    tmp_path: Path,
) -> None:
    """FR-S.6: precedent arrives with the claim, the way the pre-flight facts do."""
    store = PrecedentStore(tmp_path / "claims.db")
    store.record(a_record())

    found = precedent_for_line(store=store, case=a_case(), line=a_line(), policy=Policy())

    assert [one.record.case_id for one in found.retrieved] == ["CASE-0900"]


def test_the_number_of_records_shown_comes_from_the_policy(tmp_path: Path) -> None:
    """FR-S.5, FR-0.7: how many precedents a run sees is a judgement call, so it is configurable."""
    store = PrecedentStore(tmp_path / "claims.db")
    for index in range(4):
        store.record(a_record(precedent_id=f"PREC-{index}", case_id=f"CASE-{index}"))

    found = precedent_for_line(
        store=store,
        case=a_case(),
        line=a_line(),
        policy=Policy(precedent_results_per_line=2),
    )

    assert len(found.retrieved) == 2


def test_raising_the_bar_for_similarity_leaves_a_weak_match_out(tmp_path: Path) -> None:
    """FR-S.5, FR-0.7: how close is close enough is a judgement call too."""
    resembling_but_not_identical = a_record(
        product_name="Additional Collagen Ampoule Duo",
        unit_price=Decimal("38.00"),
        merchant_account="Product arrived damaged, shipping box crushed by poor packaging.",
    )
    store = PrecedentStore(tmp_path / "claims.db")
    store.record(resembling_but_not_identical)

    lenient = precedent_for_line(
        store=store, case=a_case(), line=a_line(), policy=Policy(min_precedent_similarity=0.35)
    )
    strict = precedent_for_line(
        store=store, case=a_case(), line=a_line(), policy=Policy(min_precedent_similarity=0.9)
    )

    assert len(lenient.retrieved) == 1
    assert strict.retrieved == ()
    assert strict.was_read is True


def test_a_claim_being_investigated_again_does_not_find_its_own_record(tmp_path: Path) -> None:
    """FR-S.5: a claim is not evidence of how claims like it are handled."""
    store = PrecedentStore(tmp_path / "claims.db")
    store.record(a_record(precedent_id="PREC-CASE-1001-L01", claim_line_id="CASE-1001-L01"))

    found = precedent_for_line(store=store, case=a_case(), line=a_line(), policy=Policy())

    assert found.retrieved == ()


def test_what_triage_settled_about_the_evidence_shapes_the_search(tmp_path: Path) -> None:
    """FR-S.5, FR-1a.3: retrieval runs after triage, so it uses what triage found."""
    missing_confirmation = (
        EvidenceFinding(
            kind=EvidenceKind.CUSTOMER_CONFIRMATION,
            state=EvidenceState.MISSING,
            observed="Nothing was sent.",
        ),
    )
    store = PrecedentStore(tmp_path / "claims.db")
    store.record(a_record(evidence=missing_confirmation))

    found = precedent_for_line(
        store=store,
        case=a_case(),
        line=a_line(),
        policy=Policy(),
        shared_evidence=missing_confirmation,
    )

    (one,) = found.retrieved
    assert any("same evidence was short" in reason for reason in one.similarity.reasons)


def test_a_store_that_cannot_be_read_does_not_stop_the_investigation(tmp_path: Path) -> None:
    """FR-S.13, NFR-4: the investigation goes ahead without precedent, and says so."""
    not_a_database = tmp_path / "claims.db"
    not_a_database.write_text("this is not a database at all")

    found = precedent_for_line(
        store=PrecedentStore(not_a_database), case=a_case(), line=a_line(), policy=Policy()
    )

    assert found.was_read is False
    assert found.retrieved == ()


def test_an_empty_store_is_an_ordinary_answer(tmp_path: Path) -> None:
    """FR-S.13: no comparable history is the normal state on the first claim ever filed."""
    found = precedent_for_line(
        store=PrecedentStore(tmp_path / "claims.db"),
        case=a_case(),
        line=a_line(),
        policy=Policy(),
    )

    assert found.retrieved == ()
    assert found.was_read is True
