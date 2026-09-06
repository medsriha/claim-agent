from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from decimal import Decimal

import httpx
import respx
from langchain_core.exceptions import ModelConnectionError
from langchain_core.messages import AIMessage
from tests.fakes.model import ScriptedModel, scripted
from tests.fixtures.attachments import ATTACHMENTS_1001, INVOICE_342578703
from tests.fixtures.shipbob import CASE_1001, ORDER_1001, SHIPMENT_1001

from claim_agent.agent.budget import BudgetLimit
from claim_agent.agent.events import EventKind, EventStream
from claim_agent.agent.images import ImageFetcher
from claim_agent.agent.investigate import ClaimFindings, investigate_claim_lines
from claim_agent.agent.ledger import StepKind
from claim_agent.agent.llm import StructuredModel
from claim_agent.agent.observations import ObservationCache
from claim_agent.agent.prompts import PROMPT_VERSION
from claim_agent.agent.schemas import (
    AssessmentJudgement,
    DamagedItem,
    EvidenceJudgement,
    InvestigationConclusion,
)
from claim_agent.agent.tools import LIST_ATTACHMENTS
from claim_agent.domain.assessment import REQUIRED_ASSESSMENTS, AssessmentName
from claim_agent.domain.claim_line import ClaimedProduct, ClaimLine, MatchOutcome, build_claim_lines
from claim_agent.domain.evidence import (
    REQUIRED_EVIDENCE,
    EvidenceFinding,
    EvidenceKind,
    EvidenceState,
    findings_by_kind,
    gaps_the_merchant_can_fill,
)
from claim_agent.domain.models import (
    Attachment,
    Case,
    Invoice,
    Order,
    OrderLineItem,
    Shipment,
)
from claim_agent.domain.outcome import OverrideReason, Recommendation
from claim_agent.domain.precedent import PrecedentRecord, PrecedentSimilarity
from claim_agent.policy import Policy
from claim_agent.preflight.models import CaseRecord, ClaimContext
from claim_agent.settings import Settings
from claim_agent.shipbob.evidence_client import EvidenceClient
from claim_agent.storage.precedent_store import PrecedentSet, RetrievedPrecedent

SHIPBOB = "http://shipbob.test"


CASE = Case.model_validate(CASE_1001)
SHIPMENT = Shipment.model_validate(SHIPMENT_1001)
ORDER = Order.model_validate(ORDER_1001)
INVOICE = Invoice.model_validate(INVOICE_342578703)

COLLAGEN = "Liposomal Tripeptide Collagen"
COLLAGEN_SKU = "COLLAGEN1"
AMPOULE = "Additional Collagen Ampoule Duo"


def images_on_the_claim() -> tuple[Attachment, ...]:
    listed = ATTACHMENTS_1001["attachments"]
    assert isinstance(listed, list)
    return tuple(Attachment.model_validate(image) for image in listed)


IMAGES = images_on_the_claim()

RECORD = CaseRecord(case=CASE, shipment=SHIPMENT, order=ORDER)
CONTEXT = ClaimContext(
    order_value_usd=Decimal("90.00"),
    is_high_value=False,
    days_since_delivery=8,
    delivered_date=CASE.delivered_date,
)


def build_settings() -> Settings:
    return Settings(
        environment="test",
        log_level="WARNING",
        anthropic_api_key=None,
        shipbob_base_url=SHIPBOB,
        attachment_allowed_hosts=("images.test",),
        attachment_cache_dir=None,
        attachment_timeout_seconds=1.0,
    )


def claim_lines(*claimed: ClaimedProduct, order: Order = ORDER) -> tuple[ClaimLine, ...]:
    return build_claim_lines(CASE.case_id, claimed, order)


def a_claim_for_the_collagen(order: Order = ORDER) -> ClaimLine:
    line = claim_lines(ClaimedProduct(name=COLLAGEN, quantity=1, sku=COLLAGEN_SKU), order=order)[0]
    assert line.match is MatchOutcome.MATCHED
    return line


def five_other_products() -> tuple[ClaimedProduct, ...]:
    return (
        ClaimedProduct(name=AMPOULE, quantity=1, sku="AMP1"),
        ClaimedProduct(name="Beef Trachea Chews", quantity=2),
        ClaimedProduct(name="Salmon Skin Twists", quantity=1),
        ClaimedProduct(name="Duck Neck Crunchies", quantity=3),
        ClaimedProduct(name="Turkey Tendon Sticks", quantity=1),
    )


def the_collagen_beside(others: Sequence[ClaimedProduct]) -> tuple[ClaimLine, ...]:
    return claim_lines(ClaimedProduct(name=COLLAGEN, quantity=1, sku=COLLAGEN_SKU), *others)


def evidence_all_in_hand(**states: EvidenceState) -> tuple[EvidenceJudgement, ...]:
    return tuple(
        EvidenceJudgement(
            kind=kind,
            state=states.get(kind.value, EvidenceState.PRESENT),
            observed=f"What the {kind.value.replace('_', ' ')} shows.",
            attachment_id=IMAGES[0].attachment_id,
        )
        for kind in REQUIRED_EVIDENCE
    )


def all_four_answered(**passed: bool) -> tuple[AssessmentJudgement, ...]:
    return tuple(
        AssessmentJudgement(
            name=name,
            passed=passed.get(name.value, True),
            reasoning=f"Why {name.value.replace('_', ' ')} is answered that way.",
            attachment_ids=(IMAGES[0].attachment_id,),
        )
        for name in REQUIRED_ASSESSMENTS
    )


def a_conclusion(**overrides: object) -> InvestigationConclusion:
    fields: dict[str, object] = {
        "evidence": evidence_all_in_hand(),
        "assessments": all_four_answered(),
        "damaged_items": (DamagedItem(product_name=COLLAGEN, quantity=1, sku=COLLAGEN_SKU),),
        "recommended_amount_usd": "40.00",
        "amount_reasoning": "The bottle is cracked through and the contents are lost.",
        "recommendation": Recommendation.APPROVE,
        "reasoning": "The photographs show the collagen bottle crushed, and it is on the invoice.",
        "concerns": ("The photograph is taken close in, so the outer box is not visible in it.",),
        "email_subject": "About your damaged shipment",
        "email_body": "We have looked at your claim and approved the damaged collagen.",
    }
    fields.update(overrides)
    return InvestigationConclusion.model_validate(fields)


def test_fr_c_7_a_model_that_asks_for_the_high_value_label_is_read_as_approving() -> None:
    conclusion = a_conclusion(recommendation=Recommendation.APPROVE_HIGH_VALUE)

    assert conclusion.recommendation is Recommendation.APPROVE


def an_email_with_no_figure(**overrides: object) -> dict[str, object]:
    fields: dict[str, object] = {
        "email_subject": "About your damaged shipment",
        "email_body": "We have looked at your claim and will be in touch about it.",
    }
    fields.update(overrides)
    return fields


async def investigate(
    model: ScriptedModel,
    *,
    lines: Sequence[ClaimLine] | None = None,
    shared_evidence: Sequence[EvidenceFinding] = (),
    invoice: Invoice | None = INVOICE,
    order: Order = ORDER,
    policy: Policy | None = None,
    events: EventStream | None = None,
    precedent: PrecedentSet | None = None,
) -> ClaimFindings:
    settings = build_settings()
    async with (
        httpx.AsyncClient(base_url=SHIPBOB, timeout=1.0) as shipbob_http,
        httpx.AsyncClient() as images_http,
    ):
        return await investigate_claim_lines(
            lines=lines if lines is not None else (a_claim_for_the_collagen(order),),
            record=CaseRecord(case=CASE, shipment=SHIPMENT, order=order),
            context=CONTEXT,
            attachments=IMAGES,
            invoice=invoice,
            evidence=EvidenceClient(shipbob_http, max_attempts=1),
            fetcher=ImageFetcher(images_http, settings),
            chat=model,
            structured=StructuredModel(model, max_attempts=1),
            cache=ObservationCache(),
            events=events if events is not None else EventStream(),
            policy=policy if policy is not None else Policy(),
            shared_evidence=shared_evidence,
            precedent=precedent,
        )


def a_run_that_concludes(conclusion: InvestigationConclusion) -> ScriptedModel:
    return scripted("I have seen enough to answer.", conclusion)


def settled(kind: EvidenceKind, state: EvidenceState) -> EvidenceFinding:
    return EvidenceFinding(
        kind=kind,
        state=state,
        observed=f"What the claim settled about the {kind.value.replace('_', ' ')}.",
        attachment_id=IMAGES[0].attachment_id if state is not EvidenceState.MISSING else None,
        problem="It could not be read." if state is EvidenceState.UNREADABLE else None,
    )


def state_of(result: ClaimFindings, kind: EvidenceKind) -> EvidenceState:
    return findings_by_kind(result.evidence)[kind].state


async def test_a_well_evidenced_product_is_recommended_for_payment_at_the_policy_share() -> None:
    result = await investigate(a_run_that_concludes(a_conclusion()))

    assert result.outcome.recommendation is Recommendation.APPROVE
    assert result.outcome.recommended_by_agent is Recommendation.APPROVE
    assert result.outcome.was_overridden is False
    assert result.amount.proposed_usd == Decimal("40.00")
    assert result.amount.amount_usd == Decimal("40.00")
    assert result.amount.cap_applied is False
    assert result.amount.items_total_usd == Decimal("52.00")
    assert result.amount.priced_from == "INV-342578703"
    assert result.amount.cap_applied is False
    assert result.drafted_email is not None
    assert result.drafted_email.to == "sakukreja@shipbob.com"
    assert result.drafted_email.is_draft is True
    assert "$40.00" in result.drafted_email.body


async def test_a_recommendation_is_never_presented_as_settled() -> None:
    result = await investigate(a_run_that_concludes(a_conclusion()))

    assert result.drafted_email is not None
    assert result.drafted_email.is_draft is True
    assert "draft" not in result.drafted_email.body.lower()
    assert "draft" not in result.drafted_email.subject.lower()


async def test_all_four_pieces_of_evidence_and_all_four_questions_are_reported() -> None:
    result = await investigate(a_run_that_concludes(a_conclusion()))

    assert tuple(finding.kind for finding in result.evidence) == REQUIRED_EVIDENCE
    assert tuple(answer.name for answer in result.assessments) == REQUIRED_ASSESSMENTS


async def test_a_missing_piece_of_evidence_sends_the_claim_back_to_the_merchant() -> None:
    conclusion = a_conclusion(
        evidence=evidence_all_in_hand(outer_packaging_photo=EvidenceState.MISSING),
        **an_email_with_no_figure(),
    )

    result = await investigate(a_run_that_concludes(conclusion))

    assert result.outcome.recommendation is Recommendation.REQUEST_INFO
    assert result.outcome.recommended_by_agent is Recommendation.APPROVE
    assert OverrideReason.EVIDENCE_INCOMPLETE in result.outcome.overrides
    assert gaps_the_merchant_can_fill(result.evidence) == (EvidenceKind.OUTER_PACKAGING_PHOTO,)
    assert result.drafted_email is not None


async def test_a_specific_identification_detail_can_be_requested_from_the_merchant() -> None:
    detail = "a clear photograph showing the full product label and SKU"
    conclusion = a_conclusion(
        recommendation=Recommendation.REQUEST_INFO,
        requested_details=(detail,),
        **an_email_with_no_figure(),
    )

    result = await investigate(a_run_that_concludes(conclusion))

    assert result.outcome.recommendation is Recommendation.REQUEST_INFO
    assert result.drafted_email is not None
    assert detail in result.drafted_email.body


async def test_an_image_we_could_not_read_goes_to_a_person_and_not_to_the_merchant() -> None:
    conclusion = a_conclusion(**an_email_with_no_figure())

    result = await investigate(
        a_run_that_concludes(conclusion),
        shared_evidence=(settled(EvidenceKind.INVOICE, EvidenceState.UNREADABLE),),
    )

    assert result.outcome.recommendation is Recommendation.REQUEST_REP_CLARIFICATION
    assert OverrideReason.EVIDENCE_UNREADABLE in result.outcome.overrides
    assert state_of(result, EvidenceKind.INVOICE) is EvidenceState.UNREADABLE
    assert EvidenceKind.INVOICE not in gaps_the_merchant_can_fill(result.evidence)


async def test_a_question_answered_no_is_not_the_same_as_one_never_answered() -> None:
    conclusion = a_conclusion(
        assessments=all_four_answered(damage_visible=False),
        **an_email_with_no_figure(),
    )

    result = await investigate(a_run_that_concludes(conclusion))

    assert result.outcome.recommendation is Recommendation.REQUEST_REP_CLARIFICATION
    assert OverrideReason.ASSESSMENT_FAILED in result.outcome.overrides
    assert result.drafted_email is None
    answered = {answer.name: answer.passed for answer in result.assessments}
    assert answered[AssessmentName.DAMAGE_VISIBLE] is False
    assert len(result.assessments) == 4


async def test_a_question_the_run_never_answered_is_not_written_down_as_an_answer() -> None:
    conclusion = a_conclusion(
        assessments=all_four_answered()[:3],
        **an_email_with_no_figure(),
    )

    result = await investigate(a_run_that_concludes(conclusion))

    assert tuple(answer.name for answer in result.assessments) == REQUIRED_ASSESSMENTS[:3]
    assert result.outcome.recommendation is Recommendation.REQUEST_REP_CLARIFICATION
    assert OverrideReason.INVESTIGATION_INCOMPLETE in result.outcome.overrides


async def test_an_investigation_records_which_wording_and_model_produced_it() -> None:
    conclusion = a_conclusion(**an_email_with_no_figure())

    result = await investigate(a_run_that_concludes(conclusion))

    assert result.outcome.recommendation is Recommendation.APPROVE
    assert result.prompt_version == PROMPT_VERSION
    assert result.model == "scripted"


async def test_a_run_that_used_up_its_steps_asks_the_rep_with_findings_intact() -> None:
    model = scripted(
        AIMessage(
            content="",
            tool_calls=[
                {"name": LIST_ATTACHMENTS, "args": {}, "id": "call-1", "type": "tool_call"}
            ],
        )
    )

    with respx.mock(assert_all_called=False) as api:
        api.get(f"{SHIPBOB}/cases/{CASE.case_id}/attachments").respond(200, json=ATTACHMENTS_1001)
        result = await investigate(
            model,
            policy=Policy(max_agent_steps=1),
            shared_evidence=(settled(EvidenceKind.CUSTOMER_CONFIRMATION, EvidenceState.PRESENT),),
        )

    assert result.outcome.recommendation is Recommendation.REQUEST_REP_CLARIFICATION
    assert OverrideReason.BUDGET_EXHAUSTED in result.outcome.overrides
    assert result.conclusion is None
    assert result.drafted_email is None
    assert BudgetLimit.STEPS in result.budget.limits_reached
    assert [entry.name for entry in result.ledger if entry.kind is StepKind.TOOL_CALL] == [
        LIST_ATTACHMENTS
    ]
    assert state_of(result, EvidenceKind.CUSTOMER_CONFIRMATION) is EvidenceState.PRESENT
    assert result.concerns != ()


async def test_a_model_that_cannot_be_reached_produces_a_write_up_rather_than_an_error() -> None:
    result = await investigate(scripted(ModelConnectionError("the socket closed")))

    assert result.outcome.recommendation is Recommendation.REQUEST_REP_CLARIFICATION
    assert result.conclusion is None
    assert result.drafted_email is None
    assert BudgetLimit.STEPS not in result.budget.limits_reached
    assert OverrideReason.BUDGET_EXHAUSTED not in result.outcome.overrides
    assert len(result.evidence) == 4
    assert all(finding.state is EvidenceState.MISSING for finding in result.evidence)
    assert result.concerns != ()


def an_order_with_two_lines_of_one_name() -> Order:
    return Order(
        order_id="334291211",
        user_id="334430",
        line_items=(
            OrderLineItem(
                name="CleanBoss Multi Surface Cleaner 24oz",
                sku="A00300",
                quantity=1,
                unit_price=Decimal("12.99"),
            ),
            OrderLineItem(
                name="CleanBoss Multi Surface Cleaner 24oz",
                sku="A00301",
                quantity=1,
                unit_price=Decimal("24.99"),
            ),
        ),
    )


async def test_a_product_that_could_be_either_of_two_order_lines_is_never_priced() -> None:
    order = an_order_with_two_lines_of_one_name()
    line = claim_lines(
        ClaimedProduct(name="CleanBoss Multi Surface Cleaner 24oz", quantity=1), order=order
    )[0]
    assert line.match is MatchOutcome.AMBIGUOUS

    conclusion = a_conclusion(
        damaged_items=(
            DamagedItem(product_name="CleanBoss Multi Surface Cleaner 24oz", quantity=1),
        ),
        is_ambiguous=True,
        ambiguity="The photograph shows a 24oz bottle, and the order holds two of them.",
        recommendation=Recommendation.REQUEST_INFO,
        **an_email_with_no_figure(),
    )

    result = await investigate(
        a_run_that_concludes(conclusion),
        lines=(line,),
        order=order,
        invoice=Invoice(invoice_id="INV-342578703", line_items=order.line_items),
    )

    assert result.outcome.recommendation is Recommendation.REQUEST_REP_CLARIFICATION
    assert result.drafted_email is None

    assert result.amount.components == ()
    assert result.amount.components == ()
    assert any("two of them" in concern for concern in result.concerns)


async def test_an_ambiguous_product_is_judged_against_the_order_and_not_against_the_claim() -> None:
    order = an_order_with_two_lines_of_one_name()
    line = claim_lines(
        ClaimedProduct(name="CleanBoss Multi Surface Cleaner 24oz", quantity=1), order=order
    )[0]

    result = await investigate(
        a_run_that_concludes(a_conclusion(**an_email_with_no_figure())),
        lines=(line,),
        order=order,
        invoice=Invoice(invoice_id="INV-342578703", line_items=order.line_items),
    )

    assert result.outcome.recommendation is Recommendation.REQUEST_REP_CLARIFICATION
    assert OverrideReason.PRODUCT_NOT_PRICEABLE in result.outcome.overrides
    assert "more than one line on the order" in result.outcome.explanation


async def test_a_product_that_is_not_on_the_order_cannot_be_paid_for() -> None:
    line = claim_lines(ClaimedProduct(name="Beef Trachea Chews", quantity=1))[0]
    assert line.match is MatchOutcome.NOT_ON_ORDER

    conclusion = a_conclusion(
        damaged_items=(DamagedItem(product_name="Beef Trachea Chews", quantity=1),),
        **an_email_with_no_figure(),
    )

    result = await investigate(a_run_that_concludes(conclusion), lines=(line,))

    assert result.outcome.recommendation is Recommendation.REQUEST_REP_CLARIFICATION
    assert OverrideReason.PRODUCT_NOT_PRICEABLE in result.outcome.overrides
    assert "not on the order" in result.outcome.explanation

    assert result.amount.components == ()
    assert result.amount.proposed_usd == Decimal("40.00")


async def test_only_the_damaged_items_are_covered_and_never_the_whole_order() -> None:
    result = await investigate(a_run_that_concludes(a_conclusion()))

    assert result.amount.items_total_usd == Decimal("52.00")
    assert [component.product_name for component in result.amount.components] == [COLLAGEN]


async def test_the_amount_is_capped() -> None:
    whey = OrderLineItem(
        name="2.5LBS White Chocolate Raspberry Huge Whey",
        sku="0159",
        quantity=4,
        unit_price=Decimal("59.99"),
    )
    order = Order(order_id="337761802", user_id="334430", line_items=(whey,))
    line = claim_lines(ClaimedProduct(name=whey.name, quantity=4, sku="0159"), order=order)[0]
    conclusion = a_conclusion(
        damaged_items=(DamagedItem(product_name=whey.name, quantity=4, sku="0159"),),
        recommended_amount_usd="180.00",
    )

    result = await investigate(
        a_run_that_concludes(conclusion),
        lines=(line,),
        order=order,
        invoice=Invoice(invoice_id="INV-337761802", line_items=(whey,)),
    )

    assert result.amount.proposed_usd == Decimal("180.00")
    assert result.amount.amount_usd == Decimal("100.00")
    assert result.amount.cap_applied is True
    assert result.drafted_email is not None
    assert "$100.00" in result.drafted_email.body

    assert "180.00" not in result.drafted_email.body


async def test_the_figure_is_worked_out_from_the_invoice_and_never_from_what_the_model_wrote() -> (
    None
):
    conclusion = a_conclusion(
        reasoning="The bottle is crushed. I would put it at about $12.00.",
        concerns=("I am not certain the $12.00 I have in mind is the right price.",),
    )

    result = await investigate(a_run_that_concludes(conclusion))

    assert result.amount.amount_usd == Decimal("40.00")
    assert result.amount.priced_from == "INV-342578703"
    assert [component.unit_price for component in result.amount.components] == [Decimal("52.00")]
    assert result.drafted_email is not None

    assert "12.00" not in result.drafted_email.body
    assert "$40.00" in result.drafted_email.body
    assert "$40.00" in result.drafted_email.body


async def test_an_email_carrying_a_figure_the_model_wrote_is_refused_and_goes_to_a_person() -> None:
    conclusion = a_conclusion(
        email_body="We have looked at your claim and will refund $52.00 for the collagen."
    )

    result = await investigate(a_run_that_concludes(conclusion))

    assert result.outcome.recommendation is Recommendation.REQUEST_REP_CLARIFICATION
    assert result.drafted_email is None
    assert result.conclusion is not None
    assert result.conclusion.recommendation is Recommendation.APPROVE
    assert any("amount of money" in concern for concern in result.concerns)


async def test_an_approval_withheld_for_missing_evidence_requests_it_without_money() -> None:
    conclusion = a_conclusion(
        evidence=evidence_all_in_hand(customer_confirmation=EvidenceState.MISSING)
    )

    result = await investigate(a_run_that_concludes(conclusion))

    assert result.outcome.recommendation is Recommendation.REQUEST_INFO
    assert result.drafted_email is not None
    assert "additional information" in result.drafted_email.body
    assert "customer who received the parcel" in result.drafted_email.body
    assert "$40.00" not in result.drafted_email.body


async def test_what_the_claim_settled_about_the_parcel_stands_over_this_run_s_own_read() -> None:
    conclusion = a_conclusion(**an_email_with_no_figure())

    result = await investigate(
        a_run_that_concludes(conclusion),
        shared_evidence=(settled(EvidenceKind.OUTER_PACKAGING_PHOTO, EvidenceState.MISSING),),
    )

    assert state_of(result, EvidenceKind.OUTER_PACKAGING_PHOTO) is EvidenceState.MISSING
    assert any("outer packaging photo" in concern for concern in result.concerns)
    assert result.outcome.recommendation is Recommendation.REQUEST_INFO


async def test_the_photographs_of_the_damage_are_this_product_s_own() -> None:
    result = await investigate(
        a_run_that_concludes(a_conclusion()),
        shared_evidence=(settled(EvidenceKind.DAMAGED_PRODUCT_PHOTO, EvidenceState.MISSING),),
    )

    assert state_of(result, EvidenceKind.DAMAGED_PRODUCT_PHOTO) is EvidenceState.PRESENT
    assert result.outcome.recommendation is Recommendation.APPROVE


async def test_fr_1b_1_one_run_sees_the_whole_claim_and_answers_for_all_of_it() -> None:
    lines = the_collagen_beside(five_other_products())
    model = a_run_that_concludes(a_conclusion())

    result = await investigate(model, lines=lines)

    asked = model.asked[0].text
    assert "1 order affected" in asked
    assert AMPOULE in asked
    assert "Duck Neck Crunchies" in asked
    assert result.lines == lines


async def test_fr_1b_3_a_claim_of_six_products_gets_one_recommendation_and_one_email() -> None:
    lines = the_collagen_beside(five_other_products())

    result = await investigate(a_run_that_concludes(a_conclusion()), lines=lines)

    assert result.outcome.recommendation is Recommendation.REQUEST_REP_CLARIFICATION
    assert len(result.lines) == 6

    assert OverrideReason.PRODUCT_NOT_PRICEABLE in result.outcome.overrides


async def test_fr_1b_3_one_unpriceable_product_withholds_the_whole_claim() -> None:
    lines = claim_lines(
        ClaimedProduct(name=COLLAGEN, quantity=1, sku=COLLAGEN_SKU),
        ClaimedProduct(name="Beef Trachea Chews", quantity=1),
    )
    conclusion = a_conclusion(
        damaged_items=(
            DamagedItem(product_name=COLLAGEN, quantity=1, sku=COLLAGEN_SKU),
            DamagedItem(product_name="Beef Trachea Chews", quantity=1),
        ),
    )

    result = await investigate(a_run_that_concludes(conclusion), lines=lines)

    assert result.outcome.recommendation is Recommendation.REQUEST_REP_CLARIFICATION
    assert OverrideReason.PRODUCT_NOT_PRICEABLE in result.outcome.overrides
    assert "Beef Trachea Chews is not on the order" in result.outcome.explanation
    assert result.drafted_email is None


async def test_fr_1b_4_the_report_names_every_product_and_what_each_cost() -> None:
    lines = claim_lines(
        ClaimedProduct(name=COLLAGEN, quantity=1, sku=COLLAGEN_SKU),
        ClaimedProduct(name=AMPOULE, quantity=1, sku="AMPOULE1"),
    )
    conclusion = a_conclusion(
        damaged_items=(
            DamagedItem(product_name=COLLAGEN, quantity=1, sku=COLLAGEN_SKU),
            DamagedItem(product_name=AMPOULE, quantity=1, sku="AMPOULE1"),
        ),
        recommended_amount_usd="70.00",
    )

    result = await investigate(a_run_that_concludes(conclusion), lines=lines)

    assert sorted(line.product_name for line in result.lines) == sorted([COLLAGEN, AMPOULE])
    assert [component.product_name for component in result.amount.components] == [
        COLLAGEN,
        AMPOULE,
    ]
    assert result.amount.items_total_usd == Decimal("90.00")
    assert result.amount.amount_usd == Decimal("70.00")


async def test_fr_1b_3_the_claim_cap_applies_to_the_whole_claim_by_being_one_figure() -> None:
    tubs = OrderLineItem(
        name="2.5LBS White Chocolate Raspberry Huge Whey",
        sku="0159",
        quantity=3,
        unit_price=Decimal("50.00"),
    )
    order = Order(order_id="337761802", user_id="334430", line_items=(tubs,))
    lines = claim_lines(ClaimedProduct(name=tubs.name, quantity=3, sku="0159"), order=order)
    conclusion = a_conclusion(
        damaged_items=(DamagedItem(product_name=tubs.name, quantity=3, sku="0159"),),
        recommended_amount_usd="150.00",
    )

    result = await investigate(
        a_run_that_concludes(conclusion),
        lines=lines,
        order=order,
        invoice=Invoice(invoice_id="INV-337761802", line_items=(tubs,)),
    )

    assert result.amount.proposed_usd == Decimal("150.00")
    assert result.amount.amount_usd == Decimal("100.00")
    assert result.amount.cap_applied is True
    assert result.outcome.recommendation.is_approval


async def test_nfr_1_the_order_the_products_arrive_in_is_the_order_they_are_described_in() -> None:
    lines = the_collagen_beside(five_other_products())

    once = a_run_that_concludes(a_conclusion())
    again = a_run_that_concludes(a_conclusion())
    await investigate(once, lines=lines)
    await investigate(again, lines=lines)

    assert once.asked[0].text == again.asked[0].text


async def test_the_same_claim_investigated_twice_produces_the_same_write_up() -> None:
    first = await investigate(a_run_that_concludes(a_conclusion()))
    second = await investigate(a_run_that_concludes(a_conclusion()))

    assert first == second


async def test_the_run_says_what_it_started_on_and_what_it_recommends() -> None:
    events = EventStream()

    await investigate(a_run_that_concludes(a_conclusion()), events=events)

    said = {event.kind: event for event in events.events()}
    assert COLLAGEN in said[EventKind.INVESTIGATION_STARTED].summary
    assert (
        said[EventKind.INVESTIGATION_FINISHED].detail["recommendation"]
        == Recommendation.APPROVE.value
    )
    assert "52.00" not in said[EventKind.INVESTIGATION_FINISHED].summary


def a_closed_claim(**overrides: object) -> PrecedentRecord:
    fields: dict[str, object] = {
        "precedent_id": "PREC-CASE-0900-L01",
        "case_id": "CASE-0900",
        "claim_line_id": "CASE-0900-L01",
        "user_id": "283959",
        "product_name": "Liposomal Tripeptide Collagen",
        "sku": "COLLAGEN1",
        "unit_price": Decimal("52.00"),
        "merchant_account": "The bottle arrived cracked in a crushed box.",
        "match": MatchOutcome.MATCHED,
        "evidence": (),
        "assessments": (),
        "outcome": Recommendation.REQUEST_REP_CLARIFICATION,
        "amount_usd": None,
        "cap_applied": False,
        "rep_note": "Refused: the crushing happened after delivery.",
        "withdrawn": False,
        "closed_at": datetime(2026, 1, 8, tzinfo=UTC),
    }
    fields.update(overrides)
    return PrecedentRecord(**fields)


def a_precedent_set(*records: PrecedentRecord) -> PrecedentSet:
    return PrecedentSet(
        retrieved=tuple(
            RetrievedPrecedent(
                record=record,
                similarity=PrecedentSimilarity(
                    score=0.9, reasons=("the product names share: collagen",)
                ),
            )
            for record in records
        ),
        considered=len(records),
    )


def what_the_model_was_asked(model: ScriptedModel) -> str:
    return model.asked[0].text


async def test_fr_s_6_a_run_is_handed_the_closed_claims_most_like_its_product() -> None:
    model = a_run_that_concludes(a_conclusion())

    await investigate(model, precedent=a_precedent_set(a_closed_claim()))

    asked = what_the_model_was_asked(model)
    assert "## SIMILAR CLAIMS HANDLED BEFORE" in asked
    assert "CASE-0900" in asked
    assert "closed as: request_rep_clarification" in asked
    assert "the crushing happened after delivery" in asked


async def test_fr_s_13_a_run_told_nothing_about_precedent_is_not_told_there_is_none() -> None:
    model = a_run_that_concludes(a_conclusion())

    await investigate(model, precedent=None)

    assert "## SIMILAR CLAIMS HANDLED BEFORE" not in what_the_model_was_asked(model)


async def test_fr_s_13_a_run_is_told_when_the_store_was_read_and_held_nothing() -> None:
    model = a_run_that_concludes(a_conclusion())

    await investigate(model, precedent=a_precedent_set())

    assert "holds nothing much like this one" in what_the_model_was_asked(model)


async def test_fr_1_21_what_past_claims_were_settled_for_is_shown_to_the_model() -> None:
    model = a_run_that_concludes(a_conclusion())

    await investigate(
        model,
        precedent=a_precedent_set(
            a_closed_claim(outcome=Recommendation.APPROVE, amount_usd=Decimal("52.00"))
        ),
    )

    asked = what_the_model_was_asked(model)
    section = asked[asked.index("## SIMILAR CLAIMS HANDLED BEFORE") :]
    assert "52.00" in section


async def test_fr_1_8_to_fr_1_11_all_four_judgements_come_back_with_their_reasoning() -> None:
    result = await investigate(a_run_that_concludes(a_conclusion(assessments=all_four_answered())))

    answered = {assessment.name: assessment for assessment in result.assessments}
    assert tuple(answered) == REQUIRED_ASSESSMENTS

    for name in REQUIRED_ASSESSMENTS:
        judgement = answered[name]
        assert judgement.reasoning.strip(), f"{name} was answered with no reasoning"


async def test_fr_1_9_a_product_that_cannot_be_identified_is_not_paid_for() -> None:
    result = await investigate(
        a_run_that_concludes(
            a_conclusion(
                assessments=all_four_answered(product_identifiable=False),
                recommendation=Recommendation.APPROVE,
                **an_email_with_no_figure(),
            )
        )
    )

    assert result.outcome.recommendation is not Recommendation.APPROVE
    identified = next(
        assessment
        for assessment in result.assessments
        if assessment.name is AssessmentName.PRODUCT_IDENTIFIABLE
    )
    assert identified.passed is False
