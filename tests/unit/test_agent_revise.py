from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal

import httpx
import respx
from langchain_core.exceptions import ModelConnectionError
from langchain_core.messages import AIMessage
from tests.fakes.model import ScriptedModel, scripted
from tests.fixtures.attachments import ATTACHMENTS_1001, INVOICE_342578703
from tests.fixtures.shipbob import CASE_1001, ORDER_1001, SHIPMENT_1001

from claim_agent.agent.events import EventStream
from claim_agent.agent.images import ImageFetcher
from claim_agent.agent.investigate import ClaimFindings, investigate_claim_lines
from claim_agent.agent.llm import StructuredModel
from claim_agent.agent.observations import ObservationCache
from claim_agent.agent.prompts import EarlierExchange
from claim_agent.agent.revise import (
    ClaimFindingsRevision,
    ReportUnderReview,
    rework_claim_findings,
)
from claim_agent.agent.schemas import (
    AssessmentJudgement,
    DamagedItem,
    EvidenceJudgement,
    InvestigationConclusion,
    RevisionConclusion,
)
from claim_agent.agent.threads import PassThread, PassThreads
from claim_agent.agent.tools import LIST_ATTACHMENTS, TOOL_NAMES
from claim_agent.domain.assessment import REQUIRED_ASSESSMENTS, Assessment, AssessmentName
from claim_agent.domain.claim_line import ClaimedProduct, ClaimLine, MatchOutcome, build_claim_lines
from claim_agent.domain.evidence import (
    REQUIRED_EVIDENCE,
    EvidenceFinding,
    EvidenceKind,
    EvidenceState,
    findings_by_kind,
)
from claim_agent.domain.models import Attachment, Case, DraftedEmail, Invoice, Order, Shipment
from claim_agent.domain.outcome import OverrideReason, Recommendation
from claim_agent.domain.reimbursement import AmountDerivation, review_recommended_amount
from claim_agent.policy import Policy
from claim_agent.preflight.models import CaseRecord, ClaimContext
from claim_agent.settings import Settings
from claim_agent.shipbob.evidence_client import EvidenceClient

SHIPBOB = "http://shipbob.test"

CASE = Case.model_validate(CASE_1001)
SHIPMENT = Shipment.model_validate(SHIPMENT_1001)
ORDER = Order.model_validate(ORDER_1001)
INVOICE = Invoice.model_validate(INVOICE_342578703)

COLLAGEN = "Liposomal Tripeptide Collagen"
COLLAGEN_SKU = "COLLAGEN1"
AMPOULE = "Additional Collagen Ampoule Duo"


def images_on_the_claim() -> tuple[Attachment, ...]:
    """The images CASE-1001 actually carries, as the rework is handed them."""
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


# --- The report a representative is sending back ----------------------------


def build_settings() -> Settings:
    """Settings for a test process, with no credentials and nowhere to cache downloads."""
    return Settings(
        environment="test",
        log_level="WARNING",
        anthropic_api_key=None,
        shipbob_base_url=SHIPBOB,
        attachment_allowed_hosts=("images.test",),
        attachment_cache_dir=None,
        attachment_timeout_seconds=1.0,
    )


def a_claim_for_the_collagen() -> ClaimLine:
    """One claim line: the $52.00 collagen, matched to exactly one line on the order."""
    lines = build_claim_lines(
        CASE.case_id, (ClaimedProduct(name=COLLAGEN, quantity=1, sku=COLLAGEN_SKU),), ORDER
    )
    assert lines[0].match is MatchOutcome.MATCHED
    return lines[0]


def the_ampoule_beside_it() -> ClaimLine:
    """The claim's other damaged product, as a sibling line."""
    lines = build_claim_lines(
        CASE.case_id, (ClaimedProduct(name=AMPOULE, quantity=1, sku="AMP1"),), ORDER
    )
    return lines[0]


def all_four_findings(**states: EvidenceState) -> tuple[EvidenceFinding, ...]:
    """What the earlier report recorded about each piece of evidence, present by default."""
    return tuple(
        EvidenceFinding(
            kind=kind,
            state=states.get(kind.value, EvidenceState.PRESENT),
            observed=f"What the earlier report recorded about the {kind.value}.",
            attachment_id=IMAGES[0].attachment_id,
        )
        for kind in REQUIRED_EVIDENCE
    )


def all_four_answers(**passed: bool) -> tuple[Assessment, ...]:
    """What the earlier report recorded as its answers to the four questions."""
    return tuple(
        Assessment(
            name=name,
            passed=passed.get(name.value, True),
            reasoning=f"What the earlier report said about {name.value}.",
            attachment_ids=(IMAGES[0].attachment_id,),
        )
        for name in REQUIRED_ASSESSMENTS
    )


def an_amount(figure: str = "40.00") -> AmountDerivation:
    """The figure the earlier report carried, with its working, capped as it was."""
    return review_recommended_amount(
        figure,
        reasoning="The bottle is cracked through and the contents are lost.",
        damaged=(ClaimedProduct(name=COLLAGEN, quantity=1, sku=COLLAGEN_SKU),),
        invoice=INVOICE,
        policy=Policy(),
    )


def a_report_under_review(**overrides: object) -> ReportUnderReview:
    """A sound approval report, as it stands when a representative sends it back."""
    fields: dict[str, object] = {
        "lines": (a_claim_for_the_collagen(),),
        "context": CONTEXT,
        "attachments": IMAGES,
        "recommendation": Recommendation.APPROVE,
        "amount": an_amount(),
        "evidence": all_four_findings(),
        "assessments": all_four_answers(),
        "concerns": ("The photograph is taken close in.",),
        "drafted_email": DraftedEmail(
            to="merchant@example.test",
            subject="About your damaged shipment",
            body="We have looked at your claim and approved the damaged collagen.",
        ),
    }
    fields.update(overrides)
    return ReportUnderReview.model_validate(fields)


# --- The answer the reworking gives -----------------------------------------


def judgements(**states: EvidenceState) -> tuple[EvidenceJudgement, ...]:
    """All four pieces of evidence as the rework reports them, present unless told otherwise."""
    return tuple(
        EvidenceJudgement(
            kind=kind,
            state=states.get(kind.value, EvidenceState.PRESENT),
            observed=f"What the rework saw in the {kind.value}.",
            attachment_id=IMAGES[0].attachment_id,
        )
        for kind in REQUIRED_EVIDENCE
    )


def answers(**passed: bool) -> tuple[AssessmentJudgement, ...]:
    """The four questions as the rework answers them, yes unless a test says otherwise."""
    return tuple(
        AssessmentJudgement(
            name=name,
            passed=passed.get(name.value, True),
            reasoning=f"Why the rework answers {name.value} that way.",
            attachment_ids=(IMAGES[0].attachment_id,),
        )
        for name in REQUIRED_ASSESSMENTS
    )


def a_rework(**overrides: object) -> RevisionConclusion:
    """A reworked answer that still recommends payment, at a figure it has reconsidered."""
    fields: dict[str, object] = {
        "evidence": judgements(),
        "assessments": answers(),
        "damaged_items": (DamagedItem(product_name=COLLAGEN, quantity=1, sku=COLLAGEN_SKU),),
        "recommended_amount_usd": "52.00",
        "amount_reasoning": "The whole bottle is lost rather than dented.",
        "recommendation": Recommendation.APPROVE,
        "reasoning": "The photographs show the bottle broken through, and it is on the invoice.",
        "concerns": ("The photograph is taken close in.",),
        "changed": ("Raised the amount, because the bottle is a total loss.",),
        "left_unchanged": ("The four questions, which the note did not bear on.",),
        "reply_to_representative": "You were right about the amount; I have raised it.",
        "email_subject": "About your damaged shipment",
        "email_body": "We have looked at your claim again and approved the damaged collagen.",
    }
    fields.update(overrides)
    return RevisionConclusion.model_validate(fields)


# --- Running one rework -----------------------------------------------------


async def rework(
    model: ScriptedModel,
    *,
    under_review: ReportUnderReview | None = None,
    feedback: str = "The amount looks wrong to me.",
    policy: Policy | None = None,
    events: EventStream | None = None,
    threads: PassThreads | None = None,
    thread_id: str | None = None,
) -> ClaimFindingsRevision:
    """Rework one report, with everything a test does not care about defaulted.

    The HTTP clients are real ones aimed at a name only a stand-in answers to, so a request
    that escaped a test would fail loudly rather than reach a machine. Most tests here never
    make one: their model never asks for a tool, and the invoice read fails harmlessly.
    """
    settings = build_settings()
    async with (
        httpx.AsyncClient(base_url=SHIPBOB, timeout=1.0) as shipbob_http,
        httpx.AsyncClient() as images_http,
    ):
        return await rework_claim_findings(
            under_review=under_review if under_review is not None else a_report_under_review(),
            feedback=feedback,
            record=RECORD,
            evidence_client=EvidenceClient(shipbob_http, max_attempts=1),
            fetcher=ImageFetcher(images_http, settings),
            chat=model,
            structured=StructuredModel(model, max_attempts=1),
            events=events if events is not None else EventStream(),
            policy=policy if policy is not None else Policy(),
            threads=threads,
            thread_id=thread_id,
        )


async def an_investigation_on(thread: PassThread, model: ScriptedModel) -> ClaimFindings:
    """Investigate the collagen once, keeping the conversation on this thread."""
    settings = build_settings()
    async with (
        httpx.AsyncClient(base_url=SHIPBOB, timeout=1.0) as shipbob_http,
        httpx.AsyncClient() as images_http,
    ):
        return await investigate_claim_lines(
            lines=(a_claim_for_the_collagen(),),
            record=RECORD,
            context=CONTEXT,
            attachments=IMAGES,
            invoice=INVOICE,
            evidence=EvidenceClient(shipbob_http, max_attempts=1),
            fetcher=ImageFetcher(images_http, settings),
            chat=model,
            structured=StructuredModel(model, max_attempts=1),
            cache=ObservationCache(),
            events=EventStream(),
            policy=Policy(),
            thread=thread,
        )


def a_first_conclusion() -> InvestigationConclusion:
    """What the first pass concluded, for a thread a rework will continue."""
    return InvestigationConclusion(
        evidence=judgements(),
        assessments=answers(),
        damaged_items=(DamagedItem(product_name=COLLAGEN, quantity=1, sku=COLLAGEN_SKU),),
        recommended_amount_usd="40.00",
        recommendation=Recommendation.APPROVE,
        reasoning="The photographs show the bottle broken, and it is on the invoice.",
        email_subject="About your damaged shipment",
        email_body="We have looked at your claim and approved the damaged collagen.",
    )


def a_run_that_concludes(answer: RevisionConclusion) -> ScriptedModel:
    """A model that looks at nothing, says it has seen enough, and fills the form in."""
    return scripted("I have read the note and the report.", answer)


def finding(result: ClaimFindingsRevision, kind: EvidenceKind) -> EvidenceFinding:
    """What the reworked findings say about one of the four pieces of evidence."""
    assert result.findings is not None
    return findings_by_kind(result.findings.evidence)[kind]


def answered(result: ClaimFindingsRevision) -> Sequence[AssessmentName]:
    """Which of the four questions the reworked report has answers to."""
    assert result.findings is not None
    return [answer.name for answer in result.findings.assessments]


# --- What a rework produces (FR-R.9, FR-R.10, FR-R.11) ----------------------


async def test_fr_r_9_a_rework_produces_a_whole_report_not_a_patch() -> None:
    """FR-R.9: the output is a full report in the same structure as the first one."""
    result = await rework(a_run_that_concludes(a_rework()))

    assert result.reworked
    assert result.findings is not None
    assert len(result.findings.evidence) == len(REQUIRED_EVIDENCE)
    assert len(result.findings.assessments) == len(REQUIRED_ASSESSMENTS)
    assert result.findings.outcome.recommendation is Recommendation.APPROVE


async def test_fr_r_10_what_changed_and_what_was_left_alone_both_come_back() -> None:
    """FR-R.10: a rep confirms they were understood without re-reading the whole report."""
    result = await rework(a_run_that_concludes(a_rework()))

    assert result.changed == ("Raised the amount, because the bottle is a total loss.",)
    assert result.left_unchanged == ("The four questions, which the note did not bear on.",)
    assert result.reply == "You were right about the amount; I have raised it."


async def test_fr_r_11_the_merchant_email_is_rewritten_to_match_the_reworked_report() -> None:
    """FR-R.11: a revised recommendation with a stale email is an inconsistent state."""
    result = await rework(a_run_that_concludes(a_rework()))

    assert result.findings is not None
    email = result.findings.drafted_email
    assert email is not None
    assert "again" in email.body
    # The figure that reached the merchant is the one that survived the cap, added by code.
    assert "$52.00" in email.body


async def test_fr_r_11_an_outcome_that_now_addresses_the_representative_carries_no_email() -> None:
    """FR-R.11, FR-2.7: a report asking a representative to clarify has nothing to send."""
    result = await rework(
        a_run_that_concludes(
            a_rework(
                recommendation=Recommendation.REQUEST_REP_CLARIFICATION,
                recommended_amount_usd=None,
                amount_reasoning=None,
                email_subject=None,
                email_body=None,
            )
        )
    )

    assert result.findings is not None
    assert result.findings.drafted_email is None


async def test_a_question_for_the_representative_is_marked_as_one() -> None:
    """A rework that cannot settle without the rep says so, so a screen can wait on them."""
    result = await rework(
        a_run_that_concludes(
            a_rework(
                reply_to_representative="Which of the two bottles did the customer photograph?",
                needs_more_from_representative=True,
            )
        )
    )

    assert result.needs_reply


# --- Carrying the earlier work forward (FR-R.5) -----------------------------


async def test_fr_r_5_evidence_the_rework_did_not_mention_carries_forward() -> None:
    """FR-R.5: a rep correcting one thing must not have to re-check everything else."""
    only_the_box = (
        EvidenceJudgement(
            kind=EvidenceKind.OUTER_PACKAGING_PHOTO,
            state=EvidenceState.PRESENT,
            observed="The box is photographed after all, on the second image.",
            attachment_id=IMAGES[1].attachment_id,
        ),
    )

    result = await rework(a_run_that_concludes(a_rework(evidence=only_the_box)))

    assert finding(result, EvidenceKind.INVOICE).state is EvidenceState.PRESENT
    assert "earlier report recorded" in finding(result, EvidenceKind.INVOICE).observed
    assert finding(result, EvidenceKind.OUTER_PACKAGING_PHOTO).observed.startswith("The box is")


async def test_fr_r_5_questions_the_rework_did_not_answer_carry_forward() -> None:
    """FR-R.5: leaving three questions out must not read as an unfinished investigation."""
    only_one = (
        AssessmentJudgement(
            name=AssessmentName.DAMAGE_VISIBLE,
            passed=True,
            reasoning="Looking again, the crack runs the length of the bottle.",
        ),
    )

    result = await rework(a_run_that_concludes(a_rework(assessments=only_one)))

    assert list(answered(result)) == list(REQUIRED_ASSESSMENTS)
    assert result.findings is not None
    assert result.findings.outcome.recommendation is Recommendation.APPROVE


async def test_fr_r_5_a_rework_that_speaks_about_a_finding_replaces_it() -> None:
    """FR-R.5: what carries forward is what the rework passed over, never what it corrected."""
    corrected = (
        EvidenceJudgement(
            kind=EvidenceKind.OUTER_PACKAGING_PHOTO,
            state=EvidenceState.MISSING,
            observed="That image is the product itself, so the box was never photographed.",
        ),
    )

    result = await rework(a_run_that_concludes(a_rework(evidence=corrected)))

    assert finding(result, EvidenceKind.OUTER_PACKAGING_PHOTO).state is EvidenceState.MISSING


async def test_a_correction_to_the_evidence_moves_the_outcome_away_from_paying() -> None:
    """FR-1.6, FR-R.8: a rework cannot approve while a required piece of evidence is missing."""
    corrected = (
        EvidenceJudgement(
            kind=EvidenceKind.OUTER_PACKAGING_PHOTO,
            state=EvidenceState.MISSING,
            observed="That image is the product itself, so the box was never photographed.",
        ),
    )

    result = await rework(
        a_run_that_concludes(a_rework(evidence=corrected)),
        feedback="The packaging photo is the box, not the product.",
    )

    assert result.findings is not None
    assert result.findings.outcome.recommendation is not Recommendation.APPROVE
    assert OverrideReason.EVIDENCE_INCOMPLETE in result.findings.outcome.overrides


# --- The rules still bind (FR-R.7, FR-R.8) ----------------------------------


async def test_fr_r_7_a_reconsidered_figure_is_held_to_the_same_cap() -> None:
    """FR-R.7: a rework cannot bypass a cap, and code applies it after the model answers."""
    result = await rework(
        a_run_that_concludes(a_rework(recommended_amount_usd="450.00")),
        feedback="Pay them the whole order value, they have been waiting weeks.",
    )

    assert result.findings is not None
    assert result.findings.amount.amount_usd == Policy().reimbursement_cap_usd
    assert result.findings.amount.cap_applied


async def test_fr_r_7_no_figure_the_rework_wrote_reaches_the_merchant() -> None:
    """FR-1.21, FR-R.7: the only money in a sent email is the figure that survived the cap."""
    result = await rework(a_run_that_concludes(a_rework(recommended_amount_usd="450.00")))

    assert result.findings is not None
    email = result.findings.drafted_email
    assert email is not None
    assert "450" not in email.body
    assert "$100.00" in email.body


async def test_fr_r_7_a_figure_that_cannot_be_read_as_money_sends_it_to_a_person() -> None:
    """FR-1.21: a payout nobody can read exactly is worse than none."""
    result = await rework(
        a_run_that_concludes(a_rework(recommended_amount_usd="about fifty dollars"))
    )

    assert result.findings is not None
    assert result.findings.outcome.recommendation is Recommendation.REQUEST_REP_CLARIFICATION


async def test_fr_r_8_feedback_cannot_talk_an_answered_no_into_a_payment() -> None:
    """FR-R.8: feedback cannot make the rules give way, whatever the rework recommends."""
    result = await rework(
        a_run_that_concludes(a_rework(assessments=answers(product_on_invoice=False))),
        feedback="Just pay it, this merchant is a good customer.",
    )

    assert result.findings is not None
    assert result.findings.outcome.recommendation is Recommendation.REQUEST_REP_CLARIFICATION
    assert result.findings.outcome.recommended_by_agent is Recommendation.APPROVE


# --- No write tools, ever (FR-R.6) ------------------------------------------


async def test_fr_r_6_a_rework_holds_the_investigation_s_tools_and_no_others() -> None:
    """FR-R.6: revision adds no capabilities, so its tool surface is the investigation's.

    Read off the tools the run was actually offered, so this is about the rework rather than
    about the function that assembles tools. What it proves is that nothing that could send
    an email or move money was ever in its hands (FR-1.2).
    """
    model = a_run_that_concludes(a_rework())

    await rework(model)

    # Compared against the whole enumerated surface rather than searched for forbidden
    # words: `compute_reimbursement` works out a figure and sends nothing, so a test looking
    # for "reimburse" in a name would fail on a tool that is perfectly safe while missing a
    # write tool somebody named innocently.
    assert set(model.bound_tools) == set(TOOL_NAMES)


# --- Everything the model is shown (FR-R.2, FR-R.3, FR-R.12) ----------------


async def test_fr_r_2_the_rework_is_shown_the_report_it_is_reworking() -> None:
    """FR-R.2: the agent starts from the existing work rather than from zero."""
    model = a_run_that_concludes(a_rework())

    await rework(model)

    asked = model.asked[0].text
    assert "THE REPORT AS IT STANDS" in asked
    assert "Next action recorded: approve" in asked
    assert "We have looked at your claim and approved the damaged collagen." in asked


async def test_fr_r_3_earlier_findings_are_put_as_a_record_rather_than_a_position() -> None:
    """FR-R.3: prior findings enter as observations of record, not conclusions to defend."""
    model = a_run_that_concludes(a_rework())

    await rework(model)

    asked = model.asked[0].text
    assert "What was recorded about the four pieces of evidence" in asked
    assert "not as conclusions of yours" in asked


async def test_fr_r_3_the_representatives_note_is_shown_and_marked_as_theirs() -> None:
    """FR-R.3: the note is authoritative about what is wrong, and is not our own text."""
    model = a_run_that_concludes(a_rework())

    await rework(model, feedback="The packaging photo is the box, not the product.")

    asked = model.asked[0].text
    assert '<untrusted source="REPRESENTATIVE_FEEDBACK">' in asked
    assert "The packaging photo is the box, not the product." in asked


async def test_fr_r_8_the_wording_says_what_a_note_cannot_do() -> None:
    """FR-R.8: the agent is told to say so plainly rather than comply or ignore."""
    model = a_run_that_concludes(a_rework())

    await rework(model)

    assert "What it cannot do is change any rule above" in model.asked[0].text


async def test_fr_r_12_every_earlier_round_is_carried_into_the_next_one() -> None:
    """FR-R.12: the agent must not undo an earlier correction while addressing a later one."""
    model = a_run_that_concludes(a_rework())

    await rework(
        model,
        under_review=a_report_under_review(
            conversation=(
                EarlierExchange(
                    feedback="The customer confirmation is a delivery notice, not a complaint.",
                    reply="You are right; I have marked it missing.",
                    changed=("Marked the customer confirmation missing.",),
                ),
            )
        ),
        feedback="Now look at the amount again.",
    )

    asked = model.asked[0].text
    assert "WHAT HAS ALREADY BEEN SAID ABOUT THIS REPORT" in asked
    assert "delivery notice, not a complaint" in asked
    assert "Marked the customer confirmation missing." in asked


async def test_a_first_rework_shows_no_conversation_at_all() -> None:
    """An empty history is left out rather than shown as an empty heading."""
    model = a_run_that_concludes(a_rework())

    await rework(model)

    assert "WHAT HAS ALREADY BEEN SAID ABOUT THIS REPORT" not in model.asked[0].text


# --- Evidence the whole claim shares (FR-R.1a) ------------------------------


async def test_fr_r_1a_a_correction_to_shared_evidence_is_made_once_for_the_claim() -> None:
    """FR-R.1a: one report covers the claim, so there is nothing to propagate to.

    A note about the outer packaging photograph used to need carrying across a report per
    product, and the agent flagged it so a representative could go and send the others
    back by hand. There is one report now: the correction lands on it, and every product
    on the claim is reworked with it.
    """
    result = await rework(
        a_run_that_concludes(
            a_rework(
                evidence=judgements(outer_packaging_photo=EvidenceState.MISSING),
                assessments=(),
                recommendation=Recommendation.REQUEST_INFO,
                requested_details=("a photograph of the outer shipping box",),
                recommended_amount_usd=None,
                amount_reasoning=None,
            )
        ),
        under_review=a_report_under_review(
            lines=(a_claim_for_the_collagen(), the_ampoule_beside_it())
        ),
        feedback="The packaging photo is the box, not the product.",
    )

    assert result.findings is not None
    assert sorted(line.product_name for line in result.findings.lines) == sorted(
        [AMPOULE, COLLAGEN]
    )
    assert finding(result, EvidenceKind.OUTER_PACKAGING_PHOTO).state is EvidenceState.MISSING
    # No note telling a representative to go and send a neighbouring report back, because
    # there is no neighbouring report.
    assert not any("sent back separately" in concern for concern in result.findings.concerns)


# --- Failing toward the person (NFR-4) --------------------------------------


async def test_a_model_that_cannot_be_reached_leaves_the_report_as_it_was() -> None:
    """NFR-4: a rework that could not run is an outcome to report, not an exception."""
    result = await rework(scripted(ModelConnectionError("the provider is down")))

    assert not result.reworked
    assert result.findings is None
    assert "nothing in it has changed" in result.reply


async def test_a_run_that_uses_up_its_steps_says_why_it_stopped() -> None:
    """FR-1.16, NFR-4: the representative is told what happened and what they can do.

    The model keeps asking for a tool and never stops, so the step allowance is what ends the
    run — which is the point: the allowance lives outside the conversation and no amount of
    model output can talk past it.
    """
    keeps_looking = scripted(
        AIMessage(
            content="Let me look at the images again.",
            tool_calls=[
                {"name": LIST_ATTACHMENTS, "args": {}, "id": "call-1", "type": "tool_call"}
            ],
        )
    )

    with respx.mock(assert_all_called=False) as api:
        api.get(f"{SHIPBOB}/cases/{CASE.case_id}/attachments").respond(200, json=ATTACHMENTS_1001)
        api.post(f"{SHIPBOB}/invoices/generate").respond(200, json=INVOICE_342578703)
        result = await rework(keeps_looking, policy=Policy(max_agent_steps=1))

    assert not result.reworked
    assert "Send it back again" in result.reply


async def test_the_rework_narrates_that_it_started_and_finished() -> None:
    """A screen watching a rework sees it begin and end, as it does an investigation."""
    events = EventStream()

    await rework(a_run_that_concludes(a_rework()), events=events)

    said = [event.summary for event in events.events()]
    assert any("Reworking" in summary for summary in said)
    assert any("Finished reworking" in summary for summary in said)


# --- The representative directs, the agent complies (FR-2.8) ----------------


async def test_a_representative_directing_an_approval_gets_one() -> None:
    """The agent can be wrong, and the representative is what corrects it.

    The outer packaging photograph is missing, which the rules would normally treat as reason
    enough to withhold a payment. The representative has said pay it anyway, and they can see
    things this system cannot.
    """
    result = await rework(
        a_run_that_concludes(
            a_rework(
                evidence=judgements(outer_packaging_photo=EvidenceState.MISSING),
                representative_directed_outcome=True,
            )
        ),
        feedback="The customer sent the box photo to me by email. Approve it.",
    )

    assert result.findings is not None
    assert result.findings.outcome.recommendation is Recommendation.APPROVE
    assert result.findings.amount.amount_usd == Decimal("52.00")


async def test_a_directed_approval_records_every_rule_it_set_aside() -> None:
    """NFR-5, FR-C.1: a directed payment and an earned one must never look the same."""
    result = await rework(
        a_run_that_concludes(
            a_rework(
                evidence=judgements(outer_packaging_photo=EvidenceState.MISSING),
                representative_directed_outcome=True,
            )
        ),
        feedback="Approve it.",
    )

    assert result.findings is not None
    outcome = result.findings.outcome
    assert outcome.directed_by_representative
    assert OverrideReason.EVIDENCE_INCOMPLETE in outcome.waived
    assert outcome.overrides == ()
    assert "A representative directed this payment" in outcome.explanation


async def test_a_directed_approval_still_gets_the_email_with_the_checked_figure() -> None:
    """FR-1.21: code adds the amount, so a merchant sees the figure that survived the limit."""
    result = await rework(
        a_run_that_concludes(
            a_rework(recommended_amount_usd="450.00", representative_directed_outcome=True)
        ),
        feedback="Pay it in full.",
    )

    assert result.findings is not None
    email = result.findings.drafted_email
    assert email is not None
    assert "$100.00" in email.body
    assert "450" not in email.body


async def test_a_directed_approval_with_nothing_payable_asks_instead_of_paying_nothing() -> None:
    """An instruction cannot conjure a figure, so the agent asks rather than approving zero.

    This is the one thing that happens instead of approving, and it is a question rather than
    a refusal: there is no amount to put in the email, so there is nothing to send.
    """
    result = await rework(
        a_run_that_concludes(
            a_rework(
                recommended_amount_usd=None,
                amount_reasoning=None,
                representative_directed_outcome=True,
            )
        ),
        feedback="Just approve it.",
    )

    assert result.findings is not None
    assert result.findings.outcome.recommendation is not Recommendation.APPROVE


async def test_an_ordinary_rework_is_still_held_to_every_rule() -> None:
    """FR-1.6: nothing changes for a rework the representative did not direct."""
    result = await rework(
        a_run_that_concludes(
            a_rework(evidence=judgements(outer_packaging_photo=EvidenceState.MISSING))
        ),
        feedback="Have another look at the box.",
    )

    assert result.findings is not None
    assert result.findings.outcome.recommendation is not Recommendation.APPROVE
    assert OverrideReason.EVIDENCE_INCOMPLETE in result.findings.outcome.overrides
    assert not result.findings.outcome.directed_by_representative


async def test_the_wording_tells_the_agent_to_do_what_it_is_told() -> None:
    """The prompt has to lead with complying, not with the two things it cannot change."""
    model = a_run_that_concludes(a_rework())

    await rework(model)

    asked = model.asked[0].text
    assert "WHEN THEY TELL YOU TO APPROVE" in asked
    assert "You can be wrong, and they are what corrects you." in asked


# --- A rework continues the investigation's own conversation (FR-R.2) --------


async def test_fr_r_2_a_rework_continues_the_thread_the_investigation_wrote() -> None:
    """FR-R.2: the note is answered by the pass that looked at the claim, from its own context."""
    threads = PassThreads()
    thread = threads.start(CASE.case_id)
    first = scripted("I have seen enough.", a_first_conclusion())
    investigated = await an_investigation_on(thread, first)
    assert investigated.thread_id == thread.thread_id

    second = a_run_that_concludes(a_rework())
    result = await rework(second, threads=threads, thread_id=thread.thread_id)

    shown = second.asked[0].text
    # The first pass's question and remark come first, then the new turn.
    assert shown.index("THE PRODUCTS YOU ARE ANSWERING FOR") < shown.index("I have seen enough.")
    assert shown.index("I have seen enough.") < shown.index("THE REPORT AS IT STANDS")
    assert shown.index("THE REPORT AS IT STANDS") < shown.index("The amount looks wrong to me.")
    # The claim, the order and the images are not rendered a second time.
    assert shown.count("WHAT WAS ORDERED") == 1
    assert shown.count("THE IMAGES ON THIS CLAIM") == 1
    assert "earlier in this conversation" in shown
    # The reworked findings still name the thread, so the next round continues it too.
    assert result.findings is not None
    assert result.findings.thread_id == thread.thread_id


async def test_a_rework_whose_thread_is_gone_rebuilds_its_context_from_the_report() -> None:
    """A restart loses threads, not the ability to rework: the prose path still stands."""
    threads = PassThreads()
    model = a_run_that_concludes(a_rework())

    result = await rework(model, threads=threads, thread_id="a-thread-nobody-holds")

    shown = model.asked[0].text
    assert "WHAT WAS ORDERED" in shown
    assert "THE REPORT AS IT STANDS" in shown
    assert "earlier in this conversation" not in shown
    # It started a thread of its own, so the round after this one can continue it.
    assert result.findings is not None
    assert result.findings.thread_id is not None
    assert result.findings.thread_id != "a-thread-nobody-holds"
    assert await threads.remembers(result.findings.thread_id) is True


async def test_a_rework_without_a_registry_keeps_no_thread_and_names_none() -> None:
    """The pass with no registry is the pass as it was before threads existed."""
    model = a_run_that_concludes(a_rework())

    result = await rework(model)

    assert result.findings is not None
    assert result.findings.thread_id is None
