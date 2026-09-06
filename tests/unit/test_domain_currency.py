from __future__ import annotations

from decimal import Decimal
from typing import Any

from claim_agent.domain.currency import (
    CurrencyFinding,
    SignalSource,
    convert_to_usd,
    currency_for_claim,
    normalise_currency,
)
from claim_agent.policy import Policy


def a_policy(**overrides: Any) -> Policy:
    return Policy(**overrides)


def test_pounds_become_dollars_at_the_recorded_rate() -> None:
    result = convert_to_usd(Decimal("55.95"), "GBP", a_policy())

    assert result.converted is True
    assert result.usd_amount == "71.06"
    assert result.rate_used == "1.27"
    assert result.rates_as_of == "2026-09-04"
    assert result.assumed_usd is False


def test_dollars_pass_through_without_consulting_the_rate_table() -> None:
    policy = a_policy(usd_conversion_rates={"USD": Decimal("999.00")})

    result = convert_to_usd(Decimal("90.00"), "usd", policy)

    assert result.usd_amount == "90.00"
    assert result.rate_used == "1.00"


def test_case_1001_is_inside_the_cap_as_dollars_and_outside_it_as_pounds() -> None:
    policy = a_policy()
    cap = policy.reimbursement_cap_usd

    as_dollars = convert_to_usd(Decimal("90.00"), "USD", policy)
    as_pounds = convert_to_usd(Decimal("90.00"), "GBP", policy)

    assert Decimal(str(as_dollars.usd_amount)) <= cap
    assert Decimal(str(as_pounds.usd_amount)) > cap


def test_a_currency_with_no_rate_is_not_quietly_treated_as_dollars() -> None:
    result = convert_to_usd(Decimal("40.00"), "JPY", a_policy())

    assert result.converted is False
    assert result.usd_amount is None
    assert "needs a person" in result.summary


def test_a_missing_currency_is_not_quietly_treated_as_dollars() -> None:
    result = convert_to_usd(Decimal("52.00"), None, a_policy())

    assert result.converted is False
    assert result.usd_amount is None


def test_policy_can_allow_an_unknown_currency_to_be_read_as_dollars() -> None:
    policy = a_policy(assume_usd_when_currency_unknown=True)

    result = convert_to_usd(Decimal("52.00"), None, policy)

    assert result.converted is True
    assert result.usd_amount == "52.00"
    assert result.assumed_usd is True


def test_converted_figures_round_half_a_cent_upward() -> None:
    policy = a_policy(usd_conversion_rates={"GBP": Decimal("1.005")})

    result = convert_to_usd(Decimal("10.00"), "GBP", policy)

    assert result.usd_amount == "10.05"


def test_every_figure_leaves_as_text() -> None:
    result = convert_to_usd(Decimal("55.95"), "GBP", a_policy())

    assert isinstance(result.usd_amount, str)
    assert isinstance(result.original_amount, str)
    assert isinstance(result.rate_used, str)


def test_a_currency_code_is_read_however_it_was_written() -> None:
    assert normalise_currency(" gbp ") == "GBP"
    assert normalise_currency("   ") is None
    assert normalise_currency(None) is None


def test_case_1001_is_pounds_because_three_clues_agree() -> None:
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
    finding = currency_for_claim(symbols_seen=["$"])

    assert finding.currency is None
    assert finding.is_ambiguous is True
    assert "CAD" in finding.reason


def test_a_gb_parcel_showing_a_dollar_sign_settles_nothing() -> None:
    finding = currency_for_claim(tracking_number="XQ607930599GB", symbols_seen=["$"])

    assert finding.currency is None
    assert finding.is_ambiguous is True
    assert "contradict" in finding.reason


def test_a_tracking_number_alone_is_a_weaker_answer_than_three_clues() -> None:
    finding = currency_for_claim(tracking_number="XQ607930599GB")

    assert finding.currency == "GBP"
    assert finding.confidence == 0.5


def test_carriers_that_work_in_more_than_one_country_say_nothing() -> None:
    for carrier in ("CirroECommerce", "UniUni", "Other", "USPS Priority"):
        finding = currency_for_claim(carrier=carrier)
        assert finding.currency in (None, "USD"), carrier

    assert currency_for_claim(carrier="UniUni").currency is None


def test_a_claim_with_no_clues_at_all_is_answered_rather_than_guessed() -> None:
    finding = currency_for_claim()

    assert finding == CurrencyFinding(
        reason=(
            "Nothing on this claim says what currency its figures are in — no symbol on "
            "the evidence, no country in the tracking number, and a carrier that works in "
            "more than one country."
        )
    )


def test_the_same_symbol_seen_four_times_is_one_clue() -> None:
    finding = currency_for_claim(symbols_seen=["£", "£", "£", "£"])

    assert len(finding.signals) == 1
    assert finding.confidence == 0.5


def test_a_word_ending_in_two_letters_is_not_read_as_a_country() -> None:
    assert currency_for_claim(tracking_number="PENDING").currency is None
    assert currency_for_claim(tracking_number="US").currency is None


def test_a_plain_domestic_tracking_number_carries_no_country() -> None:
    finding = currency_for_claim(tracking_number="9234690244541403638849", carrier="USPS")

    assert finding.currency == "USD"
    assert [signal.source for signal in finding.signals] == [SignalSource.CARRIER_NAME]
