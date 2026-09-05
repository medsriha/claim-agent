"""Invent a year of representatives' decisions, so the analysis screen has something to show.

**Everything this writes is invented.** Nothing in the running system records a decision: the
stage where a representative approves a report, changes it, or sends it back is specified
(FR-2.8) and unbuilt, so on any fresh machine the analysis screen honestly reports that nothing
has been decided and every chart on it is empty. That is correct, and it demonstrates nothing.

This tool exists so somebody showing the system can make that screen show something, **knowing**
that what it shows was made up rather than measured. FR-C.8 sets the terms for exactly this kind
of data: it must say in its own words that it is invented, it must be written through the same
store a real decision would go through rather than around it, and it must be removable again.
All three hold here.

    uv run python -m tools.seed_analysis_history           # write it to the store
    uv run python -m tools.seed_analysis_history --clear   # take it back out
    uv run python -m tools.seed_analysis_history --figures web/src/analysis/demoFigures.json

The third one is what the screen actually shows. The analysis screen carries its figures rather
than asking the service for them, because nothing records a real decision and a dashboard that is
blank until somebody runs a command demonstrates nothing. `--figures` writes that file: it invents
the same year, runs the service's own arithmetic over it, and saves the answer. So the numbers on
screen are made rather than typed, and every written figure agrees with the value beside it.

**What the invented history says, and why.** The numbers were not scattered at random. A
dashboard of noise demonstrates nothing, so the data has a shape somebody could actually read
off it:

- Volume grows through the year, and the advice slowly improves.
- **What the merchant reports about the damage really does predict how much work a claim will
  be.** A parcel whose outer box arrived intact, with the product inside damaged, is the awkward
  case: the damage may not have happened in transit at all, so the evidence does not corroborate
  itself and somebody has to look. A box damaged along with the product tells a consistent story.
- **How sure the system said it was mostly matches how often people agreed** — and at the very
  top it does not. In the band where it claims to be more than 95% sure, representatives agree
  rather less often than that. Over-confidence exactly where a system looks safest is the most
  useful thing a calibration chart can show, so the invented data shows it.
- **Expensive claims are agreed with less often than cheap ones at the same stated confidence.**
  That is FR-C.7's open question — whether a high-value claim should be held to a stricter
  standard — with a shape somebody could argue from.

**The words are ShipBob's, even though the numbers are not.** The damage and defect wording comes
from the case description, which states both in a fixed form — "Damage Type: Damage due to carrier
mishandling. Defect Type: Product damaged, but shipping box is intact." — and the carriers come
from the shipment. Both are quoted from ShipBob's published mock API, the same source the sample
records in `tests/fixtures/shipbob.py` come from, so nothing on the analysis screen is a category
this project made up. Which of them makes a claim harder, and by how much, is entirely invented.

Those are properties of data we made up. They are not findings about ShipBob, and nobody should
carry a number off this screen into a decision. Every identifier here begins with a 9, which is
this project's mark for something invented; no identifier ShipBob supplies does.

**It is a development tool.** It writes through the same store the service reads, so what appears
on screen went in the way a real decision would. Nothing in `src/` can reach it, and production
never runs it.

**One thing is deliberately not fixed.** The history is anchored to the day it is written, so the
screen always shows a year ending now rather than a year ending whenever somebody last ran this.
Everything else comes from a fixed starting number, so two people running it on the same day get
identical history and a screenshot keeps matching the screen.
"""

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

# How often a representative agreed, by how sure the system said it was and what the order was
# worth. These are the invented truth the rest of the file works backwards from.
#
# Read the bottom row against the band it belongs to. A claim in the "very high" band is one the
# system said it was more than 95% sure of, so anything under 95 there is the system flattering
# itself — and the numbers are set so that taken together it does. Broken apart, the flattery is
# entirely in the expensive claims: cheap ones really do come in above 95, expensive ones do not.
# That is FR-C.7's open question with a shape somebody could argue from, and it is the reason the
# screen never reports one blended figure without the breakdown beside it.
_AGREEMENT: dict[str, tuple[float, float, float]] = {
    #                     under $100  $100-$500  $500+
    "below_the_bar": (0.55, 0.52, 0.48),
    "fair": (0.74, 0.72, 0.68),
    "high": (0.89, 0.87, 0.82),
    "very_high": (0.945, 0.845, 0.800),
}

_CONFIDENCE_BAND_EDGES = (("below_the_bar", 0.70), ("fair", 0.85), ("high", 0.95))

# What the merchant reported, in ShipBob's own words, and how much weight to give each.
#
# The two vocabularies come from the case description, which states them in a fixed form:
# "Damage Type: Damage due to carrier mishandling. Defect Type: Product damaged, but shipping box
# is intact." Carriers come from the shipment. All of it is quoted rather than reworded.
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

# How much each of those moves how *clear* a claim is.
#
# This is the invented causal story the whole history rests on, and it is worth stating plainly
# because every pattern the analysis screen shows comes out of it:
#
# **A shipping box that arrived intact is the strong signal, and it points the wrong way.** If
# the outer packaging is undamaged and the product inside is not, the damage may well not have
# happened in transit at all — so the evidence does not corroborate itself, the system is less
# sure, and a representative has to look. A box damaged along with the product tells a
# consistent story and is far easier to settle.
#
# Packaging failures are ShipBob's own doing and liability is clear; carrier mishandling is
# somebody else's and may need taking up with them. And carriers differ, which is exactly the
# kind of thing an operations team would want to see and could act on.
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

# Invented, like everything else here. Kept short and specific, because a correction that says
# "the amount was wrong" carries nothing (FR-C.2) and one on a demonstration screen should still
# read like something a person would actually type.
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
    """How likely a representative was to accept this piece of advice.

    Mostly a matter of which confidence band the claim landed in, which is where the calibration
    story lives. How clear the claim is nudges it a little further on top, so that two claims the
    system was equally sure about still differ if one of them was the murkier case.

    `progress` runs from nothing at the start of the history to one at the end, and shifts the
    chance by a few points either side. That is the improvement over time the screen is meant to
    show: the same claim gets a slightly better answer late in the year than early.
    """
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
    """How clear-cut a claim is, from nothing to one.

    Everything else follows from this: a clear claim is one the system is sure about and a
    representative accepts, and a murky one is not. Making the three things a merchant reports
    drive one number, and that number drive the rest, is what stops the patterns on the analysis
    screen being noise — each cut of the data differs because something about those claims really
    is different, rather than because the dice fell that way.
    """
    centre = (
        0.60
        + 0.06 * progress
        + _DEFECT_EFFECT[defect]
        + _DAMAGE_EFFECT[damage]
        + _CARRIER_EFFECT[carrier]
    )
    return min(0.99, max(0.05, rng.gauss(centre, 0.10)))


def _draw_confidence(rng: random.Random, clarity: float) -> float:
    """How sure the system said it was.

    Read off how clear the claim is, because that is what a system reading the evidence would be
    responding to — and pitched a little above it, which is how the history comes to show the
    system flattering itself at the top of its range.
    """
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
    """What would be paid on this outcome, or nothing where no money is involved.

    Sixty per cent of the item's price, capped at $100, which is the arithmetic the real system
    does (FR-1.19, FR-1.20). Repeated here rather than imported because this file is inventing a
    plausible history, not deciding a claim.
    """
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
    """One claim the quick checks stopped, and what a representative did about it.

    These are cheap and almost always accepted: the four checks are fixed rules with clear
    answers, so there is little for anybody to disagree with. That is exactly why they are
    counted apart from the investigated claims everywhere on the screen.
    """
    agreed = rng.random() < 0.955 + 0.02 * progress
    sent_back = not agreed
    defect = _pick(rng, _DEFECTS)
    damage = _pick(rng, _DAMAGES)
    carrier = _pick(rng, _CARRIERS)
    return DecisionRecord(
        decision_id=f"DEC-{case_id}-01",
        case_id=case_id,
        claim_line_id=None,
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


def _line_decision(
    rng: random.Random, case_id: str, position: int, decided_at: datetime, progress: float
) -> DecisionRecord:
    """One investigated product, and what a representative did about it."""
    claim_line_id = f"{case_id}-L{position:02d}"
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
        # A murky claim gets reworded more often even when it is accepted: there is more to
        # explain, and the draft has more chances to say it not quite right.
        edited = rng.random() < 0.40 - 0.26 * clarity - 0.10 * progress
        return DecisionRecord(
            decision_id=f"DEC-{claim_line_id}-01",
            case_id=case_id,
            claim_line_id=claim_line_id,
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

    # They did not accept it. Two thirds of the time they fix it themselves and approve;
    # otherwise it goes back for the investigation to run again (FR-2.8, actions 1 and 2).
    if rng.random() < 0.66:
        changes_outcome = rng.random() < 0.55
        decided_outcome = _a_different_outcome(rng, recommended) if changes_outcome else recommended
        decided_amount = _amount_for(decided_outcome, order_value)
        if not changes_outcome and decided_amount is not None:
            decided_amount = (decided_amount * Decimal("0.5")).quantize(CENTS, ROUND_HALF_UP)
        return DecisionRecord(
            decision_id=f"DEC-{claim_line_id}-01",
            case_id=case_id,
            claim_line_id=claim_line_id,
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

    # Sent back: nothing was decided, so what was recommended still stands on both sides.
    return DecisionRecord(
        decision_id=f"DEC-{claim_line_id}-01",
        case_id=case_id,
        claim_line_id=claim_line_id,
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
    """Invent a year of decisions ending at `now`.

    Args:
        now: The moment the history should run up to, in UTC.

    Returns:
        Every invented decision, oldest first. Roughly five thousand of them, which is enough for
        each candidate rule on the screen to be scored on a meaningful number rather than on a
        handful.
    """
    rng = random.Random(STARTING_NUMBER)  # noqa: S311 - inventing demo data, not securing anything
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

            roll = rng.random()
            lines = 1 if roll < 0.60 else (2 if roll < 0.88 else 3)
            for position in range(1, lines + 1):
                decisions.append(_line_decision(rng, case_id, position, decided_at, progress))

    decisions.sort(key=lambda decision: decision.decided_at)
    return decisions


def seed(store: DecisionStore, now: datetime) -> str:
    """Write the invented history, replacing anything this tool wrote before.

    Safe to run twice: every decision carries an identifier of its own, and writing one again
    replaces it rather than adding a second copy. Running it on a different day writes a
    different set, because the history is anchored to today — so it clears first, or the screen
    would show two overlapping years.

    Returns:
        A sentence saying what happened, for the person who ran it.
    """
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
    """Remove every decision again.

    This matters as much as the writing does: invented history on a screen is indistinguishable
    from the real thing, so there has to be an obvious way to undo it (FR-C.8).
    """
    removed = store.clear()
    if not removed:
        return "There were no decisions to remove."
    return f"Removed {removed:,} invented decisions. The analysis screen is empty again."


# The moment the written-out figures are anchored to.
#
# Fixed, unlike the seeded store, which ends on the day it was run. A file checked into the
# repository must not change every time somebody regenerates it, or the difference between two
# versions would be a year of dates rather than whatever actually changed.
FIGURES_AS_AT = datetime(2026, 9, 4, 9, 0, tzinfo=UTC)

FIGURES_PERIOD = "twelve_months"
"""The one stretch of time the screen shows."""


def write_figures(path: Path) -> str:
    """Work the figures out once and save them, for the screen to carry.

    One period only — the twelve months the screen shows. It offered a choice of three once; that
    went, because three sets of figures nobody can switch between is bulk in the page for nothing.

    Args:
        path: Where to write. Usually `web/src/analysis/demoFigures.json`.

    Returns:
        A sentence saying what happened, for the person who ran it.
    """
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
        print(write_figures(arguments.figures))  # noqa: T201
        return 0

    store = DecisionStore(get_settings().database_path)
    print(clear(store) if arguments.clear else seed(store, datetime.now(UTC)))  # noqa: T201
    return 0


if __name__ == "__main__":
    sys.exit(main())
