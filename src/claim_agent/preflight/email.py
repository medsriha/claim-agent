"""The email a merchant receives when their claim cannot be processed at all (FR-0.4).

A claim the pre-flight checks rule out is not simply dropped. The merchant is owed
an explanation, that explanation is an email, and every email waits for a support
representative to approve it. So a stopped claim skips the whole AI investigation
and still arrives on a representative's desk as words that could be sent.

Nothing here reasons about anything. The sentences are fixed and the facts of the
claim are filled into them. That is deliberate on two counts: a claim we cannot
process has to cost almost nothing (NFR-8), and the same claim has to produce the
same email every time it is screened (FR-0.6). There is no model, no clock and no
randomness in this file, and there should never be one.

The email lists **every** reason the claim was declined that a merchant can be told
about, not only the first one. A merchant told just "too old", who fixes nothing and
files again, has been failed by the explanation. The order the reasons arrive in
therefore decides emphasis — which paragraph is read first, and which reason names
the subject — and never which of them the merchant gets to hear about.

**Being insured is not one of those reasons, and never reaches this file.** An
insured shipment is claimed on its insurance, through a process that is not ours, so
it is routed out for someone else to pick up rather than answered by us (FR-0.2).
The write-up marks it for escalation; nobody writes to the merchant about it. A claim
that is both insured and too old still gets this email about its age.

The word "draft" never appears in the text. A representative has to read the exact
wording that would be sent (FR-2.7), so a marker inside the body is a marker that
can reach a merchant. That the email is unsent is recorded next to it instead, on
the email itself, which is where a screen showing it to a representative reads it
from (FR-1.17).
"""

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
"""The month names used in every merchant email, spelled out here on purpose.

Asking the standard library to name a month gives whatever language the machine
running it happens to be configured for: the same claim would say "26 December" on
one computer and "26 décembre" on another. The same claim has to produce the same
email everywhere (FR-0.6), so the names are fixed in the code rather than taken
from the host. This is not an oversight — do not replace it with a date format
string.
"""

_INSURED_NEVER_EMAILED = (
    "An insured shipment is escalated to the insurance process, never explained to the "
    "merchant, so it must not reach the email."
)
"""Why both branches below refuse rather than write anything.

Neither can be reached: the write-up takes being insured out of the reasons before it
drafts an email (FR-0.2). They exist because leaving them out would mean matching the
reasons loosely, and then a fifth reason added one day would slip through unwritten
instead of failing the type check.
"""

SIGN_OFF = "Thanks,\nShipBob Support"
"""How every one of these emails ends.

Invented wording: nobody at ShipBob has told us how their support team signs off.
"""


def draft_terminal_email(
    case: Case,
    reasons: Sequence[TerminalReason],
    gates: Sequence[GateResult],
    context: ClaimContext,
    policy: Policy,
) -> DraftedEmail:
    """Write the merchant the explanation for a claim that cannot be processed (FR-0.4).

    The subject names the first reason, the one the policy puts first. The body
    greets the merchant, says the claim cannot be processed, then gives one short
    paragraph per reason in the order they were handed over, and ends by inviting a
    reply. Real values go into those paragraphs — the delivery date, the day count,
    the limit, exactly which details are missing — because a merchant who is told
    only "we cannot process this" has learned nothing they can act on (NFR-3).

    Args:
        case: The claim's support case. Its contact address, merchant name and case
            id all appear in the email.
        reasons: Every reason the claim was declined, already de-duplicated and
            already in the order the email should explain them. All of them are
            explained; the first also names the subject line.
        gates: All four eligibility check results, passed and failed alike. Two of
            the paragraphs read the values a check recorded, so the checks are
            searched by name rather than assumed to be in any particular position.
        context: The facts worked out about the claim up front. Used only as a
            second source for the delivery date and the day count, in case the age
            check did not record them.
        policy: The claim policy. The age limit quoted to the merchant is read from
            here, so a change to the limit changes the email (FR-0.7).

    Returns:
        An email that is written but unsent, and that says so on itself rather than
        in its wording. `to` is `None` when the case carries no contact address: the
        body is still written, the reasons still reach the representative, and the
        later sending stage is what refuses to send without a recipient.

    Raises:
        ValueError: if `reasons` is empty. An email that announces a decision and
            then explains nothing must never be written at all, let alone sent. Only
            a mistake in our own code can produce it.
    """
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
    """Write the subject line, naming the case and the first of its reasons.

    Only the first reason appears, the one the policy's email order puts there. A
    subject listing all of them would be unreadable in an inbox, and the body carries
    the full picture.
    """
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
    """Open the email by name, or neutrally when the case does not carry one.

    The merchant's name is display text that can be absent, so the fallback has to
    read like something a person would write rather than like a blank.
    """
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
    """Write the one paragraph that explains a single reason the claim was declined.

    Each reason gets its own paragraph so a merchant facing several of them can tell
    them apart, and so a fixable one is not buried inside an unfixable one.
    """
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
    """Explain that too long passed between the shipment arriving and the claim being opened.

    Names the delivery date, the date the claim was opened, the number of days between
    them and the limit, so the merchant can check the arithmetic themselves rather than
    take our word for it (NFR-3).

    The delivery date and the day count come from what the age check recorded, falling
    back to the facts worked out up front. If neither has them, the paragraph still
    states the limit and still says the claim missed it — a slightly thinner sentence is
    better than no email.
    """
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
    """Explain that this is the wrong place for the case, and that it is being passed on.

    The merchant's own recorded case type is quoted back when the case carries one, so
    they can see what we read rather than guess at what we thought they meant.
    """
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
    """Explain exactly which details are absent, and invite the merchant to send them.

    This is the only reason a merchant can actually fix, so vagueness here costs them a
    second wasted attempt. The missing items are named individually rather than summed
    up as "more information".

    If the check did not record which items were missing, the paragraph names the three
    things any damage claim needs instead. Less precise, still actionable.
    """

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
    """Find the values one of the four checks looked at, by the check's name.

    Searching by name rather than by position means a caller cannot break an email by
    handing the checks over in a different order. An empty mapping comes back when that
    check is not among those given, and the paragraph using it falls back to a sentence
    that needs no values.
    """
    for gate in gates:
        if gate.gate is gate_name:
            return gate.observed
    return {}


def _read_moment(observed: Mapping[str, str], key: str) -> datetime | None:
    """Read one date and time out of what a check recorded, or nothing if it is unusable.

    A check writes the values it looked at as text, so this reads them back. Absent or
    unreadable text gives `None`, and the caller writes a sentence that does without the
    value. A merchant getting a slightly less detailed explanation is a far better outcome
    than a claim failing to close because one recorded value was malformed (NFR-4).
    """
    written = observed.get(key)
    if written is None:
        return None
    try:
        moment = datetime.fromisoformat(written)
    except ValueError:
        return None
    # A time written with an offset is moved onto the UTC clock, which is the one clock
    # the rest of the system uses, so the date in the email is the date the check judged
    # on. A time with no offset is used exactly as written: assuming it means local time
    # would make the email depend on which machine wrote it.
    if moment.tzinfo is not None:
        return moment.astimezone(UTC)
    return moment


def _read_whole_number(observed: Mapping[str, str], key: str) -> int | None:
    """Read one whole number out of what a check recorded, or nothing if it is unusable.

    Same bargain as reading a date: an absent or malformed value costs the merchant some
    detail, never the explanation itself.
    """
    written = observed.get(key)
    if written is None:
        return None
    try:
        return int(written)
    except ValueError:
        return None


def _read_list(observed: Mapping[str, str], key: str) -> tuple[str, ...]:
    """Read a comma-separated list out of what a check recorded.

    The check for missing key information records what it could not find as one line of
    comma-separated names. Blank entries and stray spaces are dropped, and the order the
    check wrote them in is kept, so the same claim always lists them the same way
    (FR-0.6). An absent or empty value gives an empty tuple.
    """
    written = observed.get(key)
    if written is None:
        return ()
    return tuple(item.strip() for item in written.split(",") if item.strip())


def _as_list(items: Sequence[str]) -> str:
    """Join things into the list a person would write: "a, b and c".

    Used for the missing details, which a merchant has to read and act on, so it is worth
    the small effort of not handing them a comma-separated dump.
    """
    if len(items) == 1:
        return items[0]
    return f"{', '.join(items[:-1])} and {items[-1]}"


def _in_days(count: int) -> str:
    """Say a number of days the way a person would, so a one-day claim is not "1 days"."""
    if count == 1:
        return "1 day"
    return f"{count} days"


def _format_date(moment: datetime) -> str:
    """Write a date as a merchant would read it: "26 December 2025".

    Uses the month names fixed in this file, never the host's idea of them, so the same
    claim reads the same on every machine (FR-0.6).
    """
    return f"{moment.day} {MONTH_NAMES[moment.month - 1]} {moment.year}"
