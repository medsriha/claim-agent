from __future__ import annotations

from collections.abc import Sequence
from enum import StrEnum

from pydantic import BaseModel, ConfigDict


class AssessmentName(StrEnum):
    """The four questions answered once every piece of evidence is in hand.

    `DAMAGE_VISIBLE` asks whether the photographs actually show damage, rather
    than merely being photographs of the product (FR-1.8). `PRODUCT_IDENTIFIABLE`
    asks whether the damaged thing can be told apart from everything else on the
    order (FR-1.9) — the question that decides whether an amount can be worked out
    at all. `PRODUCT_ON_INVOICE` asks whether it was in the order in the first
    place, since a claim for something never bought cannot be reimbursed (FR-1.10).
    `PACKAGING_DOCUMENTED` asks whether the outer box was photographed, which is
    about a photograph existing and not about the box being damaged (FR-1.11).
    """

    DAMAGE_VISIBLE = "damage_visible"
    PRODUCT_IDENTIFIABLE = "product_identifiable"
    PRODUCT_ON_INVOICE = "product_on_invoice"
    PACKAGING_DOCUMENTED = "packaging_documented"


REQUIRED_ASSESSMENTS: tuple[AssessmentName, ...] = (
    AssessmentName.DAMAGE_VISIBLE,
    AssessmentName.PRODUCT_IDENTIFIABLE,
    AssessmentName.PRODUCT_ON_INVOICE,
    AssessmentName.PACKAGING_DOCUMENTED,
)
"""All four, in the order the requirements ask them.

Every report shows all four in this order, so two reports read the same way and a
rep can see what was considered rather than inferring it from silence (FR-2.3).
"""


class Assessment(BaseModel):
    """One of the four judgements: what was concluded and why.

    `passed` is the judgement itself. `reasoning` is the sentence a rep reads to
    decide whether they agree, and is the whole point of the shape — a bare yes or
    no would not be reviewable (NFR-3). `attachment_ids` name the images the
    judgement rests on, so the rep can look at what the system looked at (FR-2.2).

    A failed assessment leads to a recommendation of going back to the merchant,
    naming the specific reason. Whether that actually happens is the rep's call
    (FR-1.12).
    """

    model_config = ConfigDict(frozen=True, extra="ignore")

    name: AssessmentName
    passed: bool
    reasoning: str
    attachment_ids: tuple[str, ...] = ()


def assessments_by_name(
    assessments: Sequence[Assessment],
) -> dict[AssessmentName, Assessment]:
    """Index assessments by which question they answer.

    Later entries win where a question is answered twice, which is what lets a
    revision replace one judgement without rebuilding the set.
    """
    return {assessment.name: assessment for assessment in assessments}


def all_answered(assessments: Sequence[Assessment]) -> bool:
    """True when all four questions have been answered.

    A question nobody answered is not a question that passed. An incomplete set
    must never read as a clean one, which is what this exists to prevent.
    """
    indexed = assessments_by_name(assessments)
    return all(name in indexed for name in REQUIRED_ASSESSMENTS)


def failed(assessments: Sequence[Assessment]) -> tuple[AssessmentName, ...]:
    """Which of the four questions were answered no, in the fixed reporting order.

    A question that was never answered is not counted here — use `all_answered`
    for that. The two are different problems: one is a judgement against the
    claim, the other is an incomplete investigation.
    """
    indexed = assessments_by_name(assessments)
    return tuple(
        name for name in REQUIRED_ASSESSMENTS if name in indexed and not indexed[name].passed
    )
