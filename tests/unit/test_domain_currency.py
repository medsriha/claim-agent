"""Which currency a claim is in, and what its figures are worth in dollars.

No requirement covers currency — REQUIREMENTS.md never mentions it and ShipBob's API has
no currency field. These tests pin the behaviour worked out from the sample data, and
the nearest requirements they serve: the dollar cap (FR-1.20), never narrowing two
candidates to one (FR-1.13), the same answer twice (NFR-1), and failing toward a person
(NFR-4).
"""

from __future__ import annotations

from decimal import Decimal

from claim_agent.domain.currency import (
    CurrencyFinding,
    SignalSource,
    convert_to_usd,
    currency_for_claim,
    normalise_currency,
)
from claim_agent.policy import Policy


def a_policy(**overrides: object) -> Policy:
    """A policy with its shipped defaults, unless a test needs one value changed."""
    return Policy(**overrides)  # type: ignore[arg-type]


# --- Converting a figure to dollars -----------------------------------------


def test_pounds_become_dollars_at_the_recorded_rate() -> None:
    """FR-1.20: the cap is a dollar figure, so a pound figure has to become one."""
    result = convert_to_usd(Decimal("55.95"), "GBP", a_policy())

    assert result.converted is True
    assert result.usd_amount == "71.06"
    assert result.rate_used == "1.27"
    assert result.rates_as_of == "2026-09-04"
    assert result.assumed_usd is False


def test_dollars_pass_through_without_consulting_the_rate_table() -> None:
    """A claim already in dollars must not be disturbed by a mistyped rate entry."""
    policy = a_policy(usd_conversion_rates={"USD": Decimal("999.00")})

    result = convert_to_usd(Decimal("90.00"), "usd", policy)

    assert result.usd_amount == "90.00"
    assert result.rate_used == "1.00"


def test_case_1001_is_inside_the_cap_as_dollars_and_outside_it_as_pounds() -> None:
    """The real CASE-1001 order totals 90.00 with no currency stated anywhere.

    This is the whole reason the module exists. Read as dollars the order sits under the
    $100 cap; read as pounds it is over it. The claim ships Royal Mail on a GB tracking
    number and its evidence photograph reads in pounds (FR-1.20).
    """
    policy = a_policy()
    cap = policy.reimbursement_cap_usd

    as_dollars = convert_to_usd(Decimal("90.00"), "USD", policy)
    as_pounds = convert_to_usd(Decimal("90.00"), "GBP", policy)

    assert Decimal(str(as_dollars.usd_amount)) <= cap
    assert Decimal(str(as_pounds.usd_amount)) > cap


def test_a_currency_with_no_rate_is_not_quietly_treated_as_dollars() -> None:
    """NFR-4: an amount nobody can compare with the cap goes to a person, not through it."""
    result = convert_to_usd(Decimal("40.00"), "JPY", a_policy())

    assert result.converted is False
    assert result.usd_amount is None
    assert "needs a person" in result.summary


def test_a_missing_currency_is_not_quietly_treated_as_dollars() -> None:
    """The ordinary case: ShipBob's records never say, so the caller often cannot either."""
    result = convert_to_usd(Decimal("52.00"), None, a_policy())

    assert result.converted is False
    assert result.usd_amount is None


def test_policy_can_allow_an_unknown_currency_to_be_read_as_dollars() -> None:
    """FR-0.7: guessing is a policy decision, and the result says when it was used."""
    policy = a_policy(assume_usd_when_currency_unknown=True)

    result = convert_to_usd(Decimal("52.00"), None, policy)

    assert result.converted is True
    assert result.usd_amount == "52.00"
    assert result.assumed_usd is True


def test_converted_figures_round_half_a_cent_upward() -> None:
    """Stated rounding, so two identical claims never settle a cent apart."""
    policy = a_policy(usd_conversion_rates={"GBP": Decimal("1.005")})

    result = convert_to_usd(Decimal("10.00"), "GBP", policy)

    assert result.usd_amount == "10.05"


def test_every_figure_leaves_as_text() -> None:
    """NFR-3: money never passes through a floating point number in this system."""
    result = convert_to_usd(Decimal("55.95"), "GBP", a_policy())

    assert isinstance(result.usd_amount, str)
    assert isinstance(result.original_amount, str)
    assert isinstance(result.rate_used, str)


def test_a_currency_code_is_read_however_it_was_written() -> None:
    """An operator setting the table from the environment cannot break it with case."""
    assert normalise_currency(" gbp ") == "GBP"
    assert normalise_currency("   ") is None
    assert normalise_currency(None) is None


# --- Working out which currency a claim is in -------------------------------


def test_case_1001_is_pounds_because_three_clues_agree() -> None:
    """The real CASE-1001: Royal Mail, a GB tracking number, and a photographed £."""
    finding = currency_for_claim(
        tracking_number="XQ607930599GB",
        carrier="Royal Mail Tracked 48",
        symbols_seen=["£"],
    )

    assert finding.currency == "GBP"
    assert finding.is_ambiguous is False
    assert finding.confidence == 0.9
    assert len(finding.signals) == 3
    assert finding.signals[0].source is SignalSource.SYMBOL_ON_EVIDENCE


def test_a_dollar_sign_alone_does_not_say_which_dollar() -> None:
    """Canada and Australia write their money with a $ too, so it names three currencies."""
    finding = currency_for_claim(symbols_seen=["$"])

    assert finding.currency is None
    assert finding.is_ambiguous is True
    assert "CAD" in finding.reason


def test_a_gb_parcel_showing_a_dollar_sign_settles_nothing() -> None:
    """FR-1.13: two clues that contradict each other produce no answer, not a winner.

    A dollar sign cannot say which dollar it is, but it can say the money is not pounds.
    Picking the pound anyway is how a claim gets capped against the wrong number.
    """
    finding = currency_for_claim(tracking_number="XQ607930599GB", symbols_seen=["$"])

    assert finding.currency is None
    assert finding.is_ambiguous is True
    assert "contradict" in finding.reason


def test_a_tracking_number_alone_is_a_weaker_answer_than_three_clues() -> None:
    """One clue is a hint; confidence rises only as independent clues agree."""
    finding = currency_for_claim(tracking_number="XQ607930599GB")

    assert finding.currency == "GBP"
    assert finding.confidence == 0.5


def test_carriers_that_work_in_more_than_one_country_say_nothing() -> None:
    """The real carriers on CASE-1002 to CASE-1005, none of which names a country."""
    for carrier in ("CirroECommerce", "UniUni", "Other", "USPS Priority"):
        finding = currency_for_claim(carrier=carrier)
        assert finding.currency in (None, "USD"), carrier

    assert currency_for_claim(carrier="UniUni").currency is None


def test_a_claim_with_no_clues_at_all_is_answered_rather_than_guessed() -> None:
    """The ordinary case, and it must read as "we do not know", not as dollars."""
    finding = currency_for_claim()

    assert finding == CurrencyFinding(
        reason=(
            "Nothing on this claim says what currency its figures are in — no symbol on "
            "the evidence, no country in the tracking number, and a carrier that works in "
            "more than one country."
        )
    )


def test_the_same_symbol_seen_four_times_is_one_clue() -> None:
    """NFR-1: a merchant who attached more screenshots must not look more convincing."""
    finding = currency_for_claim(symbols_seen=["£", "£", "£", "£"])

    assert len(finding.signals) == 1
    assert finding.confidence == 0.5


def test_a_word_ending_in_two_letters_is_not_read_as_a_country() -> None:
    """A tracking number has to look like one before its last two letters mean anything."""
    assert currency_for_claim(tracking_number="PENDING").currency is None
    assert currency_for_claim(tracking_number="US").currency is None


def test_a_plain_domestic_tracking_number_carries_no_country() -> None:
    """The real CASE-1003 USPS number, which has no country suffix at all."""
    finding = currency_for_claim(tracking_number="9234690244541403638849", carrier="USPS")

    assert finding.currency == "USD"
    assert [signal.source for signal in finding.signals] == [SignalSource.CARRIER_NAME]
