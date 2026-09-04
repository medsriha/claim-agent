"""The four checks that decide whether a claim can be looked into at all (FR-0.2).

A "gate" is one yes-or-no check on a claim. Four of them run before anything
expensive happens: is the parcel too old to claim on, is this the kind of
complaint handled here, is the basic information present, and was the parcel
insured. A claim has to clear all four; failing any one stops it, and the
merchant gets an explanation instead of an investigation (FR-0.3, FR-0.4).

Everything here is a plain rule over data that has already been fetched. No AI
is involved and nothing reaches out to anything, so the same claim always gets
the same answer (FR-0.6). The clock is never read either: the checks compare two
dates that both came from ShipBob, so a claim that was 73 days old when it was
filed is 73 days old however long afterwards this runs.

Two habits run through the file, both of them there so a support representative
can answer "why was this claim stopped?" from the result alone, without reading
logs or running anything again (NFR-3):

- **All four checks always run**, even once one has failed. The information is
  already in hand, so stopping early would save nothing and would hide facts the
  representative needs — a claim can be both insured and three months old, and
  she should see both.
- **Each check writes down what it looked at**, not only what it decided. Every
  value is written out as text in one fixed, machine-independent form, so the
  same claim reads identically on any two machines.
"""

from __future__ import annotations

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
"""The order the merchant's email explains the reasons a claim was turned away.

A claim can fail more than one check, and the email explains every reason it failed,
one short paragraph each. This is the order those paragraphs come out in, and the
first reason also names the subject line. So the order settles emphasis and nothing
else: no reason is dropped by being last, and whether a claim is turned away does
not depend on it.

**Being insured is not in this list, and that is the point.** An insured shipment is
routed out rather than answered (FR-0.2): it is claimed on its insurance, through a
process that is not ours, so nobody here writes to the merchant about it. It is
escalated for someone else to pick up instead. A claim that is both insured and, say,
too old still gets the email about its age — the escalation and the email are two
separate things a representative can act on.

Fixing the order in code rather than in the claim policy is deliberate. A fixed
order is what keeps two screenings of the same claim identical (FR-0.6), and nobody
has asked to tune which reason a merchant reads first; a setting nobody changes is a
lever to maintain for no one. Whoever wants it configurable can move it back.
"""

NOT_RECORDED = "not recorded"
"""Shown where a value was simply not there — no date, no id, no description."""

NOT_KNOWN = "not known"
"""Shown where a value could not be worked out because something it needed was absent."""

_DELIVERY_SOURCE_LABELS = {
    "case": "the claim record",
    "shipment": "the shipment record",
    "none": "neither record",
}
"""Plain names for the two records a delivery date can come from.

The stored value is a short code the rest of the code matches on; a
representative reading the result should see words instead.
"""


def resolve_delivered_date(record: CaseRecord) -> DeliveryDate:
    """Decide which delivery date the claim's age should be judged by (FR-0.2).

    Two records carry a delivery date: the claim the merchant opened and the
    parcel it is about. The claim's own date is used whenever it has one, and the
    parcel's is the fallback — the order REQUIREMENTS.md gives for this check.

    The two can hold different dates. That is not treated as a failure: inventing
    a rule about whose date is right would be worse than saying plainly that they
    disagree, so both are kept and the age check names the disagreement in its
    explanation.

    Args:
        record: The claim and the parcel and order records read alongside it. A
            parcel that could not be read counts here as a parcel with no date.

    Returns:
        The date to judge by, which record it came from, and both original
        values. When neither record has a date, the chosen value is `None` and
        the source is "none" — the age check then cannot be carried out.
    """
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
    """Check the merchant did not wait too long before filing the claim (FR-0.2).

    Counts whole calendar days from delivery to the moment the case was opened
    and compares that with the limit in the claim policy. Whether a claim filed
    exactly on the limit still counts is a policy setting, because it is a
    judgement call nobody at ShipBob has yet made.

    Two situations are worth knowing about:

    - **No delivery date anywhere.** The check fails, citing missing information.
      A check that cannot be carried out must never quietly pass (NFR-4).
    - **A claim filed before its own delivery date.** The day count comes out
      negative. It passes — it is certainly not too old — and the negative number
      is reported as it is rather than rounded up to zero, so the oddity stays
      visible to whoever reads the result.

    Args:
        delivery: The chosen delivery date and both originals, from
            `resolve_delivered_date`.
        case: The claim, read for the moment it was opened.
        policy: The limit to judge against, and whether the limit day itself
            still counts.

    Returns:
        The outcome, with every date it looked at, the day count and the limit
        written down beside it.
    """
    observed = {
        "case_delivered_date": _moment(delivery.case_value),
        "shipment_delivered_date": _moment(delivery.shipment_value),
        "delivered_date_used": _moment(delivery.value),
        "delivered_date_taken_from": _DELIVERY_SOURCE_LABELS[delivery.source],
        "case_created_date": _moment(case.created_date),
        # Named the same as the figure worked out alongside these checks and shown
        # in the report, so a reader comparing the two is comparing like with like.
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

    # Both moments come from the models, which refuse a time without a timezone,
    # so this cannot fail on the data reaching it.
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
    """Check this is a damaged-in-transit claim, the only kind handled here (FR-0.2).

    The claim type has to match the handled one exactly, once capitals and extra
    spaces are ignored — those are typing, not meaning. Anything that merely
    *starts* with the right words is deliberately not a match: a type such as
    "Claim | Damaged in Transit - Insured" is a different thing entirely, and
    letting it through would send an insured claim down a path insured claims
    must never take. That is the worst mistake available in this layer.

    A claim that does not say what type it is fails the same way as a claim of
    the wrong type. There is no third answer: we cannot handle what we cannot
    identify.

    Args:
        case: The claim, read for the type the merchant filed it under.
        policy: Holds the one claim type handled here, which is a setting because
            the exact wording is ours rather than ShipBob's.

    Returns:
        The outcome, with both the type on the claim and the type expected,
        each shown as written and as compared.
    """
    handled = policy.damaged_in_transit_sub_category
    claim_type = case.sub_category
    compared = _for_comparison(claim_type) if claim_type is not None else None
    matches = compared is not None and compared == _for_comparison(handled)

    observed = {
        "claim_type": _text(claim_type),
        "claim_type_compared": _text(compared),
        "handled_claim_type": handled,
        "handled_claim_type_compared": _for_comparison(handled),
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
    """Check there is enough to investigate: a parcel, an order, and an account of what happened.

    Three things have to be on the claim — the parcel id, the order id and the
    merchant's description — and the parcel and order records themselves have to
    have been readable. A parcel that does not exist and a claim that never named
    one leave us in the same position: nothing to investigate (FR-0.2). The
    result says which of the two it was, because a representative can chase one
    and not the other.

    A blank or whitespace-only field counts as absent; the models turn those into
    nothing before they arrive here. How long a description has to be to count is
    a policy setting, since ShipBob has never said.

    Args:
        record: The claim and the parcel and order records read alongside it. A
            record is `None` when the claim named none or when ShipBob could not
            give it to us.
        policy: Holds the shortest description that counts as a description.

    Returns:
        The outcome, listing exactly what is missing in a fixed order, and
        showing for each record whether it was read, could not be read, or was
        never looked up.
    """
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
        # Read back by the email to the merchant as a comma-separated list, so a
        # claim with nothing missing leaves it empty rather than writing a word
        # such as "nothing", which would be read as an item and told to a merchant.
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


def check_insurance(shipment: Shipment | None) -> GateResult:
    """Check the parcel was not insured, because insured parcels go elsewhere (FR-0.2).

    An insured parcel is claimed on its insurance and follows a completely
    different process, so it has to be routed away rather than investigated here.

    A parcel record we do not have fails this check too, citing missing
    information. "Insured parcels must never be processed here" only holds if an
    unknown insurance status is treated as unsafe; passing a claim because nobody
    told us it was insured is exactly the outcome this check exists to prevent
    (NFR-4).

    Args:
        shipment: The parcel record, or nothing when the claim named no parcel or
            ShipBob could not give us one.

    Returns:
        The outcome, recording whether the parcel record was available and what
        it said about insurance.
    """
    observed = {
        "shipment_record": "read" if shipment is not None else "not available",
        "is_insured": _yes_or_no(shipment.is_insured) if shipment is not None else NOT_KNOWN,
    }

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
    """Run all four eligibility checks on one claim and return every answer (FR-0.2).

    Always four results, always in the same order — age, claim type, key
    information, insurance. None of them is skipped because an earlier one
    failed: a representative should see everything that is wrong with a claim,
    not only the first thing, and skipping would make the outcome depend on the
    order the checks happened to run in, which is the one thing this layer is not
    allowed to do (FR-0.6).

    Args:
        record: The claim and the parcel and order records read alongside it.
        delivery: The chosen delivery date, from `resolve_delivered_date`.
        policy: The thresholds every check judges against.

    Returns:
        Four outcomes, passed and failed alike, in a fixed order.
    """
    return (
        check_age(delivery, record.case, policy),
        check_claim_type(record.case, policy),
        check_key_information(record, policy),
        check_insurance(record.shipment),
    )


def terminal_reasons(gates: Sequence[GateResult]) -> tuple[TerminalReason, ...]:
    """Collect the reasons a claim was stopped, in order, with no reason said twice (FR-0.3).

    Several checks can give the same reason — a claim with no parcel record is
    missing key information according to two of them — and it should be listed once,
    not twice.

    Being insured comes first when it is one of the reasons, because it is the one
    that changes what happens to the claim: an insured claim is routed out to the
    insurance process rather than answered by us (FR-0.2). The rest follow in the
    order the merchant's email explains them.

    Args:
        gates: The outcomes of the checks. Ones that passed are ignored.

    Returns:
        The reasons to stop the claim, each appearing once, insured first if it
        applies. Empty when nothing stopped the claim — which is the only thing the
        verdict depends on, since a claim is stopped by there being a reason at all
        and not by their order.
    """
    # A list, not a set: iterating a set would put the reasons in an order that
    # can differ between runs, and this layer promises it never does (FR-0.6).
    failed = [gate.reason for gate in gates if not gate.passed and gate.reason is not None]
    emailable = tuple(reason for reason in EMAIL_REASON_ORDER if reason in failed)
    if TerminalReason.SHIPMENT_INSURED in failed:
        return (TerminalReason.SHIPMENT_INSURED, *emailable)
    return emailable


def _is_within_age_limit(days: int, policy: Policy) -> bool:
    """Say whether a claim filed this many days after delivery is still in time.

    Whether the limit day itself counts is a setting: with a 60 day limit that
    counts its last day, day 60 is in time and day 61 is not; with a limit that
    does not, day 60 is already too late.
    """
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
    """Add a sentence when the claim and the parcel give different delivery dates.

    Returns an empty string when they agree, or when only one of them has a date
    — there is nothing to disagree with then. The disagreement is reported rather
    than resolved, because which record is right is not something this code can
    know.
    """
    if not delivery.sources_disagree:
        return ""
    return (
        " The claim and the parcel give different delivery dates "
        f"({_moment(delivery.case_value)} and {_moment(delivery.shipment_value)}); "
        "the date on the claim was used."
    )


def _record_status(record_id: str | None, record: Shipment | Order | None) -> str:
    """Say what became of a record we tried to read: available, unreadable, or never looked up.

    A representative can chase a record ShipBob failed to give us, but a claim
    that never named one needs the merchant instead, so the two are kept apart.
    """
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
    """Write a date and time out in the one form that reads the same on every machine.

    Deliberately not a friendly format such as "11 February 2026": month names
    depend on the language the machine is set to, which would make the same claim
    read differently in two places and break the promise that this layer is
    repeatable (FR-0.6).
    """
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
    """Reduce text to the form claim types are compared in: no case, single spaces.

    Capitals and extra spacing are typing rather than meaning, so they are ignored
    before two claim types are compared. `casefold` rather than `lower` because it
    does not depend on the language the machine is set to (FR-0.6).
    """
    return " ".join(value.split()).casefold()
