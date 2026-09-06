from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime

from claim_agent.domain.models import Case, DraftedEmail, GateName, TerminalReason
from claim_agent.policy import Policy
from claim_agent.preflight.models import ClaimContext, GateResult

MONTH_NAMES = (
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


_INSURED_NEVER_EMAILED = (
    "An insured shipment is sent for representative clarification to the insurance process, never explained to the "
    "merchant, so it must not reach the email."
)

SIGN_OFF = "Thanks,\nShipBob Support"


def draft_terminal_email(
    case: Case,
    reasons: Sequence[TerminalReason],
    gates: Sequence[GateResult],
    context: ClaimContext,
    policy: Policy,
) -> DraftedEmail:
    """Draft the merchant email for a stopped claim."""
    if not reasons:
        raise ValueError("A declined claim needs at least one reason to explain to the merchant.")

    paragraphs = [
        _greeting(case),
        f"Thanks for getting in touch about case {case.case_id}. We have looked at it, and we "
        "are not able to process this claim. Here is why.",
        *(_reason_paragraph(reason, case, gates, context, policy) for reason in reasons),
        "If any of this looks wrong to you, reply to this email and one of us will take "
        "another look.",
        SIGN_OFF,
    ]

    return DraftedEmail(
        to=case.contact_email,
        subject=_subject(case, reasons[0]),
        body="\n\n".join(paragraphs),
    )


def _subject(case: Case, leading_reason: TerminalReason) -> str:
    """Write a subject naming the case and leading reason."""
    match leading_reason:
        case TerminalReason.SHIPMENT_INSURED:
            raise ValueError(_INSURED_NEVER_EMAILED)
        case TerminalReason.CLAIM_TOO_OLD:
            return f"Your claim {case.case_id}: opened too long after delivery"
        case TerminalReason.WRONG_CLAIM_TYPE:
            return f"Your case {case.case_id}: not a damage-in-transit claim"
        case TerminalReason.MISSING_KEY_INFORMATION:
            return f"Your claim {case.case_id}: some details are missing"


def _greeting(case: Case) -> str:
    """Address the merchant by name when available."""
    if case.account_name is None:
        return "Hi there,"
    return f"Hi {case.account_name},"


def _reason_paragraph(
    reason: TerminalReason,
    case: Case,
    gates: Sequence[GateResult],
    context: ClaimContext,
    policy: Policy,
) -> str:
    """Explain one terminal reason."""
    match reason:
        case TerminalReason.SHIPMENT_INSURED:
            raise ValueError(_INSURED_NEVER_EMAILED)
        case TerminalReason.CLAIM_TOO_OLD:
            return _too_old_paragraph(case, _observed(gates, GateName.AGE), context, policy)
        case TerminalReason.WRONG_CLAIM_TYPE:
            return _wrong_type_paragraph(case)
        case TerminalReason.MISSING_KEY_INFORMATION:
            return _missing_information_paragraph(_observed(gates, GateName.KEY_INFORMATION))


def _too_old_paragraph(
    case: Case,
    observed: Mapping[str, str],
    context: ClaimContext,
    policy: Policy,
) -> str:
    """Explain an age failure with the available dates and limits."""
    delivered_date = _read_moment(observed, "delivered_date_used")
    if delivered_date is None:
        delivered_date = context.delivered_date

    days_since_delivery = _read_whole_number(observed, "days_since_delivery")
    if days_since_delivery is None:
        days_since_delivery = context.days_since_delivery

    limit = _in_days(policy.max_claim_age_days)

    if delivered_date is None or days_since_delivery is None:
        return (
            f"We can only look into damage claims opened within {limit} of delivery, and this "
            "one was opened outside that window."
        )

    return (
        f"This shipment was delivered on {_format_date(delivered_date)} and the claim was "
        f"opened on {_format_date(case.created_date)}, which is "
        f"{_in_days(days_since_delivery)} later. We can only look into damage claims opened "
        f"within {limit} of delivery, and this one is past that."
    )


def _wrong_type_paragraph(case: Case) -> str:
    """Explain that the case has the wrong claim type."""
    handled = "We handle claims for goods damaged in transit here"
    passed_on = (
        "We are passing it to the team who look after those, so you do not need to open it again."
    )
    if case.sub_category is None:
        return f"{handled}, and this case is not one of those. {passed_on}"
    return (
        f'{handled}, and this case is recorded as "{case.sub_category}", which is a different '
        f"kind of case. {passed_on}"
    )


def _missing_information_paragraph(observed: Mapping[str, str]) -> str:
    """Name missing details and invite the merchant to provide them."""

    missing = _read_list(observed, "missing")
    invitation = (
        "Send it over in a reply and we will pick this straight back up."
        if len(missing) == 1
        else "Send those over in a reply and we will pick this straight back up."
    )
    if not missing:
        return (
            "To look into a damage claim we need the shipment, the order it came from, and "
            "a description of what went wrong. Some of that is not on this claim, so there "
            f"is nothing for us to investigate yet. {invitation}"
        )

    return (
        f"This claim is missing {_as_list(missing)}, so there is nothing for us to "
        f"investigate yet. {invitation}"
    )


def _observed(gates: Sequence[GateResult], gate_name: GateName) -> Mapping[str, str]:
    """Return a named gate's observed values."""
    for gate in gates:
        if gate.gate is gate_name:
            return gate.observed
    return {}


def _read_moment(observed: Mapping[str, str], key: str) -> datetime | None:
    """Parse an observed timestamp, returning none when invalid."""
    written = observed.get(key)
    if written is None:
        return None
    try:
        moment = datetime.fromisoformat(written)
    except ValueError:
        return None
    if moment.tzinfo is not None:
        return moment.astimezone(UTC)
    return moment


def _read_whole_number(observed: Mapping[str, str], key: str) -> int | None:
    """Parse an observed integer, returning none when invalid."""
    written = observed.get(key)
    if written is None:
        return None
    try:
        return int(written)
    except ValueError:
        return None


def _read_list(observed: Mapping[str, str], key: str) -> tuple[str, ...]:
    """Parse a comma-separated observed value."""
    written = observed.get(key)
    if written is None:
        return ()
    return tuple(item.strip() for item in written.split(",") if item.strip())


def _as_list(items: Sequence[str]) -> str:
    """Join items as a natural-language list."""
    if len(items) == 1:
        return items[0]
    return f"{', '.join(items[:-1])} and {items[-1]}"


def _in_days(count: int) -> str:
    """Say a number of days the way a person would, so a one-day claim is not "1 days"."""
    if count == 1:
        return "1 day"
    return f"{count} days"


def _format_date(moment: datetime) -> str:
    """Format a date with locale-independent month names."""
    return f"{moment.day} {MONTH_NAMES[moment.month - 1]} {moment.year}"
