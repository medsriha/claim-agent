from __future__ import annotations

from decimal import Decimal

from claim_agent.domain.claim_line import ClaimedProduct
from claim_agent.domain.item_matching import ItemMatch, MatchReason, match_items
from claim_agent.domain.models import OrderLineItem
from claim_agent.policy import Policy


def claimed(name: str, sku: str | None = None, quantity: int = 1) -> ClaimedProduct:
    return ClaimedProduct(name=name, quantity=quantity, sku=sku)


def order_line(name: str, sku: str | None, unit_price: str, quantity: int = 1) -> OrderLineItem:
    return OrderLineItem(name=name, sku=sku, quantity=quantity, unit_price=Decimal(unit_price))


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
    return match_items(product, lines, policy if policy is not None else Policy())


def test_an_exact_product_code_match_scores_highest() -> None:
    result = matched(claimed("Wrecked Pre-Workout", sku="0041"), CASE_1003_LINES)

    assert len(result) == 1
    assert result[0].order_line == WRECKED_PRE_WORKOUT
    assert result[0].reason is MatchReason.EXACT_SKU
    assert result[0].score == 1.0
    assert result[0].is_ambiguous is False


def test_an_exact_name_match_is_found_even_with_no_product_code() -> None:
    result = matched(claimed("Unflavored Liquid Glycerol"), CASE_1003_LINES)

    assert len(result) == 1
    assert result[0].order_line == LIQUID_GLYCEROL
    assert result[0].reason is MatchReason.EXACT_NAME
    assert result[0].score == 0.85


def test_capitals_and_extra_spacing_in_a_name_are_typing_not_meaning() -> None:
    result = matched(claimed("  unflavored   LIQUID glycerol "), CASE_1003_LINES)

    assert [candidate.order_line for candidate in result] == [LIQUID_GLYCEROL]
    assert result[0].reason is MatchReason.EXACT_NAME


def test_a_receipt_sku_with_an_extra_suffix_still_matches_the_shorter_order_code() -> None:
    result = matched(claimed("CleanBoss Wipes", sku="A00299-LV-8-N"), CASE_1002_LINES)

    assert len(result) == 1
    assert result[0].order_line == CLEANBOSS_WIPES
    assert result[0].reason is MatchReason.SKU_PREFIX
    assert result[0].score == 0.9


def test_two_codes_that_merely_start_the_same_by_coincidence_do_not_match() -> None:
    result = matched(claimed("Something Else", sku="A0"), CASE_1002_LINES)

    assert result == ()


def test_two_different_codes_that_do_not_share_a_prefix_fall_through_to_the_name() -> None:
    result = matched(
        claimed("CleanBoss Multi Surface Cleaner 24oz", sku="A00384-KIT"), CASE_1002_LINES
    )

    assert result[0].order_line == CLEANBOSS_MULTI_SURFACE
    assert result[0].reason is MatchReason.EXACT_NAME
    assert result[0].is_ambiguous is False
    assert all(candidate.score <= result[0].score for candidate in result)


def test_shared_words_find_a_product_the_customer_named_completely_differently() -> None:
    result = matched(claimed("liquid carnitine 3000"), CASE_1003_LINES)

    assert len(result) == 1
    assert result[0].order_line == BLUE_RAZZ_CARNITINE
    assert result[0].reason is MatchReason.WORD_OVERLAP
    assert '"liquid"' in result[0].explanation
    assert '"carnitine"' in result[0].explanation


def test_shared_words_survive_a_pipe_separated_category_tag() -> None:
    result = matched(claimed("huge whey | protein powder"), CASE_1003_LINES)

    assert len(result) == 1
    assert result[0].order_line == HUGE_WHEY
    assert result[0].reason is MatchReason.WORD_OVERLAP


def test_three_shared_words_score_higher_than_two_but_never_reach_an_exact_match() -> None:
    result = matched(claimed("wrecked pre workout | strongest pre-workout"), CASE_1003_LINES)

    assert len(result) == 1
    assert result[0].order_line == WRECKED_PRE_WORKOUT
    assert result[0].score == 0.8
    assert result[0].score < 0.85


def test_a_single_shared_word_scores_lower_than_two() -> None:
    lenient = Policy(min_item_match_confidence=0.0)
    two_words = matched(claimed("liquid carnitine 3000"), CASE_1003_LINES, policy=lenient)[0]
    one_word = matched(claimed("carnitine only"), CASE_1003_LINES, policy=lenient)[0]

    assert two_words.score > one_word.score


def test_a_looser_threshold_is_read_from_policy_not_hardcoded() -> None:
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


def test_two_lines_sharing_a_brand_name_equally_are_flagged_ambiguous_not_narrowed() -> None:
    result = matched(claimed("CleanBoss Cleaner"), CASE_1002_LINES)

    top_two = [candidate for candidate in result if candidate.score == result[0].score]
    assert len(top_two) == 2
    assert {candidate.order_line for candidate in top_two} == {
        CLEANBOSS_DISINFECTANT,
        CLEANBOSS_MULTI_SURFACE,
    }
    assert all(candidate.is_ambiguous for candidate in top_two)


def test_a_weaker_candidate_alongside_a_tie_is_not_itself_marked_ambiguous() -> None:
    result = matched(
        claimed("CleanBoss Cleaner"), CASE_1002_LINES, policy=Policy(min_item_match_confidence=0.3)
    )

    weakest = min(result, key=lambda candidate: candidate.score)
    assert weakest.order_line == CLEANBOSS_WIPES
    assert weakest.is_ambiguous is False
    assert weakest.score < result[0].score


def test_an_exact_code_match_is_never_ambiguous_even_when_names_also_overlap() -> None:
    result = matched(claimed("CleanBoss Cleaner", sku="A00300"), CASE_1002_LINES)

    best = result[0]
    assert best.order_line == CLEANBOSS_MULTI_SURFACE
    assert best.reason is MatchReason.EXACT_SKU
    assert best.is_ambiguous is False


def test_results_are_ordered_by_score_then_by_the_order_the_lines_were_given_in() -> None:
    reordered_lines = (CLEANBOSS_MULTI_SURFACE, CLEANBOSS_DISINFECTANT, CLEANBOSS_WIPES)

    result = matched(claimed("CleanBoss Cleaner"), reordered_lines)

    assert [candidate.score for candidate in result] == sorted(
        (candidate.score for candidate in result), reverse=True
    )
    tied = [candidate.order_line for candidate in result if candidate.is_ambiguous]
    assert tied == [CLEANBOSS_MULTI_SURFACE, CLEANBOSS_DISINFECTANT]


def test_matching_the_same_product_twice_produces_the_same_result() -> None:
    first = matched(claimed("liquid carnitine 3000"), CASE_1003_LINES)
    second = matched(claimed("liquid carnitine 3000"), CASE_1003_LINES)

    assert first == second


def test_no_order_lines_produces_no_candidates() -> None:
    assert matched(claimed("Anything"), ()) == ()


def test_a_product_sharing_nothing_with_the_order_produces_no_candidates() -> None:
    result = matched(claimed("Beef Trachea Chews"), CASE_1003_LINES)

    assert result == ()
