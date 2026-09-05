from __future__ import annotations

from collections.abc import Iterable, Sequence

from claim_agent.domain.claim_line import ClaimLine
from claim_agent.domain.evidence import EvidenceFinding
from claim_agent.domain.models import Case
from claim_agent.domain.precedent import precedent_id_for, query_for_line
from claim_agent.observability import get_logger
from claim_agent.policy import Policy
from claim_agent.storage.precedent_store import PrecedentSet, PrecedentStore, RetrievedPrecedent

logger = get_logger(__name__)


def precedent_for_claim(
    *,
    store: PrecedentStore,
    case: Case,
    lines: Sequence[ClaimLine],
    policy: Policy,
    shared_evidence: Sequence[EvidenceFinding] = (),
) -> PrecedentSet:
    """Gather the past claims most like this claim, ready to put in front of the model (FR-S.5).

    One search per damaged product, because a past claim resembles a *product* — that is what
    the store holds and what its comparison is built on. The results are then one set, because
    one run reads them (FR-1b.1).

    Args:
        store: Where closed claims are kept.
        case: The claim the merchant opened.
        lines: Every damaged product on it. Empty gives an empty set, which is honest: a claim
            with no products established has nothing to search on.
        policy: Read for how many records to keep per product and how alike one has to be.
        shared_evidence: What the split settled about the parcel, so the comparison can use
            the evidence pattern.

    Returns:
        One set, most alike first, with what every product's search considered added up. **A
        store that could not be read gives an unreadable set**, never an empty one — "we
        looked and found none" and "nobody looked" are different facts (FR-S.13).
    """
    found = [
        _for_one_product(
            store=store, case=case, line=line, policy=policy, shared_evidence=shared_evidence
        )
        for line in lines
    ]

    unreadable = next((one for one in found if not one.was_read), None)
    if unreadable is not None:
        return unreadable

    combined = _most_alike_first(retrieved for one in found for retrieved in one.retrieved)
    logger.info(
        "precedent_retrieved",
        case_id=case.case_id,
        products=len(lines),
        found=len(combined),
        considered=sum(one.considered for one in found),
        store_readable=True,
    )
    return PrecedentSet(retrieved=combined, considered=sum(one.considered for one in found))


def _for_one_product(
    *,
    store: PrecedentStore,
    case: Case,
    line: ClaimLine,
    policy: Policy,
    shared_evidence: Sequence[EvidenceFinding],
) -> PrecedentSet:
    """Search on one damaged product, excluding the record this very product would write."""
    return store.similar_to(
        query_for_line(case=case, line=line, shared_evidence=shared_evidence),
        limit=policy.precedent_results_per_product,
        minimum_similarity=policy.min_precedent_similarity,
        excluding=precedent_id_for(line.claim_line_id),
    )


def _most_alike_first(found: Iterable[RetrievedPrecedent]) -> tuple[RetrievedPrecedent, ...]:
    """Merge what every product's search returned into one list, keeping each record once.

    Two products on one claim can turn up the same past claim, and showing it twice would
    read as two independent confirmations of the same point. The higher score is kept, and
    the order is by score so the closest match is first — with the record's own id breaking a
    tie, so the same claim is always shown the same way round (NFR-1).
    """
    best: dict[str, RetrievedPrecedent] = {}
    for one in found:
        settled = best.get(one.record.precedent_id)
        if settled is None or one.similarity.score > settled.similarity.score:
            best[one.record.precedent_id] = one
    return tuple(
        sorted(
            best.values(),
            key=lambda one: (-one.similarity.score, one.record.precedent_id),
        )
    )
