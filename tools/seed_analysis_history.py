from __future__ import annotations

import argparse
import json
import random
import sys
from datetime import UTC, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

from claim_agent.analysis.performance import summarise
from claim_agent.analysis.view import build, window_for
from claim_agent.domain.decision import DecisionRecord, DecisionStage, Proposal, RepAction
from claim_agent.domain.outcome import Recommendation
from claim_agent.settings import get_settings
from claim_agent.storage.decision_store import DecisionStore

STARTING_NUMBER = 20260904
"""Fixed, so the same day always produces the same history."""

WEEKS = 53
"""A little over a year, so a twelve-month view is full at both ends."""

CENTS = Decimal("0.01")


_AGREEMENT: dict[str, tuple[float, float, float]] = {
    "below_the_bar": (0.55, 0.52, 0.48),
    "fair": (0.74, 0.72, 0.68),
    "high": (0.89, 0.87, 0.82),
    "very_high": (0.945, 0.845, 0.800),
}

_CONFIDENCE_BAND_EDGES = (("below_the_bar", 0.70), ("fair", 0.85), ("high", 0.95))


_DEFECTS = (
    ("Both product and shipping box damaged", 0.60),
    ("Product damaged, but shipping box is intact", 0.40),
)

_DAMAGES = (("Damage due to poor/bad packaging", 0.55), ("Damage due to carrier mishandling", 0.45))

_CARRIERS = (
    ("CirroECommerce", 0.32),
    ("USPS", 0.28),
    ("Royal Mail Tracked 48", 0.22),
    ("UniUni", 0.18),
)


_DEFECT_EFFECT = {
    "Both product and shipping box damaged": 0.16,
    "Product damaged, but shipping box is intact": -0.16,
}

_DAMAGE_EFFECT = {
    "Damage due to poor/bad packaging": 0.05,
    "Damage due to carrier mishandling": -0.05,
}

_CARRIER_EFFECT = {
    "Royal Mail Tracked 48": 0.06,
    "USPS": 0.03,
    "CirroECommerce": -0.04,
    "UniUni": -0.09,
}

_RECOMMENDATIONS = (
    (Recommendation.APPROVE, 0.55),
    (Recommendation.REQUEST_INFO, 0.22),
    (Recommendation.REQUEST_REP_CLARIFICATION, 0.23),
)


_WORDS_WHEN_CHANGED = (
    "Customer confirmation came in by phone; logged separately.",
    "The two-pack was claimed, not the single bottle.",
    "Outer box photo shows a different consignment.",
    "Merchant supplied the invoice after this was drafted.",
    "Damage is to the sleeve, not the product itself.",
)

_WORDS_WHEN_SENT_BACK = (
    "Please look at the second image before deciding this.",
    "The invoice covers a different order; check the shipment id.",
    "This reads as packaging damage rather than product damage.",
    "Amount looks like it used the wrong unit price.",
)


def _band_for_confidence(confidence: float) -> str:
    """Which confidence band a figure falls in, using the same edges the analysis reports on."""
    for name, upper in _CONFIDENCE_BAND_EDGES:
        if confidence < upper:
            return name
    return "very_high"


def _value_column(order_value: Decimal) -> int:
    """Which column of the agreement table an order's value belongs to."""
    if order_value < Decimal("100.00"):
        return 0
    if order_value < Decimal("500.00"):
        return 1
    return 2


def _agreement_chance(
    confidence: float, order_value: Decimal, clarity: float, progress: float
) -> float:
    """How likely a representative was to accept this piece of advice."""
    base = _AGREEMENT[_band_for_confidence(confidence)][_value_column(order_value)]
    return min(0.995, base + 0.06 * (clarity - 0.62) + 0.03 * (progress - 0.5) * 2)


def _draw_order_value(rng: random.Random) -> Decimal:
    """An order value: mostly small, occasionally large, as a real merchant's orders are."""
    dollars = rng.lognormvariate(4.4, 1.15)
    return Decimal(str(round(min(dollars, 4000.0), 2))).quantize(CENTS, ROUND_HALF_UP)


def _pick(rng: random.Random, choices: tuple[tuple[str, float], ...]) -> str:
    """One of a weighted set of values."""
    roll = rng.random()
    running = 0.0
    for value, weight in choices:
        running += weight
        if roll < running:
            return value
    return choices[-1][0]


def _clarity(rng: random.Random, defect: str, damage: str, carrier: str, progress: float) -> float:
    """How clear-cut a claim is, from nothing to one."""
    centre = (
        0.60
        + 0.06 * progress
        + _DEFECT_EFFECT[defect]
        + _DAMAGE_EFFECT[damage]
        + _CARRIER_EFFECT[carrier]
    )
    return min(0.99, max(0.05, rng.gauss(centre, 0.10)))


def _draw_confidence(rng: random.Random, clarity: float) -> float:
    """How sure the system said it was."""
    return min(0.99, max(0.30, rng.gauss(0.52 + 0.46 * clarity, 0.06)))


def _draw_recommendation(rng: random.Random) -> Recommendation:
    """Which of the three next actions the investigation landed on."""
    roll = rng.random()
    running = 0.0
    for recommendation, weight in _RECOMMENDATIONS:
        running += weight
        if roll < running:
            return recommendation
    return Recommendation.REQUEST_REP_CLARIFICATION


def _amount_for(outcome: Recommendation, order_value: Decimal) -> Decimal | None:
    """What would be paid on this outcome, or nothing where no money is involved."""
    if outcome is not Recommendation.APPROVE:
        return None
    share = (order_value * Decimal("0.60")).quantize(CENTS, ROUND_HALF_UP)
    return min(share, Decimal("100.00"))


def _a_different_outcome(rng: random.Random, outcome: Recommendation) -> Recommendation:
    """Whichever of the four a representative settled on instead."""
    others = [one for one in Recommendation if one is not outcome]
    return rng.choice(others)


def _screening_decision(
    rng: random.Random, case_id: str, decided_at: datetime, progress: float
) -> DecisionRecord:
    """One claim the quick checks stopped, and what a representative did about it."""
    agreed = rng.random() < 0.955 + 0.02 * progress
    sent_back = not agreed
    defect = _pick(rng, _DEFECTS)
    damage = _pick(rng, _DAMAGES)
    carrier = _pick(rng, _CARRIERS)
    return DecisionRecord(
        decision_id=f"DEC-{case_id}-01",
        case_id=case_id,
        stage=DecisionStage.SCREENING,
        report_version=2 if sent_back else 1,
        action=RepAction.SENT_BACK if sent_back else RepAction.APPROVED,
        recommended=Proposal(outcome=None, amount_usd=None),
        decided=Proposal(outcome=None, amount_usd=None),
        email_edited=agreed and rng.random() < 0.22 - 0.10 * progress,
        stated_confidence=None,
        order_value_usd=_draw_order_value(rng),
        defect_type=defect,
        damage_type=damage,
        carrier=carrier,
        rep_minutes=max(1, round(rng.gauss(4.0 - 0.6 * progress, 1.4))),
        rep_words=rng.choice(_WORDS_WHEN_SENT_BACK) if sent_back else None,
        decided_by=None,
        decided_at=decided_at,
    )


def _claim_decision(
    rng: random.Random, case_id: str, decided_at: datetime, progress: float
) -> DecisionRecord:
    """One investigated claim, and what a representative did about it."""
    order_value = _draw_order_value(rng)
    defect = _pick(rng, _DEFECTS)
    damage = _pick(rng, _DAMAGES)
    carrier = _pick(rng, _CARRIERS)
    clarity = _clarity(rng, defect, damage, carrier, progress)
    confidence = _draw_confidence(rng, clarity)
    recommended = _draw_recommendation(rng)
    recommended_amount = _amount_for(recommended, order_value)
    claim = {"defect_type": defect, "damage_type": damage, "carrier": carrier}

    if rng.random() < _agreement_chance(confidence, order_value, clarity, progress):
        edited = rng.random() < 0.40 - 0.26 * clarity - 0.10 * progress
        return DecisionRecord(
            decision_id=f"DEC-{case_id}-01",
            case_id=case_id,
            stage=DecisionStage.INVESTIGATION,
            report_version=1,
            action=RepAction.APPROVED,
            recommended=Proposal(outcome=recommended, amount_usd=recommended_amount),
            decided=Proposal(outcome=recommended, amount_usd=recommended_amount),
            email_edited=edited,
            stated_confidence=confidence,
            order_value_usd=order_value,
            **claim,
            rep_minutes=max(1, round(rng.gauss(11.0 - 3.0 * progress, 3.2))),
            rep_words=None,
            decided_by=None,
            decided_at=decided_at,
        )

    if rng.random() < 0.66:
        changes_outcome = rng.random() < 0.55
        decided_outcome = _a_different_outcome(rng, recommended) if changes_outcome else recommended
        decided_amount = _amount_for(decided_outcome, order_value)
        if not changes_outcome and decided_amount is not None:
            decided_amount = (decided_amount * Decimal("0.5")).quantize(CENTS, ROUND_HALF_UP)
        return DecisionRecord(
            decision_id=f"DEC-{case_id}-01",
            case_id=case_id,
            stage=DecisionStage.INVESTIGATION,
            report_version=1,
            action=RepAction.APPROVED_WITH_OVERRIDE,
            recommended=Proposal(outcome=recommended, amount_usd=recommended_amount),
            decided=Proposal(outcome=decided_outcome, amount_usd=decided_amount),
            email_edited=rng.random() < 0.5,
            stated_confidence=confidence,
            order_value_usd=order_value,
            **claim,
            rep_minutes=max(2, round(rng.gauss(16.0 - 3.0 * progress, 4.0))),
            rep_words=rng.choice(_WORDS_WHEN_CHANGED),
            decided_by=None,
            decided_at=decided_at,
        )

    return DecisionRecord(
        decision_id=f"DEC-{case_id}-01",
        case_id=case_id,
        stage=DecisionStage.INVESTIGATION,
        report_version=1,
        action=RepAction.SENT_BACK,
        recommended=Proposal(outcome=recommended, amount_usd=recommended_amount),
        decided=Proposal(outcome=recommended, amount_usd=recommended_amount),
        email_edited=False,
        stated_confidence=confidence,
        order_value_usd=order_value,
        **claim,
        rep_minutes=max(2, round(rng.gauss(9.0 - 2.0 * progress, 2.6))),
        rep_words=rng.choice(_WORDS_WHEN_SENT_BACK),
        decided_by=None,
        decided_at=decided_at,
    )


def generate(now: datetime) -> list[DecisionRecord]:
    """Invent a year of decisions ending at `now`."""
    rng = random.Random(STARTING_NUMBER)
    decisions: list[DecisionRecord] = []
    case_number = 90001

    for week in range(WEEKS):
        progress = week / (WEEKS - 1)
        week_start = now - timedelta(weeks=WEEKS - 1 - week)
        claims_this_week = max(20, round(rng.gauss(52 + 34 * progress, 7)))

        for _ in range(claims_this_week):
            case_id = f"CASE-{case_number}"
            case_number += 1
            decided_at = week_start + timedelta(
                days=rng.randrange(7), hours=rng.randrange(9, 18), minutes=rng.randrange(60)
            )
            if decided_at >= now:
                decided_at = now - timedelta(minutes=rng.randrange(1, 600))

            if rng.random() < 0.34:
                decisions.append(_screening_decision(rng, case_id, decided_at, progress))
                continue

            decisions.append(_claim_decision(rng, case_id, decided_at, progress))

    decisions.sort(key=lambda decision: decision.decided_at)
    return decisions


def seed(store: DecisionStore, now: datetime) -> str:
    """Write the invented history, replacing anything this tool wrote before."""
    removed = store.clear()
    decisions = generate(now)
    for decision in decisions:
        store.record(decision)
    replaced = f", replacing {removed:,}" if removed else ""
    return (
        f"Wrote {len(decisions):,} invented decisions{replaced}, "
        f"ending {now.date().isoformat()}. Every one of them is made up."
    )


def clear(store: DecisionStore) -> str:
    """Remove every decision again."""
    removed = store.clear()
    if not removed:
        return "There were no decisions to remove."
    return f"Removed {removed:,} invented decisions. The analysis screen is empty again."


FIGURES_AS_AT = datetime(2026, 9, 4, 9, 0, tzinfo=UTC)

FIGURES_PERIOD = "twelve_months"
"""The one stretch of time the screen shows."""


def write_figures(path: Path) -> str:
    """Work the figures out once and save them, for the screen to carry."""
    decisions = generate(FIGURES_AS_AT)
    starts_at, ends_at = window_for(FIGURES_PERIOD, FIGURES_AS_AT)
    view = build(summarise(decisions, starts_at, ends_at), FIGURES_PERIOD, FIGURES_AS_AT)
    body = json.dumps(json.loads(view.model_dump_json()), ensure_ascii=False, indent=1)
    path.write_text(body + "\n", encoding="utf-8")
    return (
        f"Wrote a year of invented figures to {path}, worked out from "
        f"{len(decisions):,} made-up decisions. Every number in it is invented."
    )


def main() -> int:
    """Write the invented history, or take it away again."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--clear", action="store_true", help="Remove every decision instead of writing any."
    )
    parser.add_argument(
        "--figures",
        type=Path,
        default=None,
        help="Write the worked-out figures to this file instead of seeding the store.",
    )
    arguments = parser.parse_args()

    if arguments.figures is not None:
        print(write_figures(arguments.figures))
        return 0

    store = DecisionStore(get_settings().database_path)
    print(clear(store) if arguments.clear else seed(store, datetime.now(UTC)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
