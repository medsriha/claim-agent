"""Reading what a merchant's own words ask for, by keyword rather than by a model.

Both real quotes this module was built for get their own test: CASE-1004's request for a
part, not the whole item, and CASE-1002's either/or between a refund and the package sent
again. The rest cover the honest default — `unclear` — and the practical limits the module
docstring already admits to: only the first occurrence of "replace" is read, and only a
bounded amount of text is scanned at all.
"""

from __future__ import annotations

from claim_agent.domain.remedy import RemedyKind, classify_remedy

# ---------------------------------------------------------------------------
# The two real cases this module exists for
# ---------------------------------------------------------------------------


def test_case_1004_a_lid_replacement_is_read_as_a_part_not_the_whole_item() -> None:
    """CASE-1004's merchant: "How can I get a lid replacement for my roller? It broke
    pretty quickly after receiving - thought I'd ask!" A claim filed as "Damaged in
    Transit" is asking for one broken part, not a reimbursement for the roller.
    """
    reading = classify_remedy(
        "How can I get a lid replacement for my roller? It broke pretty quickly after "
        "receiving - thought I'd ask!"
    )

    assert reading.kinds == (RemedyKind.REPLACEMENT_PART,)
    assert "lid" in reading.requested[0].matched_phrase.lower()
    assert "replacement" in reading.requested[0].matched_phrase.lower()
    assert reading.is_unclear is False


def test_case_1002_either_or_wording_reports_both_remedies_offered() -> None:
    """CASE-1002's merchant: "please either refund me in its entirety or send me my
    package in its entirety it's your choice" — two remedies, explicitly either/or, and
    both belong in the reading rather than one being picked for the merchant.
    """
    reading = classify_remedy(
        "please either refund me in its entirety or send me my package in its entirety "
        "it's your choice"
    )

    assert reading.kinds == (RemedyKind.REFUND, RemedyKind.RESHIP)
    phrases = [match.matched_phrase.lower() for match in reading.requested]
    assert "refund" in phrases[0]
    assert "package" in phrases[1]


# ---------------------------------------------------------------------------
# Unclear is the default, and a correct answer (never guess from silence)
# ---------------------------------------------------------------------------


def test_text_asking_for_nothing_recognisable_is_unclear() -> None:
    """A message that never says what it wants is `unclear`, not a guess at one."""
    reading = classify_remedy("Thanks so much for shipping this out quickly!")

    assert reading.requested == ()
    assert reading.is_unclear is True
    assert reading.kinds == ()


def test_empty_text_is_unclear() -> None:
    """No text at all is the same honest answer as text that says nothing useful."""
    reading = classify_remedy("")

    assert reading.is_unclear is True
    assert reading.truncated is False


def test_unclear_still_carries_a_plain_reason() -> None:
    """A rep reading `unclear` should not have to infer why from an empty list."""
    reading = classify_remedy("It arrived a bit late.")

    assert "unclear" in reading.reason.lower() or "not" in reading.reason.lower()
    assert reading.reason != ""


# ---------------------------------------------------------------------------
# Replacement: whole item versus a single part
# ---------------------------------------------------------------------------


def test_a_bare_replacement_request_with_no_part_word_nearby_is_the_whole_item() -> None:
    """No part noun near "replacement" means the whole product, not a component of it."""
    reading = classify_remedy("I would like a full replacement of the product, please.")

    assert reading.kinds == (RemedyKind.REPLACEMENT,)


def test_a_part_word_far_from_replacement_does_not_narrow_it_to_a_part() -> None:
    """The part word has to be genuinely nearby — a `strap` mentioned in an earlier,
    unrelated sentence should not turn a later, separate replacement request into one for
    that part.
    """
    reading = classify_remedy(
        "The strap on the bag looked fine to me. "
        "Regardless, I would still like a replacement of the product sent over."
    )

    assert reading.kinds == (RemedyKind.REPLACEMENT,)


def test_only_the_first_replacement_mentioned_is_read() -> None:
    """Documented as a real limit: a message about two different replacements needs a
    person regardless of what this reports.
    """
    reading = classify_remedy(
        "Could I get a replacement cap for the bottle, and separately a replacement lid "
        "for the jar?"
    )

    assert reading.kinds == (RemedyKind.REPLACEMENT_PART,)
    assert "cap" in reading.requested[0].matched_phrase.lower()


# ---------------------------------------------------------------------------
# Refund and reship phrasing
# ---------------------------------------------------------------------------


def test_money_back_is_read_as_a_refund_request() -> None:
    """A synonym for "refund" is still a refund, since the phrase itself is listed."""
    reading = classify_remedy("I'd like my money back for this order.")

    assert reading.kinds == (RemedyKind.REFUND,)
    assert reading.requested[0].matched_phrase.lower() == "money back"


def test_resend_the_order_is_read_as_reship() -> None:
    """ "resend" is a plainer word for the same request as "reship"."""
    reading = classify_remedy("Could you resend the order to me?")

    assert reading.kinds == (RemedyKind.RESHIP,)


def test_matching_is_case_insensitive() -> None:
    """A merchant writing in capitals is not asking for anything different."""
    reading = classify_remedy("PLEASE REFUND ME IMMEDIATELY")

    assert reading.kinds == (RemedyKind.REFUND,)
    assert reading.requested[0].matched_phrase == "REFUND"


# ---------------------------------------------------------------------------
# The text cap on untrusted merchant prose
# ---------------------------------------------------------------------------


def test_text_past_the_scan_limit_is_never_read() -> None:
    """A trigger word placed after the cap is invisible to this, and the result says the
    text was cut short rather than pretending to have read all of it.
    """
    padding = "This parcel arrived a little late but otherwise fine. " * 100
    text = padding + " I would like a refund please."

    reading = classify_remedy(text)

    assert reading.truncated is True
    assert reading.is_unclear is True


def test_text_within_the_scan_limit_is_read_in_full() -> None:
    """Nothing in the sample data is anywhere near the cap, so ordinary messages are
    never truncated.
    """
    reading = classify_remedy("Please refund me for this order.")

    assert reading.truncated is False
    assert reading.kinds == (RemedyKind.REFUND,)
