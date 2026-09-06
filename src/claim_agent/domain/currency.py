from __future__ import annotations

from collections.abc import Sequence
from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum

from pydantic import BaseModel, ConfigDict

from claim_agent.policy import Policy

USD = "USD"
"""The currency the cap is written in, and the only one that needs no rate to convert."""

CURRENCIES_BY_SYMBOL: dict[str, tuple[str, ...]] = {
    "£": ("GBP",),
    "€": ("EUR",),
    "$": ("USD", "CAD", "AUD"),
    "¥": ("JPY", "CNY"),
}
"""What a currency symbol narrows the money down to — often not to one currency."""

CURRENCIES_BY_COUNTRY: dict[str, str] = {
    "GB": "GBP",
    "US": USD,
    "CA": "CAD",
    "AU": "AUD",
    "IE": "EUR",
    "DE": "EUR",
    "FR": "EUR",
    "IT": "EUR",
    "ES": "EUR",
    "NL": "EUR",
}
"""The currency of the country a tracking number ends in."""

CURRENCIES_BY_CARRIER: dict[str, str] = {
    "royal mail": "GBP",
    "evri": "GBP",
    "parcelforce": "GBP",
    "usps": USD,
    "fedex": USD,
    "canada post": "CAD",
    "australia post": "AUD",
}
"""The currency suggested by a carrier that only operates in one country."""


class SignalSource(StrEnum):
    """Where a clue about the currency came from, strongest first."""

    SYMBOL_ON_EVIDENCE = "symbol_on_evidence"
    TRACKING_COUNTRY = "tracking_country"
    CARRIER_NAME = "carrier_name"


class CurrencySignal(BaseModel):
    """One clue about which currency a claim's money is in."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    source: SignalSource
    detail: str
    currencies: tuple[str, ...]


class CurrencyFinding(BaseModel):
    """What currency a claim's figures are in, and how confident anyone should be."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    currency: str | None = None
    is_ambiguous: bool = False
    confidence: float = 0.0
    reason: str
    signals: tuple[CurrencySignal, ...] = ()


class ConversionResult(BaseModel):
    """A figure turned into dollars, or an explanation of why it was not."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    original_amount: str
    currency: str | None
    usd_amount: str | None = None
    rate_used: str | None = None
    rates_as_of: str
    converted: bool = False
    assumed_usd: bool = False
    summary: str


def normalise_currency(currency: str | None) -> str | None:
    """Put a currency code in the one form everything here compares."""
    if currency is None:
        return None
    tidied = currency.strip().upper()
    return tidied or None


def convert_to_usd(amount: Decimal, currency: str | None, policy: Policy) -> ConversionResult:
    """Say what a figure is worth in dollars, so the cap can be applied to it (FR-1.20)."""
    original = _money(amount)
    code = normalise_currency(currency)
    rates_as_of = policy.conversion_rates_as_of

    if code == USD:
        return ConversionResult(
            original_amount=original,
            currency=USD,
            usd_amount=original,
            rate_used="1.00",
            rates_as_of=rates_as_of,
            converted=True,
            summary=f"{original} is already in dollars.",
        )

    rate = _rate_for(code, policy)
    if rate is None:
        if policy.assume_usd_when_currency_unknown:
            return ConversionResult(
                original_amount=original,
                currency=code,
                usd_amount=original,
                rate_used="1.00",
                rates_as_of=rates_as_of,
                converted=True,
                assumed_usd=True,
                summary=(
                    f"Nothing says what currency {original} is in, so it was read as dollars "
                    "because policy allows that. Somebody should confirm it."
                ),
            )
        unknown = (
            f"{code} is not a currency this system has a rate for"
            if code
            else ("Nothing says what currency this figure is in")
        )
        return ConversionResult(
            original_amount=original,
            currency=code,
            rates_as_of=rates_as_of,
            summary=(
                f"{unknown}, so {original} cannot be compared with the dollar cap. "
                "This claim needs a person."
            ),
        )

    converted = _to_cents(amount * rate)
    return ConversionResult(
        original_amount=original,
        currency=code,
        usd_amount=_money(converted),
        rate_used=_money(rate),
        rates_as_of=rates_as_of,
        converted=True,
        summary=(
            f"{original} {code} is {_money(converted)} dollars at {_money(rate)} "
            f"to the {code}, the rate recorded on {rates_as_of}."
        ),
    )


def currency_for_claim(
    *,
    tracking_number: str | None = None,
    carrier: str | None = None,
    symbols_seen: Sequence[str] = (),
) -> CurrencyFinding:
    """Work out which currency a claim's figures are in, from what the claim carries."""
    signals = _signals_from(
        tracking_number=tracking_number, carrier=carrier, symbols_seen=symbols_seen
    )
    if not signals:
        return CurrencyFinding(
            reason=(
                "Nothing on this claim says what currency its figures are in — no symbol on "
                "the evidence, no country in the tracking number, and a carrier that works in "
                "more than one country."
            )
        )

    candidate = next((one for one in signals if len(one.currencies) == 1), None)
    if candidate is None:
        listed = _and_list(sorted({code for signal in signals for code in signal.currencies}))
        return CurrencyFinding(
            is_ambiguous=True,
            reason=(
                f"The clues on this claim narrow the money down to {listed} and no further. "
                "Somebody has to say which."
            ),
            signals=signals,
        )

    chosen = candidate.currencies[0]
    disagreeing = tuple(one for one in signals if chosen not in one.currencies)
    if disagreeing:
        objection = _and_list([one.detail for one in disagreeing])
        return CurrencyFinding(
            is_ambiguous=True,
            reason=(
                f"{candidate.detail}, which points at {chosen}, but {objection}. The clues "
                "contradict each other, so nothing was concluded."
            ),
            signals=signals,
        )

    agreeing = tuple(one for one in signals if one.currencies == (chosen,))
    return CurrencyFinding(
        currency=chosen,
        confidence=_confidence_from(len(agreeing)),
        reason=f"{_and_list([one.detail for one in agreeing])}, so the money is {chosen}.",
        signals=signals,
    )


def _signals_from(
    *,
    tracking_number: str | None,
    carrier: str | None,
    symbols_seen: Sequence[str],
) -> tuple[CurrencySignal, ...]:
    """Gather every clue the claim carries, strongest first."""
    signals: list[CurrencySignal] = []

    for symbol in _unique(symbols_seen):
        currencies = CURRENCIES_BY_SYMBOL.get(symbol)
        if currencies is None:
            continue
        signals.append(
            CurrencySignal(
                source=SignalSource.SYMBOL_ON_EVIDENCE,
                detail=f"the evidence shows a {symbol} sign",
                currencies=currencies,
            )
        )

    country = _country_from_tracking(tracking_number)
    if country is not None:
        signals.append(
            CurrencySignal(
                source=SignalSource.TRACKING_COUNTRY,
                detail=f"the tracking number ends {country}",
                currencies=(CURRENCIES_BY_COUNTRY[country],),
            )
        )

    named = _carrier_currency(carrier)
    if named is not None:
        signals.append(
            CurrencySignal(
                source=SignalSource.CARRIER_NAME,
                detail=f"the carrier is {carrier}",
                currencies=(named,),
            )
        )

    return tuple(signals)


def _country_from_tracking(tracking_number: str | None) -> str | None:
    """The country a postal tracking number was posted in, or `None`."""
    if tracking_number is None:
        return None
    tidied = tracking_number.strip().upper()
    if len(tidied) < 4 or not tidied[:-2].isalnum() or not any(c.isdigit() for c in tidied):
        return None
    suffix = tidied[-2:]
    return suffix if suffix in CURRENCIES_BY_COUNTRY else None


def _carrier_currency(carrier: str | None) -> str | None:
    """The currency a single-country carrier suggests, or `None` for one that says nothing."""
    if carrier is None:
        return None
    lowered = carrier.strip().lower()
    if not lowered:
        return None
    return next(
        (code for name, code in CURRENCIES_BY_CARRIER.items() if name in lowered),
        None,
    )


def _rate_for(currency: str | None, policy: Policy) -> Decimal | None:
    """What one unit of this currency is worth in dollars, or `None` if we do not know."""
    if currency is None:
        return None
    for code, rate in policy.usd_conversion_rates.items():
        if code.strip().upper() == currency:
            return Decimal(rate)
    return None


def _confidence_from(agreeing: int) -> float:
    """How sure to be, given how many independent clues agree."""
    return {1: 0.5, 2: 0.75}.get(agreeing, 0.9)


def _unique(values: Sequence[str]) -> list[str]:
    """The values, each kept once, in the order they first appeared."""
    seen: dict[str, None] = {}
    for value in values:
        seen.setdefault(value.strip(), None)
    return [value for value in seen if value]


def _and_list(parts: Sequence[str]) -> str:
    """Join phrases the way a sentence would, so the reason reads as English."""
    if not parts:
        return ""
    if len(parts) == 1:
        return parts[0]
    return f"{', '.join(parts[:-1])} and {parts[-1]}"


def _to_cents(amount: Decimal) -> Decimal:
    """Round to whole cents, half a cent going up."""
    return amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _money(amount: Decimal) -> str:
    """Write a figure out with two decimal places, for a person to read."""
    return f"{amount:.2f}"
