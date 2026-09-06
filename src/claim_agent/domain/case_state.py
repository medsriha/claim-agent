from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict

from claim_agent.domain.dates import whole_days_between
from claim_agent.domain.models import Case
from claim_agent.policy import Policy


class ConcernKind(StrEnum):
    """The ways a claim can be in a state that makes answering it questionable."""

    STATUS = "status"
    INTERNAL_CONTACT = "internal_contact"
    OPENED_BEFORE_DELIVERY = "opened_before_delivery"
    MISSING_KEY_DETAIL = "missing_key_detail"


class StateConcern(BaseModel):
    """One reason this claim may not be worth answering."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: ConcernKind
    found: str
    what_it_means: str


class CaseStateReview(BaseModel):
    """Everything about this claim's state that is worth a second look."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    concerns: tuple[StateConcern, ...] = ()
    summary: str

    @property
    def is_worth_answering(self) -> bool:
        """True when nothing was found that makes answering this claim questionable."""
        return not self.concerns


def review_case_state(case: Case, policy: Policy) -> CaseStateReview:
    """List every reason this claim may not be in a state worth answering."""
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
    """Whether a drafted merchant email would reach ShipBob's own staff instead."""
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
    """One concern per identifier the case does not carry."""
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
