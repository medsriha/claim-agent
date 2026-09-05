"""Asking over HTTP which past claims resemble a claim in hand (FR-S.4, FR-S.5).

The investigation is handed its precedent automatically, before it starts work, and
never asks for it (FR-S.6). These addresses are for everybody else: a support
representative who wants to see how claims like this one have gone, a screen that
shows those claims beside a report, and anyone checking whether the record of past
claims holds what they think it holds.

**Nothing here judges a claim.** It searches what was already investigated and
answers with what it found, together with the reasons each record was thought
alike, so a representative can disagree with a comparison rather than take it on
trust (FR-S.3).

**Finding nothing and being unable to look are different answers, and both come
back as successes.** An empty result with `was_read` true means the store was read
and holds nothing much like this claim, which is the ordinary answer for an unusual
one. An empty result with `was_read` false means the store could not be read at
all. Reporting the second as the first would tell a representative there is no
comparable history when nobody actually looked, so the reply always says which
happened (FR-S.13).
"""

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
    """What a caller describes about the claim they want precedent for.

    Deliberately the same handful of things the investigation compares on, so that
    what this address answers is what the investigation would be shown for the same
    claim. A search that scored differently from the real thing would be worse than
    no search, because a representative would be checking the wrong answer.

    **Nothing is required.** Similarity is a matter of degree and every signal is
    optional: a description alone is a valid search, and so is a product name alone.
    A signal left out is left out of the comparison rather than counted against every
    candidate (FR-S.4).

    `unit_price` arrives as text — `"52.00"` — and never as a JSON number, so no
    amount in this system passes through a floating-point value (FR-1.21, NFR-2).

    `evidence` says which of the four pieces of evidence were present, missing or
    unusable, as far as the caller knows. Pieces left out are simply not compared.
    """

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
        """Turn the request into the question the store understands.

        The evidence states become findings so that the one comparison in the domain
        serves both this address and the investigation. Each carries a note saying it
        was described by a caller rather than read off a photograph, because a finding
        with no account of where it came from would be indistinguishable from one the
        system established itself.

        Raises:
            InvalidRequestError: The price is not a number. Caught here rather than by
                the model so the complaint names the field and says what was wrong
                with it.
        """
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
    """Read a price given as text, or `None` when none was given.

    Args:
        value: An amount written out, such as `"52.00"`. `None` when the caller does
            not know the price, which is ordinary — a product that matched no line on
            the order has none.

    Raises:
        InvalidRequestError: The text is not an amount. Answered as a 400 rather than
            being quietly treated as an unknown price, which would silently drop a
            signal the caller meant to supply.
    """
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
    """Answer with the past claims most like the one described, and why each is alike.

    Ranked most alike first. Where two are equally alike, one a representative
    actually decided comes before one nobody has looked at, because an unreviewed
    record is evidence only of what this system once suggested (FR-S.7).

    Args:
        search: What is known about the claim in hand. Everything is optional.
        store: The record of claims already investigated.
        policy: Read for how many records to return and how alike is alike enough,
            unless the request overrides them (FR-0.7, NFR-7).

    Returns:
        The records found, each with its score and the reasons behind it; how many
        candidates were considered; and whether the store could be read at all. An
        empty answer is a success either way, and `was_read` says which kind of empty
        it is (FR-S.13).

    Raises:
        InvalidRequestError: The price was not an amount. Answered as a 400.
    """
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
    """Answer with one stored claim, so a cited precedent can be looked at in full.

    Withdrawn records are returned here. Withdrawal takes a record out of *searches*
    (FR-S.14); somebody naming one is asking for that one, and hiding it would make a
    withdrawn record impossible to inspect or put right. The record says plainly that
    it is withdrawn.

    Args:
        precedent_id: The record's name, such as `PREC-CASE-1001-L01`.
        store: The record of claims already investigated.

    Returns:
        Everything kept about that claim line: the merchant's words, the product and
        its price, the evidence, the four judgements, what was recommended, what it
        would have paid, and what a representative did about it.

    Raises:
        NotFoundError: No such record. Answered as a 404.
        StorageError: The store could not be read. Answered as a 500 — unlike a
            search, there is no partial answer worth giving to somebody who named one
            record.
    """
    record = store.get(precedent_id)
    if record is None:
        raise NotFoundError(
            "No past claim is stored under that name.",
            details={"precedent_id": precedent_id},
        )
    return record
