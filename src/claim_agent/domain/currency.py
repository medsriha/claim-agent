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
"""What a currency symbol narrows the money down to — often not to one currency.

`£` and `€` name a currency on their own. **`$` does not**, and treating it as dollars
is the single easiest mistake to make here: Canada and Australia both write their money
with it, and a Canadian claim read as American is off by about a quarter. A symbol that
points at more than one currency is reported as pointing at more than one.

Deliberately short. Every symbol listed is one the sample data could plausibly contain;
guessing at the rest would put currencies on screen that nobody has confirmed ShipBob
ever sees.
"""

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
"""The currency of the country a tracking number ends in.

International tracking numbers in the postal format finish with the two-letter code of
the country that posted the parcel — `XQ607930599GB` was posted in Great Britain. That
is a clue about where the parcel started, which is usually but not always where the
merchant prices things.
"""

CURRENCIES_BY_CARRIER: dict[str, str] = {
    "royal mail": "GBP",
    "evri": "GBP",
    "parcelforce": "GBP",
    "usps": USD,
    "fedex": USD,
    "canada post": "CAD",
    "australia post": "AUD",
}
"""The currency suggested by a carrier that only operates in one country.

Matched on the carrier name containing one of these, lower-cased, so
`Royal Mail Tracked 48` matches `royal mail`.

**This is the weakest of the three clues and is listed last for that reason.** A carrier
tells you who moved the parcel, not who priced it, and several carriers in the sample
data — `CirroECommerce`, `UniUni`, and the literal string `Other` — say nothing at all
about a country. Those simply produce no signal, which is an ordinary outcome.
"""


class SignalSource(StrEnum):
    """Where a clue about the currency came from, strongest first.

    The order is the order they are trusted in, and it is not arbitrary. A symbol
    somebody photographed is the only clue where a human being actually wrote down
    what the money was; everything else is us inferring it from geography.
    """

    SYMBOL_ON_EVIDENCE = "symbol_on_evidence"
    TRACKING_COUNTRY = "tracking_country"
    CARRIER_NAME = "carrier_name"


class CurrencySignal(BaseModel):
    """One clue about which currency a claim's money is in.

    Attributes:
        source: Where the clue came from.
        detail: The clue in plain words, ready to show a representative — "the tracking
            number ends GB". This is what makes the finding arguable rather than
            something a person has to take on trust.
        currencies: What the clue narrows the money down to. **More than one means the
            clue is itself ambiguous** — a `$` is the usual reason — and a clue like that
            can still rule a currency *out* even when it cannot pick one.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    source: SignalSource
    detail: str
    currencies: tuple[str, ...]


class CurrencyFinding(BaseModel):
    """What currency a claim's figures are in, and how confident anyone should be.

    Attributes:
        currency: The currency, or `None` when nothing established one. `None` is an
            ordinary answer — most claims carry no clue at all.
        is_ambiguous: True when two clues contradict each other. **Then `currency` is
            `None` as well**, deliberately: a contradicted answer is worse than no
            answer, because it looks like a conclusion.
        confidence: From 0 to 1, rising with the number of clues that agree.
        reason: One plain sentence a representative can agree or disagree with.
        signals: Every clue found, in trust order, so the reasoning can be checked.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    currency: str | None = None
    is_ambiguous: bool = False
    confidence: float = 0.0
    reason: str
    signals: tuple[CurrencySignal, ...] = ()


class ConversionResult(BaseModel):
    """A figure turned into dollars, or an explanation of why it was not.

    Every amount is text, because that is how money moves through this system without
    ever passing through a floating point number.

    Attributes:
        original_amount: What went in.
        currency: The currency it was read as, normalised to upper case. `None` when the
            caller could not say.
        usd_amount: The figure in dollars, or `None` when no conversion happened. A
            `None` here is the signal that the cap **cannot** be applied yet.
        rate_used: What one unit was taken to be worth in dollars.
        rates_as_of: The day the rate table was written down, so a reader can judge how
            stale it is.
        converted: Whether a dollar figure came out.
        assumed_usd: True when an unknown currency was treated as dollars because policy
            allows it. Worth showing on screen: it is the one path here that guesses.
        summary: One plain sentence saying what happened.
    """

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
    """Put a currency code in the one form everything here compares.

    Upper case, trimmed. `gbp`, ` GBP ` and `GBP` are one currency; a blank string is no
    currency at all rather than an empty one, so a missing value and a value somebody
    typed a space into behave the same way.
    """
    if currency is None:
        return None
    tidied = currency.strip().upper()
    return tidied or None


def convert_to_usd(amount: Decimal, currency: str | None, policy: Policy) -> ConversionResult:
    """Say what a figure is worth in dollars, so the cap can be applied to it (FR-1.20).

    **The rate comes from a fixed table in `policy.py`, not from a live rate service, and
    that is a deliberate trade.** A live rate would be more accurate and would make this
    system non-deterministic: the same claim, screened twice ten minutes apart, could be
    inside the cap once and outside it the next time, which is exactly the run-to-run
    variance NFR-1 forbids. It would also add a network call that can fail in the middle
    of judging a claim. A stale rate is a known, visible error; a moving one is an
    invisible one. The table's date rides along on the result so nobody has to guess how
    old it is.

    Dollars convert to dollars without consulting the table at all, so a mistyped rate
    entry can never disturb a claim that was already in the right currency.

    A currency the table does not know does **not** become dollars. It comes back
    unconverted, and the claim needs a person. `policy.assume_usd_when_currency_unknown`
    can turn that off — it defaults to false, and the result says plainly when it was
    used, because it is the one path here that guesses at money.

    Args:
        amount: The figure, already read into an exact decimal. Never a float.
        currency: What currency it is in. `None` when nobody could establish one, which
            is treated exactly like a currency the table does not know.
        policy: Read for the rate table, its date, and whether guessing is allowed
            (FR-0.7, NFR-7).

    Returns:
        The figure in dollars, or a result saying why there isn't one. Never raises for
        an unknown currency: that is an ordinary answer this system has to carry on from
        (NFR-4).
    """
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
    """Work out which currency a claim's figures are in, from what the claim carries.

    ShipBob's records never say, so this reads the clues that are actually there. Three
    of them, in the order they are trusted:

    1. **A currency symbol somebody photographed.** The strongest, because it is the only
       one where a person wrote the currency down rather than us inferring it. A `£` on
       the merchant's own order screen settles the question; a `$` narrows it to three.
    2. **The country a tracking number ends in.** `XQ607930599GB` was posted in Great
       Britain.
    3. **The carrier's name**, when the carrier only operates in one country.

    **Two clues that contradict each other produce no answer at all.** Not the strongest
    one, not a majority vote — nothing, flagged as ambiguous, for a person to settle. A
    parcel posted in Great Britain whose paperwork shows a `$` is a genuine puzzle: it
    might be a British merchant pricing in dollars, or it might be a photograph from a
    different order entirely. Picking one silently is how a claim gets capped against the
    wrong number, and FR-1.13 already says this system does not narrow candidates to one
    when the evidence will not.

    Note that an ambiguous clue can still contradict. A `$` cannot say which of three
    currencies it is, but it says the money is not pounds.

    Args:
        tracking_number: The parcel's tracking number, from the shipment record.
        carrier: The carrier's name, from the shipment record.
        symbols_seen: Currency symbols read off the claim's evidence, in the order they
            were found. Empty when nobody looked or nothing was legible.

    Returns:
        The currency and how sure to be. Everything is optional and no clue at all is the
        ordinary case, answered with `currency` of `None` and a reason saying so.
    """
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
    """Gather every clue the claim carries, strongest first.

    Symbols are de-duplicated on the symbol itself, so the same `£` read off four
    photographs is one clue rather than four — otherwise a merchant who attached more
    screenshots would look more convincing than one who attached fewer.
    """
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
    """The country a postal tracking number was posted in, or `None`.

    Postal tracking numbers finish with the two letters of the posting country. Only the
    countries in the table above are recognised, and only when the rest of the number
    looks like a tracking number rather than a word — a plain English word ending in two
    letters must not be read as a country code.
    """
    if tracking_number is None:
        return None
    tidied = tracking_number.strip().upper()
    if len(tidied) < 4 or not tidied[:-2].isalnum() or not any(c.isdigit() for c in tidied):
        return None
    suffix = tidied[-2:]
    return suffix if suffix in CURRENCIES_BY_COUNTRY else None


def _carrier_currency(carrier: str | None) -> str | None:
    """The currency a single-country carrier suggests, or `None` for one that says nothing.

    `Other`, `CirroECommerce` and `UniUni` all appear in the sample data and all return
    `None`, which is the ordinary outcome rather than a problem.
    """
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
    """What one unit of this currency is worth in dollars, or `None` if we do not know.

    The table is matched case-insensitively so an operator setting it from the
    environment cannot break it with a lower-case key.
    """
    if currency is None:
        return None
    for code, rate in policy.usd_conversion_rates.items():
        if code.strip().upper() == currency:
            return Decimal(rate)
    return None


def _confidence_from(agreeing: int) -> float:
    """How sure to be, given how many independent clues agree.

    One clue is a hint, two is a case, three is about as good as this data gets. It never
    reaches 1: none of these clues is authoritative, and a figure that says "certain"
    would invite somebody to stop checking.
    """
    return {1: 0.5, 2: 0.75}.get(agreeing, 0.9)


def _unique(values: Sequence[str]) -> list[str]:
    """The values, each kept once, in the order they first appeared.

    Order is kept because the reason sentence lists them, and a reason that reorders
    itself between two runs of the same claim reads as a different answer (NFR-1).
    """
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
    """Round to whole cents, half a cent going up.

    Rounding is stated rather than left to the default, because the default rounds half
    to even and would settle two otherwise identical claims a cent apart. Money a person
    has to reconcile should round the way they were taught at school.
    """
    return amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _money(amount: Decimal) -> str:
    """Write a figure out with two decimal places, for a person to read."""
    return f"{amount:.2f}"
