"""Fetching the past claims like this one, just before the investigation starts."""

from __future__ import annotations

from collections.abc import Sequence

from claim_agent.domain.claim_line import ClaimLine
from claim_agent.domain.evidence import EvidenceFinding
from claim_agent.domain.models import Case
from claim_agent.domain.precedent import precedent_id_for, query_for_line
from claim_agent.observability import get_logger
from claim_agent.policy import Policy
from claim_agent.storage.precedent_store import PrecedentSet, PrecedentStore

logger = get_logger(__name__)


def precedent_for_line(
    *,
    store: PrecedentStore,
    case: Case,
    line: ClaimLine,
    policy: Policy,
    shared_evidence: Sequence[EvidenceFinding] = (),
) -> PrecedentSet:
    """Gather the past claims most like this product, ready to put in front of the model."""
    found = store.similar_to(
        query_for_line(case=case, line=line, shared_evidence=shared_evidence),
        limit=policy.precedent_results_per_line,
        minimum_similarity=policy.min_precedent_similarity,
        excluding=precedent_id_for(line.claim_line_id),
    )
    logger.info(
        "precedent_retrieved",
        case_id=case.case_id,
        claim_line_id=line.claim_line_id,
        found=len(found.retrieved),
        considered=found.considered,
        store_readable=found.was_read,
    )
    return found
