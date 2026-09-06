from __future__ import annotations

from claim_agent.domain.evidence import EvidenceFinding, EvidenceKind, EvidenceState
from claim_agent.domain.evidence_sufficiency import assess_evidence_sufficiency


def present(kind: EvidenceKind, observed: str = "looks fine") -> EvidenceFinding:
    return EvidenceFinding(kind=kind, state=EvidenceState.PRESENT, observed=observed)


def missing(kind: EvidenceKind) -> EvidenceFinding:
    return EvidenceFinding(kind=kind, state=EvidenceState.MISSING, observed="not attached")


def unusable(kind: EvidenceKind, problem: str) -> EvidenceFinding:
    return EvidenceFinding(
        kind=kind, state=EvidenceState.UNUSABLE, observed="attached", problem=problem
    )


def unreadable(kind: EvidenceKind, problem: str) -> EvidenceFinding:
    return EvidenceFinding(
        kind=kind, state=EvidenceState.UNREADABLE, observed="attached", problem=problem
    )


ALL_FOUR_PRESENT = tuple(present(kind) for kind in EvidenceKind)


def test_case_1005_zero_attachments_asks_for_all_four_kinds_specifically() -> None:
    result = assess_evidence_sufficiency(())

    assert result.is_supportable is False
    assert set(result.missing_or_unusable) == set(EvidenceKind)
    assert len(result.requests) == 4
    assert result.unreadable == ()
    assert result.needs_rep_clarification is False
    assert "outer box" in " ".join(result.requests)
    assert "damaged product itself" in " ".join(result.requests)


def test_a_request_names_the_thing_specifically_not_more_evidence() -> None:
    result = assess_evidence_sufficiency((missing(EvidenceKind.OUTER_PACKAGING_PHOTO),))

    assert len(result.requests) == 4
    assert any("outer box" in request for request in result.requests)
    for request in result.requests:
        assert "more evidence" not in request.lower()


def test_all_four_present_and_usable_is_supportable() -> None:
    result = assess_evidence_sufficiency(ALL_FOUR_PRESENT)

    assert result.is_supportable is True
    assert result.missing_or_unusable == ()
    assert result.requests == ()
    assert result.unreadable == ()
    assert result.needs_rep_clarification is False
    assert "supportable" in result.reason.lower()


def test_a_kind_missing_from_the_findings_entirely_still_blocks_a_recommendation() -> None:
    three_of_four = tuple(
        present(kind) for kind in EvidenceKind if kind is not EvidenceKind.INVOICE
    )

    result = assess_evidence_sufficiency(three_of_four)

    assert result.is_supportable is False
    assert result.missing_or_unusable == (EvidenceKind.INVOICE,)


def test_unusable_evidence_blocks_a_recommendation_and_names_the_actual_problem() -> None:
    findings = (
        present(EvidenceKind.INVOICE),
        present(EvidenceKind.CUSTOMER_CONFIRMATION),
        unusable(EvidenceKind.DAMAGED_PRODUCT_PHOTO, "too dark to make out any damage"),
        present(EvidenceKind.OUTER_PACKAGING_PHOTO),
    )

    result = assess_evidence_sufficiency(findings)

    assert result.is_supportable is False
    assert result.missing_or_unusable == (EvidenceKind.DAMAGED_PRODUCT_PHOTO,)
    assert "too dark to make out any damage" in result.requests[0]
    assert result.needs_rep_clarification is False


def test_unreadable_evidence_requests_rep_clarification_and_not_the_merchant() -> None:
    findings = (
        present(EvidenceKind.INVOICE),
        present(EvidenceKind.CUSTOMER_CONFIRMATION),
        unreadable(EvidenceKind.DAMAGED_PRODUCT_PHOTO, "the image would not download"),
        present(EvidenceKind.OUTER_PACKAGING_PHOTO),
    )

    result = assess_evidence_sufficiency(findings)

    assert result.is_supportable is False
    assert result.needs_rep_clarification is True
    assert result.unreadable == (EvidenceKind.DAMAGED_PRODUCT_PHOTO,)
    assert result.missing_or_unusable == ()
    assert result.requests == ()
    assert "person" in result.reason.lower()


def test_unusable_and_unreadable_together_are_never_mixed_into_one_list() -> None:
    findings = (
        unusable(EvidenceKind.INVOICE, "too cropped to read the prices"),
        unreadable(EvidenceKind.OUTER_PACKAGING_PHOTO, "the image failed to fetch"),
        present(EvidenceKind.CUSTOMER_CONFIRMATION),
        present(EvidenceKind.DAMAGED_PRODUCT_PHOTO),
    )

    result = assess_evidence_sufficiency(findings)

    assert result.missing_or_unusable == (EvidenceKind.INVOICE,)
    assert result.unreadable == (EvidenceKind.OUTER_PACKAGING_PHOTO,)
    assert result.needs_rep_clarification is True
    assert len(result.requests) == 1
    assert "prices" in result.requests[0]


def test_the_same_findings_produce_the_same_assessment_twice() -> None:
    findings = (missing(EvidenceKind.INVOICE), present(EvidenceKind.CUSTOMER_CONFIRMATION))

    assert assess_evidence_sufficiency(findings) == assess_evidence_sufficiency(findings)
