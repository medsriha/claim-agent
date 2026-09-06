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
    """Gather the past claims most like this claim, ready to put in front of the model (FR-S.5)."""
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
    """Merge what every product's search returned into one list, keeping each record once."""
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
