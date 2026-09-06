from __future__ import annotations

from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import AfterValidator, AwareDatetime, BaseModel, BeforeValidator, ConfigDict


def _to_utc(value: datetime) -> datetime:
    """Move a moment in time onto the UTC clock without changing the instant it names."""
    return value.astimezone(UTC)


def _blank_to_none(value: object) -> object:
    """Turn an empty or whitespace-only piece of text into \"no value at all\"."""
    if isinstance(value, str) and not value.strip():
        return None
    return value


UtcDatetime = Annotated[AwareDatetime, AfterValidator(_to_utc)]


BlankToNone = Annotated[str | None, BeforeValidator(_blank_to_none)]


class Verdict(StrEnum):
    """The two ways the pre-flight screen can end (FR-0.3)."""

    PROCEED = "proceed"
    TERMINAL = "terminal"


class GateName(StrEnum):
    """The four eligibility checks a claim has to pass (FR-0.2)."""

    AGE = "age"
    CLAIM_TYPE = "claim_type"
    KEY_INFORMATION = "key_information"
    INSURANCE = "insurance"


class TerminalReason(StrEnum):
    """Why a claim was stopped before anyone investigated it (FR-0.3, FR-0.4)."""

    SHIPMENT_INSURED = "shipment_insured"
    CLAIM_TOO_OLD = "claim_too_old"
    WRONG_CLAIM_TYPE = "wrong_claim_type"
    MISSING_KEY_INFORMATION = "missing_key_information"


class OrderLineItem(BaseModel):
    """One product on the order: what it was, how many, and what each one cost."""

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
    """The order a damaged shipment came from, and the products on it."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    order_id: str
    user_id: BlankToNone = None
    line_items: tuple[OrderLineItem, ...] = ()
    created_date: UtcDatetime | None = None

    @property
    def total_value(self) -> Decimal:
        """Add up what every line on the order was worth, to the nearest cent."""
        total = sum((item.line_total for item in self.line_items), start=Decimal("0"))
        return total.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


class Attachment(BaseModel):
    """One image the merchant uploaded to the case — a photo, or a screenshot."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    attachment_id: str
    url: str
    file_name: BlankToNone = None
    content_type: BlankToNone = None


class Invoice(BaseModel):
    """ShipBob's priced record of what a shipment contained (FR-1.18)."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    invoice_id: str
    shipment_id: BlankToNone = None
    line_items: tuple[OrderLineItem, ...] = ()
    generated_at: UtcDatetime | None = None


class Shipment(BaseModel):
    """The parcel the claim is about: who carried it, where it got to, and whether it was insured."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    shipment_id: str

    is_insured: bool
    order_id: BlankToNone = None
    carrier: BlankToNone = None
    tracking_number: BlankToNone = None
    status: BlankToNone = None
    delivered_date: UtcDatetime | None = None


class Case(BaseModel):
    """The support case a merchant opened, and the ids that lead to everything else."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    case_id: str

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
    """Something a rep changed on an earlier claim from the same merchant (FR-3.8)."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    user_id: str
    case_id: str
    summary: str
    recorded_at: UtcDatetime


class DraftedEmail(BaseModel):
    """An email to the merchant that has been written but not sent, and cannot send itself."""

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
        """Return approval wording carrying the exact figure."""
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
