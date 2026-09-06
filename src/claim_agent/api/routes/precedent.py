from __future__ import annotations

from decimal import Decimal, InvalidOperation

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field

from claim_agent.api.deps import PolicyDep, PrecedentStoreDep
from claim_agent.domain.claim_line import MatchOutcome
from claim_agent.domain.evidence import EvidenceFinding, EvidenceKind, EvidenceState
from claim_agent.domain.precedent import PrecedentQuery, PrecedentRecord
from claim_agent.errors import InvalidRequestError, NotFoundError
from claim_agent.storage.precedent_store import PrecedentSet

router = APIRouter(prefix="/precedent", tags=["precedent"])


class PrecedentSearch(BaseModel):
    """What a caller describes about the claim they want precedent for."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    merchant_account: str | None = Field(
        default=None, description="What the merchant said happened, in their words."
    )
    product_name: str = Field(default="", description="The damaged product's name.")
    unit_price: str | None = Field(
        default=None, description='What one of them cost, as text: "52.00".'
    )
    match: MatchOutcome = Field(
        default=MatchOutcome.MATCHED,
        description="How the damaged product related to the order behind it.",
    )
    evidence: dict[EvidenceKind, EvidenceState] = Field(
        default_factory=dict, description="What state each known piece of evidence was in."
    )
    limit: int | None = Field(
        default=None,
        gt=0,
        le=50,
        description="How many records to return. Defaults to the policy value.",
    )
    minimum_similarity: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="How alike a record must be to come back. Defaults to the policy value.",
    )

    def to_query(self) -> PrecedentQuery:
        """Turn the request into the question the store understands."""
        return PrecedentQuery(
            merchant_account=self.merchant_account,
            product_name=self.product_name,
            unit_price=_price(self.unit_price),
            match=self.match,
            evidence=tuple(
                EvidenceFinding(kind=kind, state=state, observed="Described in the search.")
                for kind, state in self.evidence.items()
            ),
        )


def _price(value: str | None) -> Decimal | None:
    """Read a price given as text, or `None` when none was given."""
    if value is None:
        return None
    try:
        return Decimal(value)
    except InvalidOperation as failure:
        raise InvalidRequestError(
            "unit_price has to be an amount written as text, such as '52.00'.",
            details={"unit_price": value},
        ) from failure


@router.post("/search", summary="Find past claims like this one")
async def search_precedent(
    search: PrecedentSearch,
    store: PrecedentStoreDep,
    policy: PolicyDep,
) -> PrecedentSet:
    """Answer with the past claims most like the one described, and why each is alike."""
    return store.similar_to(
        search.to_query(),
        limit=search.limit if search.limit is not None else policy.precedent_results_per_product,
        minimum_similarity=(
            search.minimum_similarity
            if search.minimum_similarity is not None
            else policy.min_precedent_similarity
        ),
    )


@router.get("/{precedent_id}", summary="Read one past claim")
async def read_precedent(precedent_id: str, store: PrecedentStoreDep) -> PrecedentRecord:
    """Answer with one stored claim, so a cited precedent can be looked at in full."""
    record = store.get(precedent_id)
    if record is None:
        raise NotFoundError(
            "No past claim is stored under that name.",
            details={"precedent_id": precedent_id},
        )
    return record
