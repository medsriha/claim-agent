"""Fetching the past claims like this one, just before the investigation starts.

The investigation is handed its precedent the way it is handed the facts the
pre-flight screen worked out: it arrives with the claim, already gathered
(FR-0.5, FR-S.6). It is **not** a tool the model may choose to call.

That is the whole point of doing it here. If looking for precedent were optional,
two runs of the same claim could differ purely in whether the model thought to
search — which is exactly the run-to-run variance NFR-1 forbids, introduced by the
one feature meant to reduce it.

**Where this sits.** After the claim has been split into products (FR-1a) and
before each product is investigated (FR-1b). By then the product is known, which is
half of what makes two claims alike, and the claim-level pass has already settled
what the invoice, the customer confirmation and the outer packaging show
(FR-1a.3) — the other half. One retrieval per product, because from that point on
each product is its own claim (FR-1b.1, FR-S.5).

**It cannot fail the claim.** A store that cannot be read comes back saying so, and
the investigation goes ahead without precedent (FR-S.13, NFR-4).
"""

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
    """Gather the past claims most like this product, ready to put in front of the model.

    Called once per claim line, before that line's investigation is asked anything
    (FR-S.5, FR-S.6).

    The line's own record is left out of the search. A claim being investigated a
    second time — after a revision, or a re-run — would otherwise find the record it
    wrote the first time and rate it its own best precedent, which is not evidence of
    anything except that the claim is identical to itself.

    Args:
        store: Where past claims are kept.
        case: The claim the merchant opened, read for their account of what happened.
        line: The one product about to be investigated.
        policy: Read for how many records to return and how alike a record has to be
            to count (FR-0.7, NFR-7). Both are judgement calls nobody has ruled on.
        shared_evidence: What the claim-level pass settled about the invoice, the
            customer confirmation and the outer packaging (FR-1a.3). Empty when
            nothing has been settled yet, which simply leaves the evidence pattern out
            of the comparison rather than counting against every candidate.

    Returns:
        The records found, most alike first; or an empty set that says whether
        nothing was similar enough or the store could not be read. The caller must
        not treat those two as the same thing (FR-S.13).
    """
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
