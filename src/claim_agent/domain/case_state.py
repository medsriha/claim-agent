"""Whether a claim is even in a state worth answering.

Before anybody works out what a claim is worth, there is a cheaper question: is producing
a recommendation for this claim the right thing to do at all? Four of ShipBob's five
sample claims say no in some way, and nothing in the system noticed any of it:

* **One is already closed.** Somebody finished with it. Recommending a payout on a closed
  case is answering a question that is no longer open.
* **One is waiting on the merchant.** They have already been asked something and have not
  replied. Sending them a second email is the wrong move, and it is the move this system
  would make.
* **Every single one has an internal contact address.** All five are `@shipbob.com`, and
  four of them are plus-addresses on one person's mailbox. A drafted "merchant email" would
  go to ShipBob's own staff.
* **A case can be dated before its own delivery.** The day counter already hands back a
  negative number for that and deliberately declines to judge it, because deciding what a
  negative age means is a judgement rather than arithmetic. This is where it gets said out
  loud.

**No requirement covers any of this.** It came from reading the sample data. The nearest
ones are FR-0.2, which is where a claim's age is judged, and NFR-4, which says a failure
ends in front of a person.

**Nothing here stops a claim or decides anything.** It reports what it found and a person
decides. That is deliberate: every one of these is a reason to look twice, and none of them
is proof on its own. A case marked closed may have been closed in error, and an internal
address is what a test system looks like — which is exactly what this data is.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict

from claim_agent.domain.dates import whole_days_between
from claim_agent.domain.models import Case
from claim_agent.policy import Policy


class ConcernKind(StrEnum):
    """The ways a claim can be in a state that makes answering it questionable.

    Ordered as they are reported, strongest first. A closed case is the most likely to
    make the whole exercise pointless; a missing identifier is the most likely to be
    ordinary.
    """

    STATUS = "status"
    INTERNAL_CONTACT = "internal_contact"
    OPENED_BEFORE_DELIVERY = "opened_before_delivery"
    MISSING_KEY_DETAIL = "missing_key_detail"


class StateConcern(BaseModel):
    """One reason this claim may not be worth answering.

    Attributes:
        kind: Which kind of concern this is.
        found: What was actually on the record, in plain words, so a representative can
            check it rather than take it on trust.
        what_it_means: What it means for somebody about to act on a recommendation.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: ConcernKind
    found: str
    what_it_means: str


class CaseStateReview(BaseModel):
    """Everything about this claim's state that is worth a second look.

    Attributes:
        concerns: What was found, in a fixed order so two runs of the same claim read the
            same way (NFR-1). Empty is the ordinary answer and means nothing was found.
        summary: One plain sentence, ready to put in front of a representative.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    concerns: tuple[StateConcern, ...] = ()
    summary: str

    @property
    def is_worth_answering(self) -> bool:
        """True when nothing was found that makes answering this claim questionable.

        A convenience for a caller that wants one answer. It is deliberately not a
        decision: a claim with concerns is still answered, by a person who has read them.
        """
        return not self.concerns


def review_case_state(case: Case, policy: Policy) -> CaseStateReview:
    """List every reason this claim may not be in a state worth answering.

    Runs four checks, in the order they are reported. Each is a plain reading of the case
    record — there is no AI here and no threshold that is not a policy value (FR-0.6,
    FR-0.7).

    1. **Status.** Compared against the statuses policy calls unanswerable, ignoring case
       and surrounding spaces so `closed` and `Closed ` are one status.
    2. **The contact address.** Anything at the domain policy names as internal reaches
       ShipBob rather than a merchant. Plus-addressing is seen through, so
       `sakukreja+4@shipbob.com` is recognised as one person's mailbox — worth saying,
       because four of the five sample claims share it and that is what test data looks
       like.
    3. **A case opened before its own delivery date.** Reported here rather than in the
       day counter, which hands back a negative number and declines to interpret it.
    4. **Missing identifiers.** No shipment, no order or no merchant, each named
       separately so a reader knows which.

    Args:
        case: The claim's record, as ShipBob returned it.
        policy: Read for the unanswerable statuses and the internal mail domain, so both
            are settings rather than values buried here (FR-0.7, NFR-7).

    Returns:
        The concerns found, in a fixed order, and a sentence summing them up. An empty
        list is the ordinary answer. Never raises: every one of these is an observation
        about ordinary data, not a fault (NFR-4).
    """
    concerns: list[StateConcern] = []

    status = _status_concern(case, policy)
    if status is not None:
        concerns.append(status)

    contact = _contact_concern(case, policy)
    if contact is not None:
        concerns.append(contact)

    ordering = _ordering_concern(case)
    if ordering is not None:
        concerns.append(ordering)

    concerns.extend(_missing_detail_concerns(case))

    return CaseStateReview(concerns=tuple(concerns), summary=_summary_for(concerns))


def _status_concern(case: Case, policy: Policy) -> StateConcern | None:
    """Whether the case's status makes a recommendation the wrong thing to produce."""
    if case.status is None:
        return None
    status = case.status.strip()
    unanswerable = {one.strip().casefold() for one in policy.unanswerable_case_statuses}
    if status.casefold() not in unanswerable:
        return None
    return StateConcern(
        kind=ConcernKind.STATUS,
        found=f"This case's status is {status!r}.",
        what_it_means=(
            "Somebody has already finished with this case, or has asked the merchant "
            "something and is waiting for an answer. A recommendation now either answers a "
            "question that is closed or sends a second message over the top of the first."
        ),
    )


def _contact_concern(case: Case, policy: Policy) -> StateConcern | None:
    """Whether a drafted merchant email would reach ShipBob's own staff instead.

    Plus-addressing is seen through deliberately. Four of the five sample claims are
    plus-addresses on one mailbox, which is a strong hint that these are test records
    rather than real merchants — worth telling a person rather than quietly emailing.
    """
    if case.contact_email is None:
        return None
    address = case.contact_email.strip()
    _, _, domain = address.partition("@")
    if domain.casefold() != policy.internal_email_domain.strip().casefold():
        return None
    mailbox, _, _ = address.partition("@")
    root, plus, tag = mailbox.partition("+")
    shared = (
        f" It is a plus-address on {root}'s mailbox, tagged {tag!r}, so several claims may "
        "share one recipient."
        if plus
        else ""
    )
    return StateConcern(
        kind=ConcernKind.INTERNAL_CONTACT,
        found=f"The contact address on this case is {address}.{shared}",
        what_it_means=(
            "That address is inside ShipBob, not a merchant's. An email drafted for the "
            "merchant would go to ShipBob's own staff, and nobody outside would hear "
            "anything."
        ),
    )


def _ordering_concern(case: Case) -> StateConcern | None:
    """Whether the case was opened before the parcel it is about was delivered."""
    if case.delivered_date is None:
        return None
    days = whole_days_between(case.delivered_date, case.created_date)
    if days >= 0:
        return None
    return StateConcern(
        kind=ConcernKind.OPENED_BEFORE_DELIVERY,
        found=(
            f"This case was opened on {case.created_date.date().isoformat()}, "
            f"{abs(days)} day(s) before its parcel was delivered on "
            f"{case.delivered_date.date().isoformat()}."
        ),
        what_it_means=(
            "A claim about damage cannot honestly predate the delivery it is about. Either "
            "one of the two dates is wrong, or this case is about a different parcel. The "
            "age limit is measured between exactly these two dates, so it cannot be "
            "trusted here either."
        ),
    )


def _missing_detail_concerns(case: Case) -> list[StateConcern]:
    """One concern per identifier the case does not carry.

    Named separately rather than rolled into one, because they lead different places: no
    shipment means nothing can be priced, and no merchant means nobody can be written to.
    """
    missing = [
        (case.shipment_id, "shipment", "nothing can be priced and no invoice can be asked for"),
        (case.order_id, "order", "there is no record of what was bought"),
        (case.user_id, "merchant", "there is nobody to write to and no past claims to look up"),
    ]
    return [
        StateConcern(
            kind=ConcernKind.MISSING_KEY_DETAIL,
            found=f"This case names no {what}.",
            what_it_means=f"Without it, {consequence}.",
        )
        for value, what, consequence in missing
        if value is None
    ]


def _summary_for(concerns: list[StateConcern]) -> str:
    """One sentence a representative can read without working anything out."""
    if not concerns:
        return "Nothing about this case's state makes it questionable to answer."
    return (
        f"There are {len(concerns)} thing(s) about this case's state worth looking at before "
        "acting on any recommendation."
    )
