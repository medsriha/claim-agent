from __future__ import annotations

from collections.abc import Sequence
from enum import StrEnum

from pydantic import BaseModel, ConfigDict


class AssessmentName(StrEnum):
    """The four questions answered once every piece of evidence is in hand."""

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
"""All four, in the order the requirements ask them."""


class Assessment(BaseModel):
    """One of the four judgements: what was concluded and why."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    name: AssessmentName
    passed: bool
    reasoning: str
    attachment_ids: tuple[str, ...] = ()


def assessments_by_name(
    assessments: Sequence[Assessment],
) -> dict[AssessmentName, Assessment]:
    """Index assessments by which question they answer."""
    return {assessment.name: assessment for assessment in assessments}


def all_answered(assessments: Sequence[Assessment]) -> bool:
    """True when all four questions have been answered."""
    indexed = assessments_by_name(assessments)
    return all(name in indexed for name in REQUIRED_ASSESSMENTS)


def failed(assessments: Sequence[Assessment]) -> tuple[AssessmentName, ...]:
    """Which of the four questions were answered no, in the fixed reporting order."""
    indexed = assessments_by_name(assessments)
    return tuple(
        name for name in REQUIRED_ASSESSMENTS if name in indexed and not indexed[name].passed
    )
