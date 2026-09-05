from __future__ import annotations

import re
from collections.abc import Sequence
from datetime import datetime

from claim_agent.domain.dates import whole_days_between
from claim_agent.domain.models import Case, GateName, Order, Shipment, TerminalReason
from claim_agent.policy import Policy
from claim_agent.preflight.models import CaseRecord, DeliveryDate, GateResult

EMAIL_REASON_ORDER = (
    TerminalReason.CLAIM_TOO_OLD,
    TerminalReason.WRONG_CLAIM_TYPE,
    TerminalReason.MISSING_KEY_INFORMATION,
)

NOT_RECORDED = "not recorded"

NOT_KNOWN = "not known"

_DELIVERY_SOURCE_LABELS = {
    "case": "the claim record",
    "shipment": "the shipment record",
    "none": "neither record",
}

_INSURED_WORD = re.compile(r"\binsured\b", re.IGNORECASE)


def resolve_delivered_date(record: CaseRecord) -> DeliveryDate:
    """Choose the case delivery date, falling back to the shipment date."""
    case_value = record.case.delivered_date
    shipment_value = record.shipment.delivered_date if record.shipment is not None else None

    if case_value is not None:
        return DeliveryDate(
            value=case_value,
            source="case",
            case_value=case_value,
            shipment_value=shipment_value,
        )
    if shipment_value is not None:
        return DeliveryDate(
            value=shipment_value,
            source="shipment",
            case_value=case_value,
            shipment_value=shipment_value,
        )
    return DeliveryDate(
        value=None,
        source="none",
        case_value=case_value,
        shipment_value=shipment_value,
    )


def check_age(delivery: DeliveryDate, case: Case, policy: Policy) -> GateResult:
    """Check that the claim was filed within the configured age limit."""
    observed = {
        "case_delivered_date": _moment(delivery.case_value),
        "shipment_delivered_date": _moment(delivery.shipment_value),
        "delivered_date_used": _moment(delivery.value),
        "delivered_date_taken_from": _DELIVERY_SOURCE_LABELS[delivery.source],
        "case_created_date": _moment(case.created_date),
        "days_since_delivery": NOT_KNOWN,
        "age_limit_days": str(policy.max_claim_age_days),
        "limit_day_still_counts": _yes_or_no(policy.age_limit_inclusive),
    }

    if delivery.value is None:
        return GateResult(
            gate=GateName.AGE,
            passed=False,
            reason=TerminalReason.MISSING_KEY_INFORMATION,
            explanation=(
                "Neither the claim nor the shipment record says when it was delivered, "
                "so there is no way to tell whether the claim was filed in time."
            ),
            observed=observed,
        )

    days = whole_days_between(delivery.value, case.created_date)
    observed["days_since_delivery"] = str(days)

    within_limit = _is_within_age_limit(days, policy)
    return GateResult(
        gate=GateName.AGE,
        passed=within_limit,
        reason=None if within_limit else TerminalReason.CLAIM_TOO_OLD,
        explanation=_age_explanation(days, within_limit=within_limit, policy=policy)
        + _disagreement_note(delivery),
        observed=observed,
    )


def check_claim_type(case: Case, policy: Policy) -> GateResult:
    """Check that the case is a supported damage-in-transit claim."""
    handled = policy.damaged_in_transit_sub_category
    claim_type = case.sub_category
    compared = _for_comparison(claim_type) if claim_type is not None else None
    handled_compared = _for_comparison(handled)
    matches = (
        bool(handled_compared) and compared is not None and compared.startswith(handled_compared)
    )

    observed = {
        "claim_type": _text(claim_type),
        "claim_type_compared": _text(compared),
        "handled_claim_type": handled,
        "handled_claim_type_compared": handled_compared,
    }

    if matches:
        return GateResult(
            gate=GateName.CLAIM_TYPE,
            passed=True,
            reason=None,
            explanation=f'This claim was filed as "{claim_type}", which is the kind handled here.',
            observed=observed,
        )

    if claim_type is None:
        explanation = (
            "The claim does not say what kind of complaint it is, and only "
            f'"{handled}" claims are handled here.'
        )
    else:
        explanation = (
            f'This claim was filed as "{claim_type}", but only "{handled}" claims are handled here.'
        )
    return GateResult(
        gate=GateName.CLAIM_TYPE,
        passed=False,
        reason=TerminalReason.WRONG_CLAIM_TYPE,
        explanation=explanation,
        observed=observed,
    )


def check_key_information(record: CaseRecord, policy: Policy) -> GateResult:
    """Check that the claim has enough information to investigate."""
    case = record.case
    description = case.description.strip() if case.description is not None else None

    missing: list[str] = []
    if case.shipment_id is None:
        missing.append("the shipment number it relates to")
    elif record.shipment is None:
        missing.append("a shipment matching the number on it")
    if case.order_id is None:
        missing.append("the order number it relates to")
    elif record.order is None:
        missing.append("an order matching the number on it")
    if description is None:
        missing.append("a description of what happened")
    elif len(description) < policy.min_description_length:
        missing.append("a fuller description of what happened")

    observed = {
        "shipment_id": _text(case.shipment_id),
        "shipment_record": _record_status(case.shipment_id, record.shipment),
        "order_id": _text(case.order_id),
        "order_record": _record_status(case.order_id, record.order),
        "description": NOT_RECORDED if description is None else "given",
        "description_length": str(len(description) if description is not None else 0),
        "minimum_description_length": str(policy.min_description_length),
        "missing": ", ".join(missing),
    }

    if not missing:
        return GateResult(
            gate=GateName.KEY_INFORMATION,
            passed=True,
            reason=None,
            explanation=(
                "The claim names a parcel and an order, both records were read, "
                "and the merchant described what happened."
            ),
            observed=observed,
        )

    return GateResult(
        gate=GateName.KEY_INFORMATION,
        passed=False,
        reason=TerminalReason.MISSING_KEY_INFORMATION,
        explanation=(
            f"This claim is missing {_written_list(missing)}, so there is nothing to investigate."
        ),
        observed=observed,
    )


def check_insurance(shipment: Shipment | None, claim_type: str | None = None) -> GateResult:
    """Check that neither the shipment nor claim type marks the claim insured."""
    claim_type_indicates_insured = bool(claim_type and _INSURED_WORD.search(claim_type))
    observed = {
        "shipment_record": "read" if shipment is not None else "not available",
        "is_insured": _yes_or_no(shipment.is_insured) if shipment is not None else NOT_KNOWN,
        "claim_type": _text(claim_type),
        "claim_type_indicates_insured": _yes_or_no(claim_type_indicates_insured),
    }

    if claim_type_indicates_insured:
        return GateResult(
            gate=GateName.INSURANCE,
            passed=False,
            reason=TerminalReason.SHIPMENT_INSURED,
            explanation=(
                f'This claim was filed as "{claim_type}", which marks it as insured. '
                "Insured claims are routed through a different process."
            ),
            observed=observed,
        )

    if shipment is None:
        return GateResult(
            gate=GateName.INSURANCE,
            passed=False,
            reason=TerminalReason.MISSING_KEY_INFORMATION,
            explanation=(
                "There is no shipment record, so nobody can say whether the shipment was insured, "
                "and an insured parcel must never be handled here."
            ),
            observed=observed,
        )

    if shipment.is_insured:
        return GateResult(
            gate=GateName.INSURANCE,
            passed=False,
            reason=TerminalReason.SHIPMENT_INSURED,
            explanation=(
                "This shipment was insured, and insured shipments are claimed on their insurance "
                "through a different process."
            ),
            observed=observed,
        )

    return GateResult(
        gate=GateName.INSURANCE,
        passed=True,
        reason=None,
        explanation="This parcel was not insured, so the claim belongs here.",
        observed=observed,
    )


def evaluate_gates(
    record: CaseRecord, delivery: DeliveryDate, policy: Policy
) -> tuple[GateResult, ...]:
    """Run all four eligibility checks in a fixed order."""
    return (
        check_age(delivery, record.case, policy),
        check_claim_type(record.case, policy),
        check_key_information(record, policy),
        check_insurance(record.shipment, record.case.sub_category),
    )


def terminal_reasons(gates: Sequence[GateResult]) -> tuple[TerminalReason, ...]:
    """Collect unique terminal reasons in their display order."""
    failed = [gate.reason for gate in gates if not gate.passed and gate.reason is not None]
    emailable = tuple(reason for reason in EMAIL_REASON_ORDER if reason in failed)
    if TerminalReason.SHIPMENT_INSURED in failed:
        return (TerminalReason.SHIPMENT_INSURED, *emailable)
    return emailable


def _is_within_age_limit(days: int, policy: Policy) -> bool:
    """Apply the configured inclusive or exclusive age limit."""
    if policy.age_limit_inclusive:
        return days <= policy.max_claim_age_days
    return days < policy.max_claim_age_days


def _age_explanation(days: int, *, within_limit: bool, policy: Policy) -> str:
    """Write the age check's finding as one sentence a representative can read."""
    limit = (
        f"the limit of {_day_count(policy.max_claim_age_days)} or fewer"
        if policy.age_limit_inclusive
        else f"the limit of fewer than {_day_count(policy.max_claim_age_days)}"
    )
    if days < 0:
        return (
            f"This claim was filed {_day_count(-days)} before the delivery date on record, "
            "which cannot be right, but it is certainly not too old."
        )
    if within_limit:
        return f"This claim was filed {_day_count(days)} after delivery, within {limit}."
    return f"This claim was filed {_day_count(days)} after delivery, past {limit}."


def _disagreement_note(delivery: DeliveryDate) -> str:
    """Describe conflicting case and shipment delivery dates."""
    if not delivery.sources_disagree:
        return ""
    return (
        " The claim and the parcel give different delivery dates "
        f"({_moment(delivery.case_value)} and {_moment(delivery.shipment_value)}); "
        "the date on the claim was used."
    )


def _record_status(record_id: str | None, record: Shipment | Order | None) -> str:
    """Describe whether a referenced record was available."""
    if record is not None:
        return "read"
    if record_id is not None:
        return "could not be read"
    return "not looked up, because the claim gives no id"


def _written_list(items: Sequence[str]) -> str:
    """Join things into the list a person would write: "a", "a and b", "a, b and c"."""
    if len(items) == 1:
        return items[0]
    return f"{', '.join(items[:-1])} and {items[-1]}"


def _day_count(days: int) -> str:
    """Write a number of days the way a person says it, so "1 days" never appears."""
    return "1 day" if days == 1 else f"{days} days"


def _moment(value: datetime | None) -> str:
    """Format a timestamp consistently across hosts."""
    if value is None:
        return NOT_RECORDED
    return value.isoformat()


def _text(value: str | None) -> str:
    """Show a piece of text, or say plainly that it was not there."""
    return NOT_RECORDED if value is None else value


def _yes_or_no(value: bool) -> str:
    """Write a true-or-false answer as a word, for someone reading the result."""
    return "yes" if value else "no"


def _for_comparison(value: str) -> str:
    """Normalize case and whitespace for claim-type comparisons."""
    return " ".join(value.split()).casefold()
