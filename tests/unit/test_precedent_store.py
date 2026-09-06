from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

from claim_agent.domain.claim_line import MatchOutcome
from claim_agent.domain.evidence import EvidenceFinding, EvidenceKind, EvidenceState
from claim_agent.domain.outcome import Recommendation
from claim_agent.domain.precedent import PrecedentQuery, PrecedentRecord
from claim_agent.storage.precedent_store import PrecedentStore, all_records

WRITTEN_AT = datetime(2026, 2, 19, 14, 20, 16, 123456, tzinfo=UTC)

CRUSHED_IN_A_BAD_BOX = (
    "Customer received order and product arrived damaged. Both product and shipping box "
    "damaged. Damage due to poor packaging."
)
WRONG_ITEM_ENTIRELY = "The wrong item was sent to the customer. Nothing was broken."


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
        "evidence": (
            EvidenceFinding(
                kind=EvidenceKind.INVOICE, state=EvidenceState.PRESENT, observed="An invoice."
            ),
        ),
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


def a_query(**overrides: Any) -> PrecedentQuery:
    fields: dict[str, Any] = {
        "merchant_account": CRUSHED_IN_A_BAD_BOX,
        "product_name": "Liposomal Tripeptide Collagen",
        "unit_price": Decimal("52.00"),
        "match": MatchOutcome.MATCHED,
    }
    fields.update(overrides)
    return PrecedentQuery(**fields)


def a_store(tmp_path: Path) -> PrecedentStore:
    return PrecedentStore(tmp_path / "claims.db")


def search(store: PrecedentStore, query: PrecedentQuery | None = None, **kwargs: Any) -> Any:
    options: dict[str, Any] = {"limit": 5, "minimum_similarity": 0.35}
    options.update(kwargs)
    return store.similar_to(query or a_query(), **options)


def test_a_captured_claim_comes_back_exactly_as_it_was_written(tmp_path: Path) -> None:
    store = a_store(tmp_path)
    written = a_record()

    store.record(written)

    assert store.get("PREC-CASE-0900-L01") == written


def test_investigating_the_same_line_again_replaces_its_record(tmp_path: Path) -> None:
    store = a_store(tmp_path)
    store.record(a_record(outcome=Recommendation.REQUEST_INFO))

    store.record(a_record(outcome=Recommendation.APPROVE))

    assert len(all_records(tmp_path / "claims.db")) == 1
    stored = store.get("PREC-CASE-0900-L01")
    assert stored is not None
    assert stored.outcome is Recommendation.APPROVE


def test_a_record_nobody_wrote_reads_back_as_nothing(tmp_path: Path) -> None:
    assert a_store(tmp_path).get("PREC-NOTHING") is None


def test_the_note_a_rep_left_is_kept_with_the_record(tmp_path: Path) -> None:
    store = a_store(tmp_path)
    store.record(a_record(rep_note="Paid the ampoule duo only; the collagen was undamaged."))

    stored = store.get("PREC-CASE-0900-L01")
    assert stored is not None
    assert stored.rep_note == "Paid the ampoule duo only; the collagen was undamaged."


def test_the_more_recently_closed_of_two_equally_alike_records_comes_first(
    tmp_path: Path,
) -> None:
    store = a_store(tmp_path)
    store.record(a_record(precedent_id="PREC-OLD", case_id="CASE-OLD", closed_at=WRITTEN_AT))
    store.record(
        a_record(
            precedent_id="PREC-NEW",
            case_id="CASE-NEW",
            closed_at=WRITTEN_AT + timedelta(days=30),
        )
    )

    assert search(store).retrieved[0].record.case_id == "CASE-NEW"


def test_a_similar_past_claim_is_found(tmp_path: Path) -> None:
    store = a_store(tmp_path)
    store.record(a_record())

    result = search(store)

    assert [found.record.case_id for found in result.retrieved] == ["CASE-0900"]
    assert result.was_read is True


def test_a_claim_about_something_else_entirely_is_not_offered_as_precedent(
    tmp_path: Path,
) -> None:
    store = a_store(tmp_path)
    store.record(
        a_record(
            product_name="Red/Black HUGE Shaker",
            unit_price=Decimal("12.99"),
            merchant_account=WRONG_ITEM_ENTIRELY,
        )
    )

    assert search(store).retrieved == ()


def test_only_as_many_records_as_asked_for_come_back(tmp_path: Path) -> None:
    store = a_store(tmp_path)
    for index in range(6):
        store.record(
            a_record(
                precedent_id=f"PREC-{index}", case_id=f"CASE-{index}", claim_line_id=str(index)
            )
        )

    assert len(search(store, limit=2).retrieved) == 2


def test_the_most_alike_record_comes_first(tmp_path: Path) -> None:
    store = a_store(tmp_path)
    store.record(
        a_record(
            precedent_id="PREC-FAR",
            case_id="CASE-FAR",
            product_name="Additional Collagen Ampoule Duo",
            unit_price=Decimal("38.00"),
            merchant_account="Product arrived damaged in a crushed box.",
        )
    )
    store.record(a_record(precedent_id="PREC-NEAR", case_id="CASE-NEAR"))

    assert search(store).retrieved[0].record.case_id == "CASE-NEAR"


def test_two_searches_of_the_same_store_return_the_same_records_in_the_same_order(
    tmp_path: Path,
) -> None:
    store = a_store(tmp_path)
    for index in range(4):
        store.record(
            a_record(
                precedent_id=f"PREC-{index}",
                case_id=f"CASE-{index}",
                closed_at=WRITTEN_AT + timedelta(days=index),
            )
        )

    assert search(store).retrieved == search(store).retrieved


def test_a_claim_never_finds_itself(tmp_path: Path) -> None:
    store = a_store(tmp_path)
    store.record(a_record())

    assert search(store, excluding="PREC-CASE-0900-L01").retrieved == ()


def test_a_search_reports_which_merchant_a_precedent_came_from_but_never_matches_on_it(
    tmp_path: Path,
) -> None:
    store = a_store(tmp_path)
    store.record(a_record(user_id="111111"))

    (result,) = search(store).retrieved

    assert result.record.user_id == "111111"


def test_an_empty_store_reports_finding_nothing_rather_than_failing(tmp_path: Path) -> None:
    result = search(a_store(tmp_path))

    assert result.retrieved == ()
    assert result.was_read is True
    assert result.unavailable_reason is None


def test_a_store_that_cannot_be_read_says_so_instead_of_saying_there_is_nothing(
    tmp_path: Path,
) -> None:
    not_a_database = tmp_path / "claims.db"
    not_a_database.write_text("this is not a database at all")

    result = search(PrecedentStore(not_a_database))

    assert result.retrieved == ()
    assert result.was_read is False
    assert result.unavailable_reason is not None


def test_a_broken_store_never_stops_the_claim(tmp_path: Path) -> None:
    not_a_database = tmp_path / "claims.db"
    not_a_database.write_text("this is not a database at all")

    search(PrecedentStore(not_a_database))


def test_a_claim_with_nothing_to_search_on_is_not_a_failure(tmp_path: Path) -> None:
    result = search(a_store(tmp_path), a_query(merchant_account=None, product_name="1234"))

    assert result.retrieved == ()
    assert result.was_read is True


def test_a_withdrawn_record_is_never_offered_as_precedent_again(tmp_path: Path) -> None:
    store = a_store(tmp_path)
    store.record(a_record())

    assert store.withdraw("PREC-CASE-0900-L01") is True

    assert search(store).retrieved == ()


def test_withdrawing_a_record_does_not_destroy_it(tmp_path: Path) -> None:
    store = a_store(tmp_path)
    store.record(a_record())

    store.withdraw("PREC-CASE-0900-L01")

    still_there = store.get("PREC-CASE-0900-L01")
    assert still_there is not None
    assert still_there.withdrawn is True


def test_withdrawing_a_record_nobody_wrote_says_so_rather_than_failing(tmp_path: Path) -> None:
    assert a_store(tmp_path).withdraw("PREC-NOTHING") is False


def test_a_search_word_that_is_also_a_search_operator_is_treated_as_a_word(
    tmp_path: Path,
) -> None:
    store = a_store(tmp_path)
    store.record(a_record(merchant_account="The parcel arrived damaged AND the box was NOT sealed"))

    result = search(store, a_query(merchant_account="arrived damaged AND NOT sealed box parcel"))

    assert result.was_read is True


def test_a_record_with_no_words_worth_searching_is_stored_but_never_found(
    tmp_path: Path,
) -> None:
    store = a_store(tmp_path)
    store.record(a_record(merchant_account=None, product_name="1234"))

    assert store.get("PREC-CASE-0900-L01") is not None
    assert search(store).retrieved == ()


def test_the_store_is_created_on_first_use_without_anyone_setting_it_up(tmp_path: Path) -> None:
    database = tmp_path / "nested" / "claims.db"

    PrecedentStore(database).record(a_record())

    assert database.exists()
