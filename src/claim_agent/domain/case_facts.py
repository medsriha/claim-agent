"""Reading the facts a case description hides in ordinary prose.

Every claim a merchant files carries a description: a few sentences of plain
English that ShipBob's case portal builds out of the form the merchant filled
in. Read those sentences and there are real, structured facts inside them —
which parcel the claim is about, what kind of damage is being reported, whether
the box broke as well as the goods, how many orders were affected, when the
carrier last scanned the parcel, and which carrier the merchant says carried it.
Nothing in the system read any of it before this file.

**The disagreements are the point.** On four of the five sample claims the
description names one carrier while ShipBob's own shipment record names a
different one, and on two of them the tracking date written in the prose is not
the day the parcel was recorded as delivered. Someone deciding a claim should be
told that the two accounts differ, rather than being handed one of them as
though it were the only version of events.

Two shapes of description turn up in the sample data, and both are handled:

- **Labelled**, where the portal writes the form's own field names into the
  sentence: `Damage Type: Damage due to carrier mishandling.`
- **Loose**, where the same facts are written as ordinary sentences with no field
  names at all. One of the five sample claims is written this way.

Nothing here reaches out to anything, reads a clock, or asks a model. It is
pattern matching over text, so the same description always produces the same
facts (FR-0.6, NFR-1).

**A merchant's description is untrusted writing.** Nothing read out of it decides
anything by itself: what comes back is a set of values, a list of the places
those values disagree with ShipBob's records, and a list of anything that was
written down but could not be read. A person weighs all three (NFR-4). No
wording in a description can make this file do anything beyond filling those in.

No requirement covers this; see DESIGN.md. The nearest rules it works under are
FR-0.6 (screening that gives the same answer every time), NFR-1 (the same answer
twice), FR-1.13 (never narrow two candidates to one) and NFR-4 (fail toward the
human).
"""

from __future__ import annotations

import re
from datetime import date
from enum import StrEnum

from pydantic import BaseModel, ConfigDict

from claim_agent.domain.models import Case, Shipment


class DamageType(StrEnum):
    """The causes of damage ShipBob's claim form is known to offer.

    There are exactly two members because exactly two wordings appear anywhere in
    ShipBob's sample claims. This is deliberately **not** a guess at the full list
    of options on their form: a description using any other wording is left
    unclassified, and only the merchant's own words survive in `damage_type`. That
    way a cause nobody has seen before is reported as itself rather than pushed
    into the nearest bucket, which is how invented categories get into a system
    and stay there.

    `POOR_PACKAGING` is "Damage due to poor/bad packaging" — the goods were not
    packed well enough for the journey. `CARRIER_MISHANDLING` is "Damage due to
    carrier mishandling" — the parcel was packed properly and the carrier broke
    it. Which of the two it is decides who ShipBob would recover the money from,
    so it is worth reading even though nothing acts on it yet.
    """

    POOR_PACKAGING = "poor_packaging"
    CARRIER_MISHANDLING = "carrier_mishandling"


class DefectType(StrEnum):
    """How far the damage went: the goods only, or the box as well.

    Two members, for the same reason and with the same limit as `DamageType` —
    these are the only two wordings in ShipBob's sample claims, and anything else
    is left unclassified rather than forced into one of them.

    `PRODUCT_AND_BOX` is "Both product and shipping box damaged", which points at
    something happening to the parcel in transit. `PRODUCT_ONLY` is "Product
    damaged, but shipping box is intact", which points at the goods having been
    packed badly or having left the warehouse already broken, since nothing
    outside the box shows a mark.
    """

    PRODUCT_AND_BOX = "product_and_box"
    PRODUCT_ONLY = "product_only"


class ContradictionKind(StrEnum):
    """The four ways a description can disagree with ShipBob's own records.

    `CARRIER` is the description naming a different carrier from the shipment
    record. `SHIPMENT_ID` is the description being about a different parcel from
    the one the case points at. `AFFECTED_ORDER_COUNT` is the description
    claiming a number of affected orders that the case cannot be covering.
    `LAST_TRACKING_DATE` is the description's last carrier scan falling on a
    different day from the shipment's recorded delivery.
    """

    CARRIER = "carrier"
    SHIPMENT_ID = "shipment_id"
    AFFECTED_ORDER_COUNT = "affected_order_count"
    LAST_TRACKING_DATE = "last_tracking_date"


# One fixed sentence per kind of disagreement, so the same claim is always
# explained in the same words (NFR-1). They say what the disagreement means for
# the decision, because "these two fields differ" on its own tells a
# representative nothing they can act on.
_WHY_IT_MATTERS: dict[ContradictionKind, str] = {
    ContradictionKind.CARRIER: (
        "The merchant's account names a different carrier from the one ShipBob's shipment "
        "record says carried the parcel, so anything the description says about the journey "
        "may not be about the carrier that actually made it."
    ),
    ContradictionKind.SHIPMENT_ID: (
        "The description is about a different parcel from the one this case points at, so the "
        "evidence on the case and the shipment record may not belong to each other."
    ),
    ContradictionKind.AFFECTED_ORDER_COUNT: (
        "This case names exactly one order, so a description reporting any other number of "
        "affected orders is describing damage this case does not cover."
    ),
    ContradictionKind.LAST_TRACKING_DATE: (
        "The last carrier scan in the description is not the day the parcel was recorded as "
        "delivered, so either the description is about a different shipment or one of the two "
        "dates is wrong."
    ),
}


class Contradiction(BaseModel):
    """One place where the merchant's description and ShipBob's records disagree.

    Both sides are carried, never just the difference, because which of the two
    is right is a judgement and this file does not make it. A representative
    reads what the merchant wrote, what ShipBob holds, and what the gap between
    them would mean, and decides (NFR-4).

    `described` is the value taken from the merchant's own sentences. `recorded`
    is the value on ShipBob's case or shipment record. Dates appear on both sides
    written the same way — year, month, day — so the two can be compared at a
    glance even though the description wrote its date out in words.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: ContradictionKind
    described: str
    recorded: str
    why_it_matters: str


class CaseFacts(BaseModel):
    """Everything that could be read out of one case description, and what it clashes with.

    Every value is optional and `None` means the description simply did not carry
    it — not zero, not unknown-so-assume-something. Four of the five sample
    descriptions say nothing about how badly the box fared, and inventing an
    answer for them would be worse than leaving the space empty.

    The two `_recognised` fields are the tidy form of the two free-text ones: set
    only when the merchant's wording is one this system has actually seen from
    ShipBob, and left empty otherwise. The raw wording is always kept beside it,
    so nothing is lost when a description says something new.

    `contradictions` lists every place the description disagrees with ShipBob's
    records, always in the same order: carrier, then parcel, then how many orders,
    then the date. Empty means nothing disagreed, which is a real and useful
    answer.

    `unreadable` is what was written down but could not be turned into a value: a
    field given two different answers in the same description, or a date that is
    not a date. Each entry is a plain sentence for a person to read. It is the
    difference between "the description never said" and "the description said
    something we refused to guess at", and a claim should not fail silently on
    the second (NFR-4).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    shipment_id: str | None = None
    damage_type: str | None = None
    damage_type_recognised: DamageType | None = None
    defect_type: str | None = None
    defect_type_recognised: DefectType | None = None
    affected_order_count: int | None = None
    last_carrier_tracking_date: date | None = None
    carrier: str | None = None
    contradictions: tuple[Contradiction, ...] = ()
    unreadable: tuple[str, ...] = ()


def read_case_facts(case: Case, shipment: Shipment | None = None) -> CaseFacts:
    """Read the structured facts out of a merchant's description and check them.

    The description is read first, then every value that came out of it is held
    up against ShipBob's own records and any disagreement is reported. Neither
    step ever decides which side is right, and neither ever fails: a description
    that says nothing produces an empty result rather than an error, because a
    claim written in three words is a normal claim, not a broken one (NFR-4).

    No requirement covers this; see DESIGN.md.

    Args:
        case: The support case, read for its description and for the parcel, order
            and dates the disagreement checks compare against.
        shipment: ShipBob's record of the parcel. Leave it out when it could not
            be read — the description is still read in full, but the carrier and
            the delivery date have nothing to be checked against, so those two
            disagreements cannot be reported. That is a gap in what was checked,
            not a clean bill of health.

    Returns:
        What the description said, what could not be read out of it, and where it
        disagrees with ShipBob's records.
    """
    unreadable: list[str] = []
    description = case.description
    if description is None:
        # A blank description arrives here as nothing at all, because the case
        # model treats empty text as absent. Both mean the same thing: there was
        # nothing to read, and saying so is more use than an empty result alone.
        return CaseFacts(
            unreadable=("The case carries no description, so there was nothing to read.",)
        )

    shipment_id = _single_value(
        _distinct_values(_SHIPMENT_ID, description), "shipment id", unreadable
    )
    carrier = _single_value(_distinct_values(_CARRIER, description), "carrier", unreadable)
    damage_type = _single_value(_damage_type_wordings(description), "damage type", unreadable)
    defect_type = _single_value(_defect_type_wordings(description), "defect type", unreadable)
    affected_order_count = _read_affected_order_count(description, unreadable)
    last_tracking_date = _read_last_tracking_date(description, unreadable)

    return CaseFacts(
        shipment_id=shipment_id,
        damage_type=damage_type,
        damage_type_recognised=_recognised_damage_type(damage_type),
        defect_type=defect_type,
        defect_type_recognised=_recognised_defect_type(defect_type),
        affected_order_count=affected_order_count,
        last_carrier_tracking_date=last_tracking_date,
        carrier=carrier,
        contradictions=_contradictions(
            case=case,
            shipment=shipment,
            described_carrier=carrier,
            described_shipment_id=shipment_id,
            affected_order_count=affected_order_count,
            last_tracking_date=last_tracking_date,
        ),
        unreadable=tuple(unreadable),
    )


# ---------------------------------------------------------------------------
# The shapes of text we look for
# ---------------------------------------------------------------------------
# Every pattern names its capture `value`, so one reader can run any of them.
# All of them ignore capitals, because merchants type field names however they
# like. None of them contains a repeated group inside another repeated group, so
# a very long description costs time in proportion to its length and no more —
# text a merchant wrote is not text this system should be able to be tied up by.

# "Shipment ID: 342578703." — the identifier stops at the first character that
# could not be part of one, which is how the closing full stop is left behind.
_SHIPMENT_ID = re.compile(
    r"\bShipment\s*ID\s*:\s*(?P<value>[A-Za-z0-9][A-Za-z0-9_-]*)",
    re.IGNORECASE,
)

# "Carrier: Other." The colon has to come straight after the word. That is what
# keeps this off "Date of Last Carrier Tracking:", which also contains "Carrier"
# and whose value is a date, and off a product with "Carrier" in its name.
_CARRIER = re.compile(r"\bCarrier\s*:\s*(?P<value>[^.\n]+)", re.IGNORECASE)

# "Damage Type: Damage due to poor/bad packaging."
_LABELLED_DAMAGE_TYPE = re.compile(r"\bDamage\s+Type\s*:\s*(?P<value>[^.\n]+)", re.IGNORECASE)

# "Defect Type: Both product and shipping box damaged."
_LABELLED_DEFECT_TYPE = re.compile(r"\bDefect\s+Type\s*:\s*(?P<value>[^.\n]+)", re.IGNORECASE)

# "Number of affected orders: 2." Only digits are accepted. A number written out
# in words is left unread rather than interpreted, because how many orders a
# claim covers is not a thing to be nearly right about.
_LABELLED_AFFECTED_ORDERS = re.compile(
    r"\bNumber\s+of\s+affected\s+orders\s*:\s*(?P<value>\d+)",
    re.IGNORECASE,
)

# "1 order affected." — the same fact with no field name in front of it.
_LOOSE_AFFECTED_ORDERS = re.compile(r"\b(?P<value>\d+)\s+orders?\s+affected\b", re.IGNORECASE)

# "Date of Last Carrier Tracking: February 22, 2026." Everything up to the full
# stop is taken and then read as a date separately, so a label carrying something
# that is not a date is reported as unreadable instead of quietly ignored.
_LAST_TRACKING_DATE = re.compile(
    r"\bDate\s+of\s+Last\s+Carrier\s+Tracking\s*:\s*(?P<value>[^.\n]+)",
    re.IGNORECASE,
)

# The start of a sentence: the beginning of the text, or the end of the one
# before. Used by the two unlabelled patterns below, which have no field name to
# anchor them and would otherwise match the same words buried in a longer
# sentence — including one saying the opposite.
_SENTENCE_START = r"(?:^|[.\n])\s*"

# "Damage due to poor/bad packaging." on its own, with no label. The opening
# words are distinctive enough to identify the sentence, so the cause itself is
# read freely and a cause nobody has seen before still comes through.
_LOOSE_DAMAGE_TYPE = re.compile(
    _SENTENCE_START + r"(?P<value>Damage\s+due\s+to\s+[^.\n]+)",
    re.IGNORECASE,
)

# ShipBob's exact wordings, and the tidy name each one maps to. The keys are the
# form two pieces of text are compared in — see `_for_comparison`.
_DAMAGE_TYPE_WORDINGS: dict[str, DamageType] = {
    "damage due to poor/bad packaging": DamageType.POOR_PACKAGING,
    "damage due to carrier mishandling": DamageType.CARRIER_MISHANDLING,
}
_DEFECT_TYPE_WORDINGS: dict[str, DefectType] = {
    "both product and shipping box damaged": DefectType.PRODUCT_AND_BOX,
    "product damaged, but shipping box is intact": DefectType.PRODUCT_ONLY,
}

# "Both product and shipping box damaged." on its own, with no label. Unlike the
# damage cause, a defect sentence has no opening words that mark it out, so
# without a label the only safe rule is to look for wordings ShipBob itself has
# written. A defect described in any other words, and with no label in front of
# it, is not read at all — reported as nothing rather than guessed at.
_LOOSE_DEFECT_TYPE = re.compile(
    _SENTENCE_START
    + r"(?P<value>"
    + "|".join(re.escape(wording) for wording in _DEFECT_TYPE_WORDINGS)
    + r")\s*(?=[.\n]|$)",
    re.IGNORECASE,
)

# "February 22, 2026". Month names are held here rather than taken from the
# calendar the machine is set to, so a claim reads the same way on every machine
# (NFR-1). Three-letter shortenings are accepted because they are unambiguous.
_MONTH_NAMES = (
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
)
_MONTH_NUMBERS: dict[str, int] = {
    **{name.casefold(): number for number, name in enumerate(_MONTH_NAMES, start=1)},
    **{name[:3].casefold(): number for number, name in enumerate(_MONTH_NAMES, start=1)},
}
_WRITTEN_DATE = re.compile(r"(?P<month>[A-Za-z]+)\s+(?P<day>\d{1,2}),\s*(?P<year>\d{4})")


# ---------------------------------------------------------------------------
# Reading one field out of the text
# ---------------------------------------------------------------------------


def _distinct_values(pattern: re.Pattern[str], description: str) -> tuple[str, ...]:
    """Collect every different answer the description gives for one field.

    All the matches are gathered rather than just the first, because a
    description answering the same field twice with two different answers is
    something the caller has to be told about. Answers that differ only in
    capitals or spacing count as the same answer, and the first spelling of each
    is the one kept.
    """
    found: list[str] = []
    already_seen: set[str] = set()
    for match in pattern.finditer(description):
        value = _tidy(match.group("value"))
        key = _for_comparison(value)
        if not key or key in already_seen:
            continue
        already_seen.add(key)
        found.append(value)
    return tuple(found)


def _single_value(values: tuple[str, ...], field_name: str, unreadable: list[str]) -> str | None:
    """Take the one answer a field was given, or refuse to choose between several.

    Nothing found means the description did not carry the field, which is
    ordinary and comes back as nothing. Two different answers means the
    description contradicts itself, and picking one would invent the answer, so
    neither is used and the caller is told what was written instead (FR-1.13,
    NFR-4).
    """
    if not values:
        return None
    if len(values) > 1:
        spelled_out = ", ".join(f'"{value}"' for value in values)
        unreadable.append(
            f"The description gives more than one {field_name}: {spelled_out}. None of them was "
            "used, because choosing between them would invent the answer."
        )
        return None
    return values[0]


def _damage_type_wordings(description: str) -> tuple[str, ...]:
    """Find how the description says the damage was caused, labelled or not.

    The labelled form is tried first and, when it is there, is the only thing
    read. A description carrying a field name is answering that field, and going
    on to hunt for loose sentences afterwards would only turn one answer into
    several.
    """
    labelled = _distinct_values(_LABELLED_DAMAGE_TYPE, description)
    return labelled or _distinct_values(_LOOSE_DAMAGE_TYPE, description)


def _defect_type_wordings(description: str) -> tuple[str, ...]:
    """Find how far the description says the damage went, labelled or not."""
    labelled = _distinct_values(_LABELLED_DEFECT_TYPE, description)
    return labelled or _distinct_values(_LOOSE_DEFECT_TYPE, description)


def _read_affected_order_count(description: str, unreadable: list[str]) -> int | None:
    """Read how many orders the description says were affected.

    Handles both the labelled form and the plain "1 order affected" the loose
    descriptions use. Nothing comes back when the description does not say, which
    is not the same as saying none were affected.
    """
    labelled = _distinct_values(_LABELLED_AFFECTED_ORDERS, description)
    values = labelled or _distinct_values(_LOOSE_AFFECTED_ORDERS, description)
    written = _single_value(values, "number of affected orders", unreadable)
    if written is None:
        return None
    # Safe: both patterns capture digits and nothing else.
    return int(written)


def _read_last_tracking_date(description: str, unreadable: list[str]) -> date | None:
    """Read the day the description says the carrier last scanned the parcel.

    A label with something after it that is not a date — a month that does not
    exist, a day that does not exist in that month, or a word like "unknown" — is
    reported as unreadable rather than dropped, because the merchant did answer
    and a representative should see that the answer could not be used (NFR-4).
    """
    written = _single_value(
        _distinct_values(_LAST_TRACKING_DATE, description),
        "last carrier tracking date",
        unreadable,
    )
    if written is None:
        return None
    day = _as_date(written)
    if day is None:
        unreadable.append(
            f'The description gives a last carrier tracking date of "{written}", which could not '
            "be read as a date, so no date was taken from it."
        )
    return day


def _as_date(written: str) -> date | None:
    """Turn "February 22, 2026" into a date, or say it cannot be done.

    Only the one written form is accepted: month in words, day, year. A date
    written as numbers is deliberately not read here, because 11/02/2026 is two
    different days depending on where it was typed and this file has no way to
    tell which (NFR-1).
    """
    match = _WRITTEN_DATE.fullmatch(written)
    if match is None:
        return None
    month = _MONTH_NUMBERS.get(match.group("month").casefold())
    if month is None:
        return None
    try:
        return date(int(match.group("year")), month, int(match.group("day")))
    except ValueError:
        # Days like 30 February get this far and stop here, since only the
        # calendar knows they are impossible.
        return None


def _recognised_damage_type(written: str | None) -> DamageType | None:
    """Match the merchant's wording for the cause to one this system knows.

    Nothing comes back when the wording is not one ShipBob has been seen to use.
    That is the safe answer: the raw wording is kept beside this, so a cause we
    have never met is reported in the merchant's own words rather than filed
    under the nearest one we have (FR-1.13).
    """
    if written is None:
        return None
    return _DAMAGE_TYPE_WORDINGS.get(_for_comparison(written))


def _recognised_defect_type(written: str | None) -> DefectType | None:
    """Match the merchant's wording for how far the damage went to one this system knows.

    Nothing comes back for a wording we have not seen, for the same reason as the
    cause above.
    """
    if written is None:
        return None
    return _DEFECT_TYPE_WORDINGS.get(_for_comparison(written))


# ---------------------------------------------------------------------------
# Checking what was read against ShipBob's records
# ---------------------------------------------------------------------------


def _contradictions(
    *,
    case: Case,
    shipment: Shipment | None,
    described_carrier: str | None,
    described_shipment_id: str | None,
    affected_order_count: int | None,
    last_tracking_date: date | None,
) -> tuple[Contradiction, ...]:
    """List every place the description and ShipBob's records tell different stories.

    Always in the same order — carrier, parcel, orders, date — so two runs of the
    same claim read identically (NFR-1). A check whose other side is missing is
    skipped rather than counted as agreement: with no shipment record there is
    nothing for the carrier or the delivery date to disagree with.
    """
    found: list[Contradiction] = []

    if (
        described_carrier is not None
        and shipment is not None
        and shipment.carrier is not None
        and _differ(described_carrier, shipment.carrier)
    ):
        # "Other" is one of the options on ShipBob's own form, so this fires on
        # nearly every claim. It is reported all the same: a claim filed against
        # an unnamed carrier while a real one carried the parcel is exactly the
        # sort of thing a representative should see rather than have hidden.
        found.append(_contradiction(ContradictionKind.CARRIER, described_carrier, shipment.carrier))

    if (
        described_shipment_id is not None
        and case.shipment_id is not None
        and _differ(described_shipment_id, case.shipment_id)
    ):
        found.append(
            _contradiction(ContradictionKind.SHIPMENT_ID, described_shipment_id, case.shipment_id)
        )

    if affected_order_count is not None and case.order_id is not None and affected_order_count != 1:
        # A case points at exactly one order, so any other count — two, or none —
        # is the merchant describing something wider than this case covers.
        found.append(
            _contradiction(
                ContradictionKind.AFFECTED_ORDER_COUNT,
                f"{affected_order_count} affected orders",
                f"one order, {case.order_id}",
            )
        )

    if (
        last_tracking_date is not None
        and shipment is not None
        and shipment.delivered_date is not None
        and last_tracking_date != shipment.delivered_date.date()
    ):
        found.append(
            _contradiction(
                ContradictionKind.LAST_TRACKING_DATE,
                last_tracking_date.isoformat(),
                shipment.delivered_date.date().isoformat(),
            )
        )

    return tuple(found)


def _contradiction(kind: ContradictionKind, described: str, recorded: str) -> Contradiction:
    """Write down one disagreement, with the fixed sentence saying why it matters."""
    return Contradiction(
        kind=kind,
        described=described,
        recorded=recorded,
        why_it_matters=_WHY_IT_MATTERS[kind],
    )


def _differ(described: str, recorded: str) -> bool:
    """Say whether two pieces of text are really different things.

    Capitals and extra spaces are typing rather than meaning, so they are
    ignored. Nothing else is: no word is dropped and no abbreviation expanded,
    because "USPS" and "USPS Ground" are two different services and calling them
    the same would hide a disagreement a representative needs.
    """
    return _for_comparison(described) != _for_comparison(recorded)


# ---------------------------------------------------------------------------
# Tidying text
# ---------------------------------------------------------------------------


def _tidy(value: str) -> str:
    """Clean up a value pulled out of a sentence, without changing what it says.

    Runs of spaces become one, and punctuation left hanging on the end by the
    sentence around it is dropped. The words themselves are untouched, so what
    comes back is still the merchant's own wording.
    """
    return " ".join(value.split()).strip(" ,;")


def _for_comparison(value: str) -> str:
    """Reduce text to the form two pieces of it are compared in.

    `casefold` rather than lower case, because it does not depend on the language
    the machine is set to, so the same claim reads the same way anywhere (NFR-1).
    """
    return " ".join(value.split()).casefold()
