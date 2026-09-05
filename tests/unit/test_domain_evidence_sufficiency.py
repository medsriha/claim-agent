"""Whether the evidence gathered so far can support a recommendation, and what to ask for.

CASE-1005 anchors the empty-evidence tests: it has zero attachments and is already
"Waiting on Client", so the right output is a specific request for all four kinds, not a
priced verdict. The rest of the tests focus on the distinction `agent/tools.py`'s module
docstring draws and this module is built to protect: evidence the merchant can still send
again, versus evidence *we* failed to read, which must never be asked of them.
"""

from __future__ import annotations

from claim_agent.domain.evidence import EvidenceFinding, EvidenceKind, EvidenceState
from claim_agent.domain.evidence_sufficiency import assess_evidence_sufficiency


def present(kind: EvidenceKind, observed: str = "looks fine") -> EvidenceFinding:
    """A finding for a piece of evidence that was found and can be relied on."""
    return EvidenceFinding(kind=kind, state=EvidenceState.PRESENT, observed=observed)


def missing(kind: EvidenceKind) -> EvidenceFinding:
    """A finding for a piece of evidence nobody sent."""
    return EvidenceFinding(kind=kind, state=EvidenceState.MISSING, observed="not attached")


def unusable(kind: EvidenceKind, problem: str) -> EvidenceFinding:
    """A finding for evidence the merchant sent, that cannot support a conclusion."""
    return EvidenceFinding(
        kind=kind, state=EvidenceState.UNUSABLE, observed="attached", problem=problem
    )


def unreadable(kind: EvidenceKind, problem: str) -> EvidenceFinding:
    """A finding for evidence we could not fetch or analyse ourselves."""
    return EvidenceFinding(
        kind=kind, state=EvidenceState.UNREADABLE, observed="attached", problem=problem
    )


ALL_FOUR_PRESENT = tuple(present(kind) for kind in EvidenceKind)


# ---------------------------------------------------------------------------
# CASE-1005: zero attachments
# ---------------------------------------------------------------------------


def test_case_1005_zero_attachments_asks_for_all_four_kinds_specifically() -> None:
    """CASE-1005 has no attachments at all — nothing was even looked for, let alone found.

    The right answer is a specific request for every one of the four kinds, not a vague
    "insufficient evidence" and not a priced verdict on nothing.
    """
    result = assess_evidence_sufficiency(())

    assert result.is_supportable is False
    assert set(result.missing_or_unusable) == set(EvidenceKind)
    assert len(result.requests) == 4
    assert result.unreadable == ()
    assert result.needs_escalation is False
    assert "outer box" in " ".join(result.requests)
    assert "damaged product itself" in " ".join(result.requests)


def test_a_request_names_the_thing_specifically_not_more_evidence() -> None:
    """Every request has to be sendable as-is — named, not vague.

    A kind nobody reported on is missing just like one reported as unusable, so naming a
    single finding asks about the other three as well. That is deliberate: silence about
    a kind of evidence is not the same as having it.
    """
    result = assess_evidence_sufficiency((missing(EvidenceKind.OUTER_PACKAGING_PHOTO),))

    assert len(result.requests) == 4
    assert any("outer box" in request for request in result.requests)
    for request in result.requests:
        assert "more evidence" not in request.lower()


# ---------------------------------------------------------------------------
# Everything present: a recommendation is supportable
# ---------------------------------------------------------------------------


def test_all_four_present_and_usable_is_supportable() -> None:
    """The ordinary, complete case: nothing to ask for, nothing to escalate."""
    result = assess_evidence_sufficiency(ALL_FOUR_PRESENT)

    assert result.is_supportable is True
    assert result.missing_or_unusable == ()
    assert result.requests == ()
    assert result.unreadable == ()
    assert result.needs_escalation is False
    assert "supportable" in result.reason.lower()


def test_a_kind_missing_from_the_findings_entirely_still_blocks_a_recommendation() -> None:
    """A kind that is simply absent from the findings counts as missing, the same way
    `evidence.py`'s own helpers already treat it — nobody has to remember to also record
    the negative case.
    """
    three_of_four = tuple(
        present(kind) for kind in EvidenceKind if kind is not EvidenceKind.INVOICE
    )

    result = assess_evidence_sufficiency(three_of_four)

    assert result.is_supportable is False
    assert result.missing_or_unusable == (EvidenceKind.INVOICE,)


# ---------------------------------------------------------------------------
# Unusable evidence: the merchant's gap, and they can be asked again (FR-1.5, FR-1.7)
# ---------------------------------------------------------------------------


def test_unusable_evidence_blocks_a_recommendation_and_names_the_actual_problem() -> None:
    """A blurry photo is not "missing", but it still cannot support a conclusion, and the
    request should say what was actually wrong with what was sent.
    """
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
    assert result.needs_escalation is False


# ---------------------------------------------------------------------------
# Unreadable evidence: our fault, and the merchant must never be asked for it (NFR-4)
# ---------------------------------------------------------------------------


def test_unreadable_evidence_escalates_and_is_never_added_to_the_merchant_request() -> None:
    """The distinction this module exists to protect: an image *we* could not read is not
    the merchant's problem to fix, so it must appear in `unreadable` and escalate, and
    must never show up in `missing_or_unusable` or `requests`.
    """
    findings = (
        present(EvidenceKind.INVOICE),
        present(EvidenceKind.CUSTOMER_CONFIRMATION),
        unreadable(EvidenceKind.DAMAGED_PRODUCT_PHOTO, "the image would not download"),
        present(EvidenceKind.OUTER_PACKAGING_PHOTO),
    )

    result = assess_evidence_sufficiency(findings)

    assert result.is_supportable is False
    assert result.needs_escalation is True
    assert result.unreadable == (EvidenceKind.DAMAGED_PRODUCT_PHOTO,)
    assert result.missing_or_unusable == ()
    assert result.requests == ()
    assert "person" in result.reason.lower()


def test_unusable_and_unreadable_together_are_never_mixed_into_one_list() -> None:
    """A claim can have both problems at once, and the two must stay in separate lists so
    the merchant is never asked to fix something that was our failure.
    """
    findings = (
        unusable(EvidenceKind.INVOICE, "too cropped to read the prices"),
        unreadable(EvidenceKind.OUTER_PACKAGING_PHOTO, "the image failed to fetch"),
        present(EvidenceKind.CUSTOMER_CONFIRMATION),
        present(EvidenceKind.DAMAGED_PRODUCT_PHOTO),
    )

    result = assess_evidence_sufficiency(findings)

    assert result.missing_or_unusable == (EvidenceKind.INVOICE,)
    assert result.unreadable == (EvidenceKind.OUTER_PACKAGING_PHOTO,)
    assert result.needs_escalation is True
    assert len(result.requests) == 1
    assert "prices" in result.requests[0]


# ---------------------------------------------------------------------------
# Determinism (NFR-1)
# ---------------------------------------------------------------------------


def test_the_same_findings_produce_the_same_assessment_twice() -> None:
    """NFR-1: nothing here depends on ordering or on anything but the findings given."""
    findings = (missing(EvidenceKind.INVOICE), present(EvidenceKind.CUSTOMER_CONFIRMATION))

    assert assess_evidence_sufficiency(findings) == assess_evidence_sufficiency(findings)
