from __future__ import annotations

from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import AfterValidator, AwareDatetime, BaseModel, BeforeValidator, ConfigDict


def _to_utc(value: datetime) -> datetime:
    """Move a moment in time onto the UTC clock without changing the instant it names.

    Keeping one clock across the whole system is how an age check avoids landing
    a day out because two dates were written in two different timezones
    (FR-0.2, FR-0.6).
    """
    return value.astimezone(UTC)


def _blank_to_none(value: object) -> object:
    """Turn an empty or whitespace-only piece of text into "no value at all".

    ShipBob writes `""` where a field is absent. Kept as it is, an empty shipment
    id would look like an answer and the check for missing key information would
    let through a case that has nothing to investigate (FR-0.2).

    Anything that is not text is handed back untouched, so pydantic still reports
    its own error for, say, a number where words were expected.
    """
    if isinstance(value, str) and not value.strip():
        return None
    return value


# A moment in time that has to arrive with a timezone and is kept in UTC. A time
# with no timezone is refused rather than guessed at: guessing would make the
# answer depend on the machine that happened to run the check.
UtcDatetime = Annotated[AwareDatetime, AfterValidator(_to_utc)]

# A piece of text that may be absent, where blank counts as absent.
BlankToNone = Annotated[str | None, BeforeValidator(_blank_to_none)]


class Verdict(StrEnum):
    """The two ways the pre-flight screen can end (FR-0.3).

    `PROCEED` means nothing rules the claim out, so the investigation runs.
    `TERMINAL` means the claim cannot be processed at all: the investigation is
    skipped, and the rep instead gets an explanation to approve (FR-0.4).
    """

    PROCEED = "proceed"
    TERMINAL = "terminal"


class GateName(StrEnum):
    """The four eligibility checks a claim has to pass (FR-0.2).

    A "gate" is one yes-or-no check. `AGE` asks whether too long passed between
    delivery and the claim being filed. `CLAIM_TYPE` asks whether this is a
    damaged-in-transit claim, the only kind handled here. `KEY_INFORMATION` asks
    whether the shipment, the order and the merchant's description are all
    present. `INSURANCE` asks whether the shipment was insured, because insured
    shipments follow an entirely different process.
    """

    AGE = "age"
    CLAIM_TYPE = "claim_type"
    KEY_INFORMATION = "key_information"
    INSURANCE = "insurance"


class TerminalReason(StrEnum):
    """Why a claim was stopped before anyone investigated it (FR-0.3, FR-0.4).

    There is one reason per check that can fail, and a single claim may collect
    more than one of them.
    """

    SHIPMENT_INSURED = "shipment_insured"
    CLAIM_TOO_OLD = "claim_too_old"
    WRONG_CLAIM_TYPE = "wrong_claim_type"
    MISSING_KEY_INFORMATION = "missing_key_information"


class OrderLineItem(BaseModel):
    """One product on the order: what it was, how many, and what each one cost.

    The price is what the merchant paid at the time the order was fulfilled,
    which is what any reimbursement is worked out from (FR-1.18). Money is held
    as an exact decimal rather than a floating point number so cents cannot
    drift.

    `product_id` and `sku` may be absent. The line still counts towards the value
    of the order without them; it is only harder to match to a photograph of the
    damage.
    """

    model_config = ConfigDict(frozen=True, extra="ignore")

    product_id: BlankToNone = None
    name: str
    sku: BlankToNone = None
    quantity: int
    unit_price: Decimal

    @property
    def line_total(self) -> Decimal:
        """What this line was worth altogether: the price of one, times how many."""
        return self.unit_price * self.quantity


class Order(BaseModel):
    """The order a damaged shipment came from, and the products on it.

    ShipBob's order record carries no total of any kind — there is no subtotal,
    tax, shipping or discount field anywhere in it — so what an order was worth
    is added up from its lines (FR-0.5).

    An order that arrives with no lines totals zero. That is a statement about
    the data we were given, not about the order, and the caller has to decide
    what to make of it.
    """

    model_config = ConfigDict(frozen=True, extra="ignore")

    order_id: str
    user_id: BlankToNone = None
    line_items: tuple[OrderLineItem, ...] = ()
    created_date: UtcDatetime | None = None

    @property
    def total_value(self) -> Decimal:
        """Add up what every line on the order was worth, to the nearest cent.

        Rounded half up to two decimal places, the way money is normally rounded,
        so the same order always produces the same figure (FR-0.6). An order with
        no lines comes to `0.00`.
        """
        total = sum((item.line_total for item in self.line_items), start=Decimal("0"))
        return total.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


class Attachment(BaseModel):
    """One image the merchant uploaded to the case — a photo, or a screenshot.

    Attachments are the evidence a damaged-in-transit claim rests on: pictures of
    the broken product, pictures of the box it arrived in, a photograph of an
    invoice, a screenshot of the end customer saying the parcel arrived damaged.

    `attachment_id` is stable, so a finding can always name the exact image that
    produced it (FR-2.2). `url` is where the image itself can be fetched from.

    `file_name` and `content_type` are carried because ShipBob sends them, and are
    **never** used to decide what an image is. They carry no signal at all: every
    attachment in every sample case is a PNG or a JPEG whatever it depicts, two
    files in one case have nearly identical names and are different kinds of
    evidence, and names across the set include `329233.png`. What an attachment is
    can only be settled by looking at it (FR-1.4).
    """

    model_config = ConfigDict(frozen=True, extra="ignore")

    attachment_id: str
    url: str
    file_name: BlankToNone = None
    content_type: BlankToNone = None


class Invoice(BaseModel):
    """ShipBob's priced record of what a shipment contained (FR-1.18).

    Generated on request rather than stored, and it is the document a recommended
    reimbursement is priced from: the agent says which products were damaged, and
    the amount is worked out from these lines.

    The lines are held as `OrderLineItem`, the same shape the order uses, because
    the two payloads are field for field identical — ShipBob's generated invoice
    applies no discount and has no discount field. Giving the same data two shapes
    would only invite them to drift apart.

    Two things about this record do not match what the requirements ask of it, and
    both are ShipBob's data rather than our handling of it. It carries no discount,
    so "the price after discounts" cannot be read from it. And `generated_at` is
    the same fixed moment on every invoice in the sample set, postdating every
    delivery, so it is a snapshot taken at claim time rather than a record frozen
    at fulfilment.

    An invoice that arrives with no lines prices nothing. That is a statement about
    the data we were given, and the caller has to decide what to make of it.
    """

    model_config = ConfigDict(frozen=True, extra="ignore")

    invoice_id: str
    shipment_id: BlankToNone = None
    line_items: tuple[OrderLineItem, ...] = ()
    generated_at: UtcDatetime | None = None


class Shipment(BaseModel):
    """The parcel the claim is about: who carried it, where it got to, and whether it was insured.

    A missing `delivered_date` means the parcel has no recorded delivery, so the
    age of the claim cannot be measured from this record.
    """

    model_config = ConfigDict(frozen=True, extra="ignore")

    shipment_id: str
    # No default on purpose. An insured shipment follows a completely different
    # process and must never be handled here (FR-0.2), so a payload that says
    # nothing about insurance has to fail loudly. Defaulting to "not insured"
    # would quietly produce the one outcome this check exists to prevent.
    is_insured: bool
    order_id: BlankToNone = None
    carrier: BlankToNone = None
    tracking_number: BlankToNone = None
    status: BlankToNone = None
    delivered_date: UtcDatetime | None = None


class Case(BaseModel):
    """The support case a merchant opened, and the ids that lead to everything else.

    The case is the starting point of an investigation: it names the order and
    the shipment, so every other read follows from it (FR-0.1). `description` is
    the merchant's own account of what happened, in their words.

    Most fields may be absent, and that absence is itself information: a case
    with no shipment, no order or no description has nothing to investigate
    (FR-0.2). `delivered_date` also appears on the shipment, and the two records
    can disagree, so whoever uses it has to say which one they took.
    """

    model_config = ConfigDict(frozen=True, extra="ignore")

    case_id: str
    # Required, unlike almost everything else here. This is the moment the
    # merchant filed the claim, and the age check measures from delivery to
    # exactly this point (FR-0.2). Substituting today's date for a missing one
    # would make an ancient claim look freshly filed.
    created_date: UtcDatetime
    status: BlankToNone = None
    sub_category: BlankToNone = None
    description: BlankToNone = None
    order_id: BlankToNone = None
    user_id: BlankToNone = None
    shipment_id: BlankToNone = None
    delivered_date: UtcDatetime | None = None
    contact_email: BlankToNone = None
    account_name: BlankToNone = None


class MerchantCorrection(BaseModel):
    """Something a rep changed on an earlier claim from the same merchant (FR-3.8).

    The pre-flight screen looks these up and passes them on as starting context,
    so a correction a rep made once does not have to be made again the next time
    that merchant files (FR-0.5).

    Merchants are identified by `user_id`, which is stable, and never by the
    account name, which is display text and can change. `summary` is a plain
    sentence saying what the rep changed and why; `case_id` is the earlier claim
    it was made on, so a rep can go and read it.
    """

    model_config = ConfigDict(frozen=True, extra="ignore")

    user_id: str
    case_id: str
    summary: str
    recorded_at: UtcDatetime


class DraftedEmail(BaseModel):
    """An email to the merchant that has been written but not sent, and cannot send itself.

    Every merchant email waits for a rep to approve it, including the one
    explaining that a claim cannot be processed at all (FR-0.4, FR-2.7).
    `is_draft` is fixed at true and will not accept any other value, so nothing
    in a report can describe itself as already sent, however confident it is
    (FR-1.17).

    `to` is the address taken from the case. It is `None` when the case carries
    no contact email: the draft is still written, and the rep supplies an address
    before approving it.
    """

    model_config = ConfigDict(frozen=True, extra="ignore")

    to: str | None
    subject: str
    body: str
    is_draft: Literal[True] = True

    def with_approved_amount(
        self,
        amount_usd: Decimal,
        *,
        previous_amount_usd: Decimal | None = None,
    ) -> DraftedEmail:
        """Return approval wording carrying the exact figure.

        The model's wording carries no amount, so the figure is appended on its own line.
        When a representative changes the approved figure, the one already written is
        replaced so the email never shows two.
        """
        figure = f"${amount_usd.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)}"
        subject = self.subject
        body = self.body
        if previous_amount_usd is not None:
            previous = f"${previous_amount_usd.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)}"
            if previous != figure:
                subject = subject.replace(previous, figure)
                body = body.replace(previous, figure)
        if figure not in subject and figure not in body:
            body = f"{body.rstrip()}\n\nApproved amount: {figure}"
        return self.model_copy(update={"subject": subject, "body": body})
