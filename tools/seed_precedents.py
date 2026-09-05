from __future__ import annotations

import argparse
import sqlite3
import sys
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from claim_agent.domain.assessment import REQUIRED_ASSESSMENTS, Assessment
from claim_agent.domain.claim_line import ClaimedProduct, ClaimLine, MatchOutcome
from claim_agent.domain.evidence import (
    REQUIRED_EVIDENCE,
    EvidenceFinding,
    EvidenceKind,
    EvidenceState,
)
from claim_agent.domain.models import Case, OrderLineItem
from claim_agent.domain.outcome import Recommendation
from claim_agent.domain.precedent import PrecedentRecord, capture_closed_line
from claim_agent.domain.reimbursement import AmountComponent, AmountDerivation
from claim_agent.settings import get_settings
from claim_agent.storage.precedent_store import PrecedentStore, all_records

# The three accounts of damage the sample claims give, near enough word for word. A past
# claim is found mostly on how the merchant described what happened, so a record phrased
# in wording no sample claim uses would sit in the store and never be offered.
CRUSHED_BOX = (
    "Customer received order and product arrived damaged. Both product and shipping box "
    "damaged. Damage due to poor/bad packaging. 1 order affected."
)
CARRIER_MISHANDLING = (
    "Customer received order and product arrived damaged. Damage due to carrier "
    "mishandling. 1 order affected."
)
BOX_INTACT = (
    "Customer received order and product arrived damaged. Product damaged, but shipping "
    "box is intact. Damage due to poor/bad packaging. 1 order affected."
)

# The cap every recommended figure was held to. Named here rather than read from the claim
# policy on purpose: these are records of what was decided at the time, and a record must
# not change its mind because an operator later moved the limit.
CAP_AT_THE_TIME = Decimal("100.00")

_ALL_PRESENT = dict.fromkeys(REQUIRED_EVIDENCE, EvidenceState.PRESENT)


def _evidence(states: dict[EvidenceKind, EvidenceState]) -> tuple[EvidenceFinding, ...]:
    """Turn a state per piece of evidence into the findings a closed claim carries."""
    said = {
        EvidenceState.PRESENT: "Found on the case and good enough to draw a conclusion from.",
        EvidenceState.MISSING: "No such attachment was sent with the claim.",
        EvidenceState.UNUSABLE: "An attachment was sent but nothing could be concluded from it.",
        EvidenceState.UNREADABLE: "The attachment could not be fetched.",
    }
    return tuple(
        EvidenceFinding(
            kind=kind,
            state=states[kind],
            observed=said[states[kind]],
            problem=(
                "Too blurry to identify the product."
                if states[kind] is EvidenceState.UNUSABLE
                else None
            ),
        )
        for kind in REQUIRED_EVIDENCE
    )


def _assessments(passed: bool) -> tuple[Assessment, ...]:
    """The four judgements, all of them going the same way.

    Empty for a claim that never got this far: the judgements are made once every piece of
    evidence is in hand, so a claim that went back to the merchant for a missing photograph
    has none, and inventing four for it would describe an investigation that did not happen.
    """
    return tuple(
        Assessment(
            name=name,
            passed=passed,
            reasoning=(
                "The photographs and the invoice supported this."
                if passed
                else "The evidence did not settle this either way."
            ),
        )
        for name in REQUIRED_ASSESSMENTS
    )


def _paid(
    *, product: str, sku: str, unit_price: Decimal, quantity: int, proposed: Decimal
) -> AmountDerivation:
    """What was paid on a claim that paid something, held to the cap of the day."""
    return AmountDerivation(
        components=(
            AmountComponent(
                product_name=product, sku=sku, quantity=quantity, unit_price=unit_price
            ),
        ),
        items_total_usd=unit_price * quantity,
        proposed_usd=proposed,
        amount_usd=min(proposed, CAP_AT_THE_TIME),
        cap_usd=CAP_AT_THE_TIME,
        cap_applied=proposed > CAP_AT_THE_TIME,
        reasoning="Settled by a representative on the photographs and the invoice.",
        priced_from="ShipBob invoice",
    )


def _closed(
    *,
    case_id: str,
    user_id: str,
    account: str,
    detail: str,
    product: str,
    sku: str,
    unit_price: str,
    quantity: int = 1,
    evidence: dict[EvidenceKind, EvidenceState],
    outcome: Recommendation,
    proposed: str | None,
    closed_on: datetime,
    note: str,
    match: MatchOutcome = MatchOutcome.MATCHED,
) -> PrecedentRecord:
    """Build one closed claim line the way the system would, had a person closed it.

    Args:
        case_id: The claim it belonged to. Invented, like everything else here.
        user_id: The merchant. Never compared against — similarity is over what happened,
            not over who it happened to — but kept so a record reads like a real one.
        account: The pattern of damage, in the wording the sample claims use. This is what
            a later claim is mostly matched on.
        detail: One sentence of this merchant's own, added to the pattern. Real merchants do
            not file claims phrased identically, and without it every record scores the same
            against a claim and the ranking says nothing.
        product: The damaged product's name.
        sku: Its code.
        unit_price: What one cost, as text so no figure passes through a float (FR-1.21).
        quantity: How many of them were damaged.
        evidence: What state each of the four pieces of evidence was in.
        outcome: What the claim actually closed on.
        proposed: What the investigation judged the damage to be worth, as text, or `None`
            where the outcome paid nothing.
        closed_on: When a representative closed it.
        note: What that representative said about the decision.
        match: How the damaged product related to the order behind it.
    """
    price = Decimal(unit_price)
    line_id = f"{case_id}-L01"
    return capture_closed_line(
        case=Case(
            case_id=case_id,
            created_date=closed_on,
            user_id=user_id,
            description=f"{account} {detail}",
        ),
        line=ClaimLine(
            claim_line_id=line_id,
            claimed=ClaimedProduct(name=product, quantity=quantity),
            match=match,
            order_line=(
                None
                if match is MatchOutcome.NOT_ON_ORDER
                else OrderLineItem(
                    product_id=line_id,
                    name=product,
                    sku=sku,
                    quantity=quantity,
                    unit_price=price,
                )
            ),
        ),
        evidence=_evidence(evidence),
        assessments=_assessments(True) if proposed is not None else (),
        outcome=outcome,
        amount=(
            None
            if proposed is None
            else _paid(
                product=product,
                sku=sku,
                unit_price=price,
                quantity=quantity,
                proposed=Decimal(proposed),
            )
        ),
        closed_at=closed_on,
        rep_note=note,
    )


def past_claims() -> tuple[PrecedentRecord, ...]:
    """The twelve invented claims, closed between November and February.

    Deliberately older than every sample claim, because a precedent is something that
    happened before the claim in hand.
    """
    missing = dict(_ALL_PRESENT)
    return (
        # A crushed box, the pattern CASE-1001 and CASE-1002 describe.
        _closed(
            case_id="CASE-0811",
            user_id="410882",
            account=CRUSHED_BOX,
            detail="The glass bottle was cracked and had leaked into the carton.",
            product="Liposomal Tripeptide Collagen",
            sku="COLLAGEN1",
            unit_price="52.00",
            evidence=_ALL_PRESENT,
            outcome=Recommendation.APPROVE,
            proposed="52.00",
            closed_on=datetime(2025, 11, 12, 10, 5, tzinfo=UTC),
            note="Paid in full. The carton was flattened and the bottle cracked with it.",
        ),
        _closed(
            case_id="CASE-0818",
            user_id="410882",
            account=CRUSHED_BOX,
            detail="The tub was split along its seam and the powder had spilled.",
            product="Marine Collagen Peptides 250g",
            sku="PEPT1",
            unit_price="44.00",
            evidence=_ALL_PRESENT,
            outcome=Recommendation.APPROVE,
            proposed="44.00",
            closed_on=datetime(2025, 11, 26, 15, 40, tzinfo=UTC),
            note="Paid in full. Same fault as the earlier claim from this merchant.",
        ),
        _closed(
            case_id="CASE-0823",
            user_id="366014",
            account=CRUSHED_BOX,
            detail="Two bottles had burst and soaked the sleeve around them.",
            product="CleanBoss Multi Surface Cleaner 24oz",
            sku="A00299",
            unit_price="12.50",
            quantity=2,
            evidence=_ALL_PRESENT,
            outcome=Recommendation.APPROVE,
            proposed="25.00",
            closed_on=datetime(2025, 12, 3, 9, 12, tzinfo=UTC),
            note="Both bottles had split and soaked the carton. Paid for the two.",
        ),
        _closed(
            case_id="CASE-0827",
            user_id="366014",
            account=CRUSHED_BOX,
            detail="The outer sleeve was torn open at one corner.",
            product="CleanBoss Botanical Disinfectant & Cleaner 24oz 2 Pack",
            sku="A00300",
            unit_price="21.00",
            evidence={**missing, EvidenceKind.INVOICE: EvidenceState.MISSING},
            outcome=Recommendation.REQUEST_INFO,
            proposed=None,
            closed_on=datetime(2025, 12, 9, 11, 48, tzinfo=UTC),
            note="Went back to the merchant for the invoice. Nothing further was sent.",
        ),
        # Carrier mishandling, the pattern CASE-1003 and CASE-1005 describe.
        _closed(
            case_id="CASE-0834",
            user_id="392551",
            account=CARRIER_MISHANDLING,
            detail="The tub arrived split and taped by the carrier.",
            product="2.5LBS White Chocolate Raspberry Huge Whey",
            sku="0159",
            unit_price="59.99",
            evidence=_ALL_PRESENT,
            outcome=Recommendation.APPROVE,
            proposed="59.99",
            closed_on=datetime(2025, 12, 18, 14, 2, tzinfo=UTC),
            note="Tub split along the seam. Paid in full.",
        ),
        _closed(
            case_id="CASE-0839",
            user_id="392551",
            account=CARRIER_MISHANDLING,
            detail="The lid had come away and loose powder was everywhere.",
            product="Bomb Popsicle Wrecked Pre-Workout",
            sku="0041",
            unit_price="39.99",
            evidence={**missing, EvidenceKind.CUSTOMER_CONFIRMATION: EvidenceState.MISSING},
            outcome=Recommendation.REQUEST_INFO,
            proposed=None,
            closed_on=datetime(2026, 1, 7, 16, 20, tzinfo=UTC),
            note="Asked the merchant for the customer's message. Closed when it did not arrive.",
        ),
        _closed(
            case_id="CASE-0842",
            user_id="404773",
            account=CARRIER_MISHANDLING,
            detail="The pouch had burst and spilled through the parcel.",
            product="30-day Pouch LOAM Prebiotic Fiber Formula",
            sku="LOAM-30DAY-001",
            unit_price="48.00",
            evidence=_ALL_PRESENT,
            outcome=Recommendation.APPROVE,
            proposed="48.00",
            closed_on=datetime(2026, 1, 14, 8, 55, tzinfo=UTC),
            note="Pouch burst in transit. Paid in full.",
        ),
        _closed(
            case_id="CASE-0847",
            user_id="392551",
            account=CARRIER_MISHANDLING,
            detail="The bottle was dented and its seal broken.",
            product="Blue Razz Liquid Carnitine",
            sku="0199",
            unit_price="29.99",
            evidence={**missing, EvidenceKind.OUTER_PACKAGING_PHOTO: EvidenceState.MISSING},
            outcome=Recommendation.REQUEST_INFO,
            proposed=None,
            closed_on=datetime(2026, 1, 20, 13, 30, tzinfo=UTC),
            note="No photograph of the outer box, so the claim could not be settled.",
        ),
        _closed(
            case_id="CASE-0851",
            user_id="381220",
            account=BOX_INTACT,
            detail="The roller housing was cracked though the carton was sound.",
            product="Organic Castor Oil Roll-on with Frankincense",
            sku="HG-FRCAST-KITTEDROLL",
            unit_price="24.00",
            evidence=_ALL_PRESENT,
            outcome=Recommendation.APPROVE,
            proposed="24.00",
            closed_on=datetime(2026, 1, 27, 10, 10, tzinfo=UTC),
            note="Roller cracked though the box was sound. Paid on the photographs.",
        ),
        _closed(
            case_id="CASE-0856",
            user_id="410882",
            account=BOX_INTACT,
            detail="One ampoule was shattered inside its moulded tray.",
            product="Additional Collagen Ampoule Duo",
            sku="AMP1",
            unit_price="38.00",
            evidence={**missing, EvidenceKind.DAMAGED_PRODUCT_PHOTO: EvidenceState.UNUSABLE},
            outcome=Recommendation.REQUEST_INFO,
            proposed=None,
            closed_on=datetime(2026, 2, 2, 12, 45, tzinfo=UTC),
            note="The photograph of the damage was too blurry to see anything. Asked again.",
        ),
        # Expensive enough that the cap decided the figure rather than the damage did.
        _closed(
            case_id="CASE-0861",
            user_id="377654",
            account=CRUSHED_BOX,
            detail="The pump bottle was crushed and would not close.",
            product="Advanced Peptide Serum 100ml",
            sku="SERUM-100",
            unit_price="180.00",
            evidence=_ALL_PRESENT,
            outcome=Recommendation.APPROVE_HIGH_VALUE,
            proposed="180.00",
            closed_on=datetime(2026, 2, 6, 9, 25, tzinfo=UTC),
            note="Worth more than we may pay. Held to the cap and flagged for a second look.",
        ),
        # Claimed for something the order never held.
        _closed(
            case_id="CASE-0864",
            user_id="392551",
            account=CARRIER_MISHANDLING,
            detail="The shaker lid was cracked across the thread.",
            product="Red/Black HUGE Shaker",
            sku="0157",
            unit_price="14.99",
            evidence=_ALL_PRESENT,
            outcome=Recommendation.REQUEST_REP_CLARIFICATION,
            proposed=None,
            closed_on=datetime(2026, 2, 11, 17, 5, tzinfo=UTC),
            note="The shaker was on no line of the order. Sent to a representative.",
            match=MatchOutcome.NOT_ON_ORDER,
        ),
    )


def seed(database_path: Path, *, only_if_empty: bool = False) -> str:
    """Write the invented claims, and say what happened.

    Safe to run twice: a record is keyed on its claim line, so writing the same one again
    replaces it rather than leaving two copies.

    Args:
        database_path: The database file the service reads, from the settings.
        only_if_empty: Write nothing if the store already holds anything at all. This is
            what the container runs on start-up, so a restart leaves existing history alone
            rather than piling a second copy on it. It asks whether the store is empty and
            nothing more: a store somebody cleared is empty like any other, and is seeded
            again.

    Returns:
        A sentence saying what happened, for whoever ran it.
    """
    already = all_records(database_path)
    if only_if_empty and already:
        return f"Left alone: the store already holds {len(already)} past claim(s)."

    store = PrecedentStore(database_path)
    claims = past_claims()
    for claim in claims:
        store.record(claim)
    return (
        f"Seeded {len(claims)} invented past claims. An investigation will now find "
        "comparable ones, and every figure in them was made up."
    )


def clear(database_path: Path) -> str:
    """Remove every past claim from the store.

    Reaches past the store's own methods, which deliberately have no way to delete a
    record: the system never forgets a claim somebody closed, and giving it that ability
    so a demonstration could tidy up after itself would be the wrong trade. The words a
    claim is searched by are kept in a second table, and a record deleted without them
    would leave every search offering claims that are no longer there.

    Args:
        database_path: The database file the service reads, from the settings.

    Returns:
        A sentence saying how many past claims were removed.
    """
    if not database_path.exists():
        return f"Nothing to clear: {database_path} does not exist yet."

    with sqlite3.connect(database_path) as connection:
        removed = connection.execute("DELETE FROM precedent_lines").rowcount
        connection.execute("DELETE FROM precedent_search")
    return f"Cleared {removed} past claim(s). Investigations report nothing comparable again."


def main() -> int:
    """Read what was asked for, do it, and say what happened."""
    parser = argparse.ArgumentParser(
        description="Seed or clear the invented past claims the demo is priced against.",
    )
    parser.add_argument(
        "--clear",
        action="store_true",
        help="remove every past claim instead of writing them",
    )
    parser.add_argument(
        "--if-empty",
        action="store_true",
        help="write them only when the store holds nothing at all",
    )
    arguments = parser.parse_args()

    database_path = get_settings().database_path
    if arguments.clear:
        print(clear(database_path))  # noqa: T201
    else:
        print(seed(database_path, only_if_empty=arguments.if_empty))  # noqa: T201
    return 0


if __name__ == "__main__":
    sys.exit(main())
