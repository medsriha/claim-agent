from __future__ import annotations

from decimal import Decimal

import httpx
import pytest
from pydantic import ValidationError
from tests.fakes.model import scripted
from tests.unit.test_agent_revise import (
    CASE,
    COLLAGEN,
    COLLAGEN_SKU,
    CONTEXT,
    IMAGES,
    INVOICE,
    RECORD,
    a_claim_for_the_collagen,
    a_report_under_review,
    all_four_answers,
    all_four_findings,
    an_amount,
)

from claim_agent.agent.directed import DirectedPayment, approve_as_directed, what_pricing_produced
from claim_agent.agent.events import EventKind, EventStream, RunEvent
from claim_agent.agent.investigate import ClaimFindings
from claim_agent.agent.llm import StructuredModel
from claim_agent.agent.prompts import build_claim_revision_messages, build_revision_plan_messages
from claim_agent.agent.revise import (
    ClaimRevision,
    DirectedApproval,
    plan_report_reply,
    rework_claim_report,
)
from claim_agent.agent.schemas import (
    RevisedClaimReport,
    RevisionMode,
    RevisionPlan,
    SettledProduct,
)
from claim_agent.domain.claim_line import ClaimedProduct, ClaimLine, build_claim_lines
from claim_agent.domain.evidence import REQUIRED_EVIDENCE, EvidenceState, findings_by_kind
from claim_agent.domain.outcome import OverrideReason, Recommendation
from claim_agent.policy import Policy

AMPOULE = "Additional Collagen Ampoule Duo"


def an_instruction(**overrides: object) -> DirectedPayment:
    """What the model read off "approve the refund": approval wording and no figure."""
    fields: dict[str, object] = {
        "email_subject": "Your damage claim has been approved",
        "email_body": "We have reviewed your claim for the damaged collagen and approved it.",
    }
    fields.update(overrides)
    return DirectedPayment.model_validate(fields)


async def paid(
    *,
    lines: tuple[ClaimLine, ...] | None = None,
    directed: DirectedPayment | None = None,
    invoice: object = INVOICE,
    policy: Policy | None = None,
    events: EventStream | None = None,
    **carried: object,
) -> ClaimFindings:
    """Approve one claim as directed, with everything a test does not care about defaulted."""
    return await approve_as_directed(
        lines=lines if lines is not None else (a_claim_for_the_collagen(),),
        directed=directed if directed is not None else an_instruction(),
        invoice=invoice,  # type: ignore[arg-type]
        policy=policy if policy is not None else Policy(),
        contact_email=CASE.contact_email,
        model="scripted",
        events=events if events is not None else EventStream(),
        **carried,  # type: ignore[arg-type]
    )


# --- The figure (FR-1.20, FR-1.21) --------------------------------------------


async def test_a_claim_nobody_investigated_is_priced_at_what_the_invoice_says() -> None:
    """The representative named no figure, so the invoice decides: one collagen at $52.00."""
    findings = await paid()

    assert findings.outcome.recommendation is Recommendation.APPROVE
    assert findings.amount.amount_usd == Decimal("52.00")
    assert findings.amount.priced_from == INVOICE.invoice_id
    assert "cost on the invoice" in findings.amount.reasoning


async def test_a_figure_the_representative_named_is_the_one_paid() -> None:
    """They said what to pay, and that is what is paid."""
    findings = await paid(directed=an_instruction(amount_usd="30.00"))

    assert findings.amount.amount_usd == Decimal("30.00")
    assert "representative named" in findings.amount.reasoning


async def test_a_figure_the_representative_named_is_still_held_to_the_cap() -> None:
    """FR-1.20: the cap is the one thing an instruction cannot lift."""
    findings = await paid(directed=an_instruction(amount_usd="450.00"))

    assert findings.amount.amount_usd == Policy().reimbursement_cap_usd
    assert findings.amount.cap_applied
    assert findings.drafted_email is not None
    assert "450" not in findings.drafted_email.body


async def test_the_reports_own_figure_is_paid_when_it_had_one() -> None:
    """The investigation judged the damage at $40; the rules withheld it; the rep overruled."""
    findings = await paid(earlier_amount=an_amount("40.00"))

    assert findings.amount.amount_usd == Decimal("40.00")
    assert "investigation's own figure" in findings.amount.reasoning


async def test_a_figure_that_cannot_be_read_falls_back_to_the_invoice() -> None:
    """A figure nobody can read exactly is not paid; the invoice is."""
    findings = await paid(directed=an_instruction(amount_usd="fifty bucks"))

    assert findings.amount.amount_usd == Decimal("52.00")


async def test_nothing_payable_asks_the_representative_instead_of_paying_nothing() -> None:
    """An instruction cannot conjure a figure: no invoice and no report figure means asking."""
    findings = await paid(invoice=None)

    assert findings.outcome.recommendation is Recommendation.REQUEST_REP_CLARIFICATION
    assert "Tell me the amount" in what_pricing_produced(findings)


async def test_asking_for_the_figure_still_keeps_the_email_for_the_representative() -> None:
    """The draft is written even without the figure, so the rep adjusts it rather than waits.

    It carries no amount line: the figure is added when they approve at one.
    """
    findings = await paid(invoice=None)

    email = findings.drafted_email
    assert email is not None
    assert email.subject == "Your damage claim has been approved"
    assert "Approved amount" not in email.body
    assert "$" not in email.body


# --- The email --------------------------------------------------------------


async def test_the_approval_email_carries_the_checked_figure() -> None:
    """FR-1.21: the figure in the email is the one code worked out."""
    findings = await paid()

    assert findings.drafted_email is not None
    assert findings.drafted_email.to == CASE.contact_email
    assert findings.drafted_email.subject == "Your damage claim has been approved"
    assert "Approved amount: $52.00" in findings.drafted_email.body


async def test_wording_the_model_did_not_write_is_replaced_rather_than_failing() -> None:
    """A decision a person took must not fall over for want of an email."""
    findings = await paid(directed=DirectedPayment())

    assert findings.outcome.recommendation is Recommendation.APPROVE
    assert findings.drafted_email is not None
    assert COLLAGEN in findings.drafted_email.body
    assert "Approved amount: $52.00" in findings.drafted_email.body
    assert any("plain approval email" in concern for concern in findings.concerns)


async def test_a_figure_the_model_wrote_into_the_email_is_thrown_out() -> None:
    """FR-1.21: no figure the model wrote reaches a merchant."""
    findings = await paid(directed=an_instruction(email_body="We will refund you $99.00."))

    assert findings.drafted_email is not None
    assert "$99.00" not in findings.drafted_email.body
    assert "Approved amount: $52.00" in findings.drafted_email.body


# --- The record (NFR-3, NFR-5) -------------------------------------------------


async def test_a_claim_nobody_investigated_says_so_on_every_piece_of_evidence() -> None:
    """The report must not read as though the photographs were looked at."""
    findings = await paid()

    by_kind = findings_by_kind(findings.evidence)
    assert set(by_kind) == set(REQUIRED_EVIDENCE)
    assert all("Not reviewed" in by_kind[kind].observed for kind in REQUIRED_EVIDENCE)
    assert findings.assessments == ()


async def test_what_an_earlier_report_established_is_carried_forward_untouched() -> None:
    """An investigated report keeps every finding; only the outcome and the email change."""
    findings = await paid(
        evidence=all_four_findings(outer_packaging_photo=EvidenceState.MISSING),
        assessments=all_four_answers(),
        concerns=("The photograph is taken close in.",),
    )

    by_kind = findings_by_kind(findings.evidence)
    assert all("earlier report" in by_kind[kind].observed for kind in REQUIRED_EVIDENCE)
    assert len(findings.assessments) == 4
    assert "The photograph is taken close in." in findings.concerns


async def test_every_rule_set_aside_is_recorded_as_waived() -> None:
    """NFR-5: a payment a person directed and one the evidence earned must never look alike."""
    findings = await paid()

    assert findings.outcome.directed_by_representative
    assert findings.outcome.overrides == ()
    assert OverrideReason.EVIDENCE_INCOMPLETE in findings.outcome.waived
    assert OverrideReason.INVESTIGATION_INCOMPLETE in findings.outcome.waived


async def test_the_pricing_is_written_into_the_ledger_and_costs_no_steps() -> None:
    """NFR-3: somebody reading the report can see the figure was priced, not judged."""
    findings = await paid()

    assert [entry.name for entry in findings.ledger] == ["price_as_directed"]
    assert findings.budget.steps_used == 0
    assert findings.budget.model_calls == 0
    assert findings.conclusion is not None
    assert "without another review of the evidence" in findings.conclusion.reasoning


async def test_it_narrates_that_it_priced_rather_than_investigated() -> None:
    """Whoever is watching is told what is happening, and that it is not a second pass."""
    seen: list[RunEvent] = []

    async def keep(event: RunEvent) -> None:
        seen.append(event)

    await paid(events=EventStream(sink=keep))

    kinds = [event.kind for event in seen]
    assert kinds == [EventKind.INVESTIGATION_STARTED, EventKind.INVESTIGATION_FINISHED]
    assert "without another review" in seen[0].summary
    assert "$52.00" in seen[1].summary


async def test_two_products_are_priced_together_as_one_claim() -> None:
    """FR-1b.3: one figure across every product the representative named."""
    lines = build_claim_lines(
        CASE.case_id,
        (
            ClaimedProduct(name=COLLAGEN, quantity=1, sku=COLLAGEN_SKU),
            ClaimedProduct(name=AMPOULE, quantity=1, sku="AMP1"),
        ),
        RECORD.order,
    )

    findings = await paid(lines=lines)

    assert findings.outcome.recommendation.is_approval
    assert len(findings.amount.components) == 2
    assert findings.amount.amount_usd == findings.amount.items_total_usd


# --- The plan routes an approval here (FR-2.8) ---------------------------------


async def test_an_instruction_to_approve_an_investigated_report_skips_the_rework() -> None:
    """The plan hands back the instruction and the wording, and no evidence pass runs."""
    model = scripted(
        RevisionPlan(
            mode=RevisionMode.APPROVE_AS_DIRECTED,
            reply_to_representative="Approving it as you directed.",
            changed=("Approved the claim.",),
            email_subject="Your damage claim has been approved",
            email_body="We have approved your claim for the damaged collagen.",
            directed_amount_usd="45.00",
        )
    )

    planned = await plan_report_reply(
        under_review=a_report_under_review(recommendation=Recommendation.REQUEST_INFO),
        feedback="Approve the refund.",
        structured=StructuredModel(model, max_attempts=1),
        events=EventStream(),
    )

    assert isinstance(planned, DirectedApproval)
    assert planned.reply == "Approving it as you directed."
    assert planned.changed == ("Approved the claim.",)
    assert planned.directed == DirectedPayment(
        email_subject="Your damage claim has been approved",
        email_body="We have approved your claim for the damaged collagen.",
        amount_usd="45.00",
    )
    assert not planned.reworked


def test_the_plan_wording_says_an_instruction_to_pay_is_never_a_rework() -> None:
    """The router has to be told that approving is cheaper than reinvestigating."""
    asked = build_revision_plan_messages(
        claim_lines=(a_claim_for_the_collagen(),),
        recommendation=Recommendation.REQUEST_INFO,
        amount=an_amount(),
        evidence=all_four_findings(),
        assessments=all_four_answers(),
        concerns=(),
        drafted_email=None,
        feedback="Approve the refund.",
    )

    wording = str(asked[0].content)
    assert "approve_as_directed" in wording
    assert "An instruction to pay is never rework_report." in wording


def test_an_approve_as_directed_plan_needs_the_email_wording() -> None:
    """Approval wording is the model's one contribution, so a plan without it is no plan."""
    with pytest.raises(ValidationError):
        RevisionPlan(mode=RevisionMode.APPROVE_AS_DIRECTED, reply_to_representative="Done.")


def test_only_an_approve_as_directed_plan_may_name_a_figure() -> None:
    with pytest.raises(ValidationError):
        RevisionPlan(
            mode=RevisionMode.EMAIL_ONLY,
            reply_to_representative="Done.",
            email_subject="s",
            email_body="b",
            directed_amount_usd="10.00",
        )


# --- A clarification report answered with "pay it" (FR-1a.4, FR-2.8) -----------


async def rework_the_clarification(answer: RevisedClaimReport) -> ClaimRevision:
    """Answer a representative about a claim nobody could split, from a script."""
    model = scripted(answer)
    async with httpx.AsyncClient() as _unused:
        return await rework_claim_report(
            case_record=RECORD,
            context=CONTEXT,
            attachments=IMAGES,
            ambiguity="Two products, and no photograph tells them apart.",
            candidate_lines=(),
            requested_details=("Which product was damaged",),
            concerns=(),
            drafted_email=None,
            feedback="It is the collagen. Approve the refund.",
            conversation=(),
            structured=StructuredModel(model, max_attempts=1),
            events=EventStream(),
        )


async def test_naming_a_product_and_saying_pay_it_carries_the_instruction_out() -> None:
    """The answer carries the products and the instruction, and asks the merchant nothing."""
    revision = await rework_the_clarification(
        RevisedClaimReport(
            reply_to_representative="Taken as read: the collagen. Pricing it now.",
            settled_products=(SettledProduct(name=COLLAGEN, quantity=1, sku=COLLAGEN_SKU),),
            representative_directed_payment=True,
            email_subject="Your damage claim has been approved",
            email_body="We have approved your claim for the damaged collagen.",
        )
    )

    assert revision.directed == DirectedPayment(
        email_subject="Your damage claim has been approved",
        email_body="We have approved your claim for the damaged collagen.",
    )
    assert [product.name for product in revision.settled] == [COLLAGEN]
    assert revision.email is None
    assert revision.requested_details == ()
    assert revision.reworked


async def test_an_instruction_to_pay_with_no_product_named_asks_and_keeps_the_draft() -> None:
    """Nothing can be priced without a product, so the agent asks — and still writes the email."""
    revision = await rework_the_clarification(
        RevisedClaimReport(
            reply_to_representative="Which of the two products do you mean?",
            representative_directed_payment=True,
            email_subject="Your damage claim has been approved",
            email_body="We have approved your claim for the damaged product.",
        )
    )

    assert revision.directed is None
    assert revision.needs_reply
    assert revision.recommendation is Recommendation.REQUEST_REP_CLARIFICATION
    assert revision.email is not None
    assert revision.email.to == CASE.contact_email
    assert revision.email.subject == "Your damage claim has been approved"
    assert revision.reworked


async def test_an_instruction_to_pay_with_no_product_and_no_wording_only_asks() -> None:
    """Without wording there is nothing to keep, and the question still goes to the rep."""
    revision = await rework_the_clarification(
        RevisedClaimReport(
            reply_to_representative="Which of the two products do you mean?",
            representative_directed_payment=True,
        )
    )

    assert revision.email is None
    assert revision.needs_reply


def test_a_figure_may_only_be_named_alongside_an_instruction_to_pay() -> None:
    with pytest.raises(ValidationError):
        RevisedClaimReport(reply_to_representative="Done.", directed_amount_usd="10.00")


def test_the_claim_wording_tells_the_agent_that_paying_is_not_investigating() -> None:
    """The prompt has to say that an instruction to pay is priced, not looked into again."""
    asked = build_claim_revision_messages(
        case=CASE,
        order=RECORD.order,
        attachments=IMAGES,
        context=CONTEXT,
        ambiguity="Two products.",
        candidate_lines=(),
        requested_details=(),
        concerns=(),
        drafted_email=None,
        feedback="Approve the refund.",
    )

    wording = "\n".join(str(message.content) for message in asked)
    assert "WHEN THEY TELL YOU TO PAY" in wording
    assert "Nothing is investigated again" in wording
    assert "representative_directed_payment" in wording
    assert "do not push back and do not decline" in wording
    assert "still write the approval email" in wording
