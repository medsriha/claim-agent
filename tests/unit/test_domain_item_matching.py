"""Whether a claimed product could be one of the products on an order, and how sure to be.

Every test uses either a real sample case's own product names and codes, or the same
constructed-two-lines pattern `test_domain_reimbursement.py` uses for CASE-1002's
ambiguity — two order lines that are genuinely indistinguishable from the merchant's own
words, which is exactly the case FR-1.13 says a person has to resolve.
"""

from __future__ import annotations

from decimal import Decimal

from claim_agent.domain.claim_line import ClaimedProduct
from claim_agent.domain.item_matching import ItemMatch, MatchReason, match_items
from claim_agent.domain.models import OrderLineItem
from claim_agent.policy import Policy


def claimed(name: str, sku: str | None = None, quantity: int = 1) -> ClaimedProduct:
    """One product a merchant's evidence says was damaged, in whatever words were read."""
    return ClaimedProduct(name=name, quantity=quantity, sku=sku)


def order_line(name: str, sku: str | None, unit_price: str, quantity: int = 1) -> OrderLineItem:
    """One line on an order, with its price written as text so it stays exact."""
    return OrderLineItem(name=name, sku=sku, quantity=quantity, unit_price=Decimal(unit_price))


# CASE-1003's own six order lines, exactly as ShipBob supplies them (tests/fixtures/shipbob.py).
WRECKED_PRE_WORKOUT = order_line("Bomb Popsicle Wrecked Pre-Workout", "0041", "49.99")
BLUE_RAZZ_CARNITINE = order_line("Blue Razz Liquid Carnitine", "0199", "34.99")
HUGE_SHAKER = order_line("Red/Black HUGE Shaker", "0157", "12.99")
HUGE_WHEY = order_line("2.5LBS White Chocolate Raspberry Huge Whey", "0159", "59.99")
CORE_SAMPLE = order_line("Green Apple Wrecked Core Sample", "0180", "9.99")
LIQUID_GLYCEROL = order_line("Unflavored Liquid Glycerol", "0179", "27.99")
CASE_1003_LINES = (
    WRECKED_PRE_WORKOUT,
    BLUE_RAZZ_CARNITINE,
    HUGE_SHAKER,
    HUGE_WHEY,
    CORE_SAMPLE,
    LIQUID_GLYCEROL,
)

# CASE-1002's own three order lines.
CLEANBOSS_DISINFECTANT = order_line(
    "CleanBoss Botanical Disinfectant & Cleaner 24oz 2 Pack", "A00360", "24.99"
)
CLEANBOSS_MULTI_SURFACE = order_line(
    "CleanBoss Multi Surface Cleaner 24oz", "A00300", "12.99", quantity=2
)
CLEANBOSS_WIPES = order_line("CleanBoss Foaming Cleaning Wipes 70 pack", "A00299", "14.99")
CASE_1002_LINES = (CLEANBOSS_DISINFECTANT, CLEANBOSS_MULTI_SURFACE, CLEANBOSS_WIPES)


def matched(
    product: ClaimedProduct,
    lines: tuple[OrderLineItem, ...],
    policy: Policy | None = None,
) -> tuple[ItemMatch, ...]:
    """Match one claimed product against a set of order lines under the given policy."""
    return match_items(product, lines, policy if policy is not None else Policy())


# ---------------------------------------------------------------------------
# Exact matches (FR-1a.2)
# ---------------------------------------------------------------------------


def test_an_exact_product_code_match_scores_highest() -> None:
    """CASE-1003: a claimed code that matches an order line's code exactly is certain."""
    result = matched(claimed("Wrecked Pre-Workout", sku="0041"), CASE_1003_LINES)

    assert len(result) == 1
    assert result[0].order_line == WRECKED_PRE_WORKOUT
    assert result[0].reason is MatchReason.EXACT_SKU
    assert result[0].score == 1.0
    assert result[0].is_ambiguous is False


def test_an_exact_name_match_is_found_even_with_no_product_code() -> None:
    """CASE-1003: a photograph of a broken bottle rarely shows a product code."""
    result = matched(claimed("Unflavored Liquid Glycerol"), CASE_1003_LINES)

    assert len(result) == 1
    assert result[0].order_line == LIQUID_GLYCEROL
    assert result[0].reason is MatchReason.EXACT_NAME
    assert result[0].score == 0.85


def test_capitals_and_extra_spacing_in_a_name_are_typing_not_meaning() -> None:
    """A name is still an exact match once case and spacing are ignored."""
    result = matched(claimed("  unflavored   LIQUID glycerol "), CASE_1003_LINES)

    assert [candidate.order_line for candidate in result] == [LIQUID_GLYCEROL]
    assert result[0].reason is MatchReason.EXACT_NAME


# ---------------------------------------------------------------------------
# A product code that grew a suffix (SKU prefix)
# ---------------------------------------------------------------------------


def test_a_receipt_sku_with_an_extra_suffix_still_matches_the_shorter_order_code() -> None:
    """CASE-1002: ShipBob's `A00299` shows up on a receipt as `A00299-LV-8-N`."""
    result = matched(claimed("CleanBoss Wipes", sku="A00299-LV-8-N"), CASE_1002_LINES)

    assert len(result) == 1
    assert result[0].order_line == CLEANBOSS_WIPES
    assert result[0].reason is MatchReason.SKU_PREFIX
    assert result[0].score == 0.9


def test_two_codes_that_merely_start_the_same_by_coincidence_do_not_match() -> None:
    """A short, accidental prefix must not read as the same product code."""
    result = matched(claimed("Something Else", sku="A0"), CASE_1002_LINES)

    assert result == ()


def test_two_different_codes_that_do_not_share_a_prefix_fall_through_to_the_name() -> None:
    """CASE-1002: `A00300` on the order and `A00384-KIT` on a receipt share no prefix at
    all — real SKU drift that a code-only rule could never bridge. The name still ties it
    to the right line as the clear best match, even though a weaker word-overlap match to
    a different CleanBoss product (same brand, same "Cleaner") also clears the bar.
    """
    result = matched(
        claimed("CleanBoss Multi Surface Cleaner 24oz", sku="A00384-KIT"), CASE_1002_LINES
    )

    assert result[0].order_line == CLEANBOSS_MULTI_SURFACE
    assert result[0].reason is MatchReason.EXACT_NAME
    assert result[0].is_ambiguous is False
    assert all(candidate.score <= result[0].score for candidate in result)


# ---------------------------------------------------------------------------
# Overlapping significant words (the real brittleness in the sample data)
# ---------------------------------------------------------------------------


def test_shared_words_find_a_product_the_customer_named_completely_differently() -> None:
    """CASE-1003: ShipBob's `Blue Razz Liquid Carnitine`, the customer's `liquid carnitine
    3000`. `3000` is packaging noise — a strength label, not a product name — and drops
    out, leaving "liquid" and "carnitine" as the two words that actually carry the match.
    """
    result = matched(claimed("liquid carnitine 3000"), CASE_1003_LINES)

    assert len(result) == 1
    assert result[0].order_line == BLUE_RAZZ_CARNITINE
    assert result[0].reason is MatchReason.WORD_OVERLAP
    assert '"liquid"' in result[0].explanation
    assert '"carnitine"' in result[0].explanation


def test_shared_words_survive_a_pipe_separated_category_tag() -> None:
    """CASE-1003: ShipBob's `2.5LBS White Chocolate Raspberry Huge Whey`, the customer's
    `huge whey | protein powder`. The weight prefix and the pipe are both just punctuation
    to strip; "huge" and "whey" are what is left once packaging noise is gone.
    """
    result = matched(claimed("huge whey | protein powder"), CASE_1003_LINES)

    assert len(result) == 1
    assert result[0].order_line == HUGE_WHEY
    assert result[0].reason is MatchReason.WORD_OVERLAP


def test_three_shared_words_score_higher_than_two_but_never_reach_an_exact_match() -> None:
    """CASE-1003: `Bomb Popsicle Wrecked Pre-Workout` against `wrecked pre workout |
    strongest pre-workout` shares three words, not two, and should score for it — but
    still below the 0.85 an exact name gets, because it still is not one.
    """
    result = matched(claimed("wrecked pre workout | strongest pre-workout"), CASE_1003_LINES)

    assert len(result) == 1
    assert result[0].order_line == WRECKED_PRE_WORKOUT
    assert result[0].score == 0.8
    assert result[0].score < 0.85


def test_a_single_shared_word_scores_lower_than_two() -> None:
    """One shared word is weaker evidence than two, and the score says so.

    A single shared word falls below the default confidence bar on its own (see
    `test_a_looser_threshold_is_read_from_policy_not_hardcoded` for why), so both sides of
    this comparison use a policy loose enough to surface it.
    """
    lenient = Policy(min_item_match_confidence=0.0)
    two_words = matched(claimed("liquid carnitine 3000"), CASE_1003_LINES, policy=lenient)[0]
    one_word = matched(claimed("carnitine only"), CASE_1003_LINES, policy=lenient)[0]

    assert two_words.score > one_word.score


def test_a_looser_threshold_is_read_from_policy_not_hardcoded() -> None:
    """FR-0.7, NFR-7: how much word overlap counts as "enough" is a policy value."""
    strict = matched(
        claimed("liquid glycerol unflavored"),
        CASE_1003_LINES,
        policy=Policy(min_item_match_confidence=0.95),
    )
    lenient = matched(
        claimed("liquid glycerol unflavored"),
        CASE_1003_LINES,
        policy=Policy(min_item_match_confidence=0.5),
    )

    assert strict == ()
    assert lenient != ()


# ---------------------------------------------------------------------------
# Ambiguity is reported, never resolved (FR-1.13)
# ---------------------------------------------------------------------------


def test_two_lines_sharing_a_brand_name_equally_are_flagged_ambiguous_not_narrowed() -> None:
    """CASE-1002: "CleanBoss Cleaner" shares two words with two different CleanBoss
    products — the disinfectant and the multi-surface cleaner — and neither is a better
    guess than the other from these words alone. Both must be reported, tied, and neither
    picked.
    """
    result = matched(claimed("CleanBoss Cleaner"), CASE_1002_LINES)

    top_two = [candidate for candidate in result if candidate.score == result[0].score]
    assert len(top_two) == 2
    assert {candidate.order_line for candidate in top_two} == {
        CLEANBOSS_DISINFECTANT,
        CLEANBOSS_MULTI_SURFACE,
    }
    assert all(candidate.is_ambiguous for candidate in top_two)


def test_a_weaker_candidate_alongside_a_tie_is_not_itself_marked_ambiguous() -> None:
    """Only the tied top score is ambiguous; a clearly weaker third candidate is not lost,
    but it is also not confused with the two the rule genuinely cannot separate.

    Sharing only the brand name ("CleanBoss") with the wipes is below the default
    confidence bar on its own, so a looser policy is used here to bring it into view
    alongside the genuine tie.
    """
    result = matched(
        claimed("CleanBoss Cleaner"), CASE_1002_LINES, policy=Policy(min_item_match_confidence=0.3)
    )

    weakest = min(result, key=lambda candidate: candidate.score)
    assert weakest.order_line == CLEANBOSS_WIPES
    assert weakest.is_ambiguous is False
    assert weakest.score < result[0].score


def test_an_exact_code_match_is_never_ambiguous_even_when_names_also_overlap() -> None:
    """A code match settles the question outright; overlapping names elsewhere on the
    order do not get to reopen it.
    """
    result = matched(claimed("CleanBoss Cleaner", sku="A00300"), CASE_1002_LINES)

    best = result[0]
    assert best.order_line == CLEANBOSS_MULTI_SURFACE
    assert best.reason is MatchReason.EXACT_SKU
    assert best.is_ambiguous is False


# ---------------------------------------------------------------------------
# Ordering and determinism (NFR-1)
# ---------------------------------------------------------------------------


def test_results_are_ordered_by_score_then_by_the_order_the_lines_were_given_in() -> None:
    """Highest score first; a tie keeps the input order rather than being resorted."""
    reordered_lines = (CLEANBOSS_MULTI_SURFACE, CLEANBOSS_DISINFECTANT, CLEANBOSS_WIPES)

    result = matched(claimed("CleanBoss Cleaner"), reordered_lines)

    assert [candidate.score for candidate in result] == sorted(
        (candidate.score for candidate in result), reverse=True
    )
    tied = [candidate.order_line for candidate in result if candidate.is_ambiguous]
    assert tied == [CLEANBOSS_MULTI_SURFACE, CLEANBOSS_DISINFECTANT]


def test_matching_the_same_product_twice_produces_the_same_result() -> None:
    """NFR-1: the same claimed product against the same order lines never changes answer."""
    first = matched(claimed("liquid carnitine 3000"), CASE_1003_LINES)
    second = matched(claimed("liquid carnitine 3000"), CASE_1003_LINES)

    assert first == second


# ---------------------------------------------------------------------------
# Nothing to match against (empty inputs)
# ---------------------------------------------------------------------------


def test_no_order_lines_produces_no_candidates() -> None:
    """An order that could not be read at all yields nothing to match against — a real
    answer, not a failure."""
    assert matched(claimed("Anything"), ()) == ()


def test_a_product_sharing_nothing_with_the_order_produces_no_candidates() -> None:
    """CASE-1003: something entirely unrelated to any of the six order lines matches none
    of them, and that absence is itself the finding.
    """
    result = matched(claimed("Beef Trachea Chews"), CASE_1003_LINES)

    assert result == ()
