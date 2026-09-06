from __future__ import annotations

import re
from datetime import date
from enum import StrEnum

from pydantic import BaseModel, ConfigDict

from claim_agent.domain.models import Case, Shipment


class DamageType(StrEnum):
    """The causes of damage ShipBob's claim form is known to offer."""

    POOR_PACKAGING = "poor_packaging"
    CARRIER_MISHANDLING = "carrier_mishandling"


class DefectType(StrEnum):
    """How far the damage went: the goods only, or the box as well."""

    PRODUCT_AND_BOX = "product_and_box"
    PRODUCT_ONLY = "product_only"


class ContradictionKind(StrEnum):
    """The four ways a description can disagree with ShipBob's own records."""

    CARRIER = "carrier"
    SHIPMENT_ID = "shipment_id"
    AFFECTED_ORDER_COUNT = "affected_order_count"
    LAST_TRACKING_DATE = "last_tracking_date"


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
    """One place where the merchant's description and ShipBob's records disagree."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: ContradictionKind
    described: str
    recorded: str
    why_it_matters: str


class CaseFacts(BaseModel):
    """Everything that could be read out of one case description, and what it clashes with."""

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
    """Read the structured facts out of a merchant's description and check them."""
    unreadable: list[str] = []
    description = case.description
    if description is None:
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


_SHIPMENT_ID = re.compile(
    r"\bShipment\s*ID\s*:\s*(?P<value>[A-Za-z0-9][A-Za-z0-9_-]*)",
    re.IGNORECASE,
)


_CARRIER = re.compile(r"\bCarrier\s*:\s*(?P<value>[^.\n]+)", re.IGNORECASE)


_LABELLED_DAMAGE_TYPE = re.compile(r"\bDamage\s+Type\s*:\s*(?P<value>[^.\n]+)", re.IGNORECASE)


_LABELLED_DEFECT_TYPE = re.compile(r"\bDefect\s+Type\s*:\s*(?P<value>[^.\n]+)", re.IGNORECASE)


_LABELLED_AFFECTED_ORDERS = re.compile(
    r"\bNumber\s+of\s+affected\s+orders\s*:\s*(?P<value>\d+)",
    re.IGNORECASE,
)


_LOOSE_AFFECTED_ORDERS = re.compile(r"\b(?P<value>\d+)\s+orders?\s+affected\b", re.IGNORECASE)


_LAST_TRACKING_DATE = re.compile(
    r"\bDate\s+of\s+Last\s+Carrier\s+Tracking\s*:\s*(?P<value>[^.\n]+)",
    re.IGNORECASE,
)


_SENTENCE_START = r"(?:^|[.\n])\s*"


_LOOSE_DAMAGE_TYPE = re.compile(
    _SENTENCE_START + r"(?P<value>Damage\s+due\s+to\s+[^.\n]+)",
    re.IGNORECASE,
)


_DAMAGE_TYPE_WORDINGS: dict[str, DamageType] = {
    "damage due to poor/bad packaging": DamageType.POOR_PACKAGING,
    "damage due to carrier mishandling": DamageType.CARRIER_MISHANDLING,
}
_DEFECT_TYPE_WORDINGS: dict[str, DefectType] = {
    "both product and shipping box damaged": DefectType.PRODUCT_AND_BOX,
    "product damaged, but shipping box is intact": DefectType.PRODUCT_ONLY,
}


_LOOSE_DEFECT_TYPE = re.compile(
    _SENTENCE_START
    + r"(?P<value>"
    + "|".join(re.escape(wording) for wording in _DEFECT_TYPE_WORDINGS)
    + r")\s*(?=[.\n]|$)",
    re.IGNORECASE,
)


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


def _distinct_values(pattern: re.Pattern[str], description: str) -> tuple[str, ...]:
    """Collect every different answer the description gives for one field."""
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
    """Take the one answer a field was given, or refuse to choose between several."""
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
    """Find how the description says the damage was caused, labelled or not."""
    labelled = _distinct_values(_LABELLED_DAMAGE_TYPE, description)
    return labelled or _distinct_values(_LOOSE_DAMAGE_TYPE, description)


def _defect_type_wordings(description: str) -> tuple[str, ...]:
    """Find how far the description says the damage went, labelled or not."""
    labelled = _distinct_values(_LABELLED_DEFECT_TYPE, description)
    return labelled or _distinct_values(_LOOSE_DEFECT_TYPE, description)


def _read_affected_order_count(description: str, unreadable: list[str]) -> int | None:
    """Read how many orders the description says were affected."""
    labelled = _distinct_values(_LABELLED_AFFECTED_ORDERS, description)
    values = labelled or _distinct_values(_LOOSE_AFFECTED_ORDERS, description)
    written = _single_value(values, "number of affected orders", unreadable)
    if written is None:
        return None

    return int(written)


def _read_last_tracking_date(description: str, unreadable: list[str]) -> date | None:
    """Read the day the description says the carrier last scanned the parcel."""
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
    """Turn \"February 22, 2026\" into a date, or say it cannot be done."""
    match = _WRITTEN_DATE.fullmatch(written)
    if match is None:
        return None
    month = _MONTH_NUMBERS.get(match.group("month").casefold())
    if month is None:
        return None
    try:
        return date(int(match.group("year")), month, int(match.group("day")))
    except ValueError:
        return None


def _recognised_damage_type(written: str | None) -> DamageType | None:
    """Match the merchant's wording for the cause to one this system knows."""
    if written is None:
        return None
    return _DAMAGE_TYPE_WORDINGS.get(_for_comparison(written))


def _recognised_defect_type(written: str | None) -> DefectType | None:
    """Match the merchant's wording for how far the damage went to one this system knows."""
    if written is None:
        return None
    return _DEFECT_TYPE_WORDINGS.get(_for_comparison(written))


def _contradictions(
    *,
    case: Case,
    shipment: Shipment | None,
    described_carrier: str | None,
    described_shipment_id: str | None,
    affected_order_count: int | None,
    last_tracking_date: date | None,
) -> tuple[Contradiction, ...]:
    """List every place the description and ShipBob's records tell different stories."""
    found: list[Contradiction] = []

    if (
        described_carrier is not None
        and shipment is not None
        and shipment.carrier is not None
        and _differ(described_carrier, shipment.carrier)
    ):
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
    """Say whether two pieces of text are really different things."""
    return _for_comparison(described) != _for_comparison(recorded)


def _tidy(value: str) -> str:
    """Clean up a value pulled out of a sentence, without changing what it says."""
    return " ".join(value.split()).strip(" ,;")


def _for_comparison(value: str) -> str:
    """Reduce text to the form two pieces of it are compared in."""
    return " ".join(value.split()).casefold()
