"""Building the messages each pass is asked: the shared rules, a task, and the claim's records."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage

from claim_agent.agent.prompts.render import (
    EarlierExchange,
    kept_warm,
    messages,
    quote_untrusted,
    render_attachments,
    render_candidates,
    render_case,
    render_claim_lines,
    render_claim_report_as_it_stands,
    render_conversation,
    render_corrections,
    render_feedback,
    render_order,
    render_precedent,
    render_report_as_it_stands,
    render_shared_evidence,
    render_why_it_was_stopped,
    section,
    warm_block,
)
from claim_agent.agent.prompts.wording import (
    ALL_PROMPTS,
    CLAIM_REVISION_PROMPT,
    IMAGE_CLASSIFICATION_PROMPT,
    INVESTIGATION_PROMPT,
    PROMPT_VERSION,
    REVISION_PLAN_PROMPT,
    REVISION_PROMPT,
    REVISION_TURN_PROMPT,
    SCREENING_REVISION_PROMPT,
    SYSTEM_PROMPT,
    TRIAGE_PROMPT,
)
from claim_agent.domain.assessment import Assessment
from claim_agent.domain.claim_line import ClaimLine
from claim_agent.domain.evidence import EvidenceFinding
from claim_agent.domain.models import Attachment, Case, DraftedEmail, Order
from claim_agent.domain.outcome import Recommendation
from claim_agent.domain.reimbursement import AmountDerivation
from claim_agent.preflight.models import ClaimContext
from claim_agent.storage.precedent_store import PrecedentSet

__all__ = [
    "ALL_PROMPTS",
    "CLAIM_REVISION_PROMPT",
    "IMAGE_CLASSIFICATION_PROMPT",
    "INVESTIGATION_PROMPT",
    "PROMPT_VERSION",
    "REVISION_PLAN_PROMPT",
    "REVISION_PROMPT",
    "REVISION_TURN_PROMPT",
    "SCREENING_REVISION_PROMPT",
    "SYSTEM_PROMPT",
    "TRIAGE_PROMPT",
    "EarlierExchange",
    "build_claim_revision_messages",
    "build_image_classification_messages",
    "build_investigation_messages",
    "build_revision_messages",
    "build_revision_plan_messages",
    "build_revision_turn_messages",
    "build_screening_revision_messages",
    "build_triage_messages",
    "quote_untrusted",
]


def build_image_classification_messages(
    *, image_url: str, question: str | None = None
) -> list[BaseMessage]:
    """Ask what one image is, and whether it can be relied on (FR-1.4, FR-1.5).

    No file name and no file type go with it (FR-1.4). The wording is marked to be kept
    warm and the picture is not, since what repeats across a claim's images is the text.
    """
    instruction = IMAGE_CLASSIFICATION_PROMPT
    if question is not None:
        instruction = "\n\n".join(
            [instruction, section("SOMETHING PARTICULAR TO LOOK FOR", question)]
        )
    parts: list[str | dict[str, Any]] = [
        warm_block(instruction),
        {"type": "image_url", "image_url": {"url": image_url}},
    ]
    return [SystemMessage(content=kept_warm(SYSTEM_PROMPT)), HumanMessage(content=parts)]


def build_triage_messages(
    *,
    case: Case,
    order: Order | None,
    attachments: Sequence[Attachment],
    context: ClaimContext,
) -> list[BaseMessage]:
    """Ask which products a claim is for (FR-1a.1, FR-1a.2, FR-1a.4)."""
    sections = [
        TRIAGE_PROMPT,
        render_case(case, context),
        render_order(order),
        render_attachments(attachments),
        *render_corrections(context.merchant_corrections),
    ]
    return messages("\n\n".join(sections))


def build_investigation_messages(
    *,
    case: Case,
    order: Order | None,
    attachments: Sequence[Attachment],
    context: ClaimContext,
    claim_lines: Sequence[ClaimLine],
    shared_evidence: Sequence[EvidenceFinding] = (),
    precedent: PrecedentSet | None = None,
) -> list[BaseMessage]:
    """Ask what should happen to one claim and every product on it (FR-1b.1, FR-1b.2).

    `precedent` of `None` means nobody looked and shows no section; a set that was looked
    up and found nothing says so, because the two are different facts (FR-S.13).
    """
    sections = [
        INVESTIGATION_PROMPT,
        render_case(case, context),
        render_order(order),
        render_attachments(attachments),
        render_claim_lines(claim_lines),
        *render_shared_evidence(shared_evidence),
        *render_precedent(precedent),
        *render_corrections(context.merchant_corrections),
    ]
    return messages("\n\n".join(sections))


def build_revision_messages(
    *,
    case: Case,
    order: Order | None,
    attachments: Sequence[Attachment],
    context: ClaimContext,
    claim_lines: Sequence[ClaimLine],
    recommendation: Recommendation,
    amount: AmountDerivation,
    evidence: Sequence[EvidenceFinding],
    assessments: Sequence[Assessment],
    concerns: Sequence[str],
    drafted_email: DraftedEmail | None,
    feedback: str,
    conversation: Sequence[EarlierExchange] = (),
    precedent: PrecedentSet | None = None,
) -> list[BaseMessage]:
    """Ask for a report to be reworked, rebuilding the claim's context from the report (FR-R.2).

    Used when the investigation's own conversation thread is no longer held. The claim is
    rendered as on a first pass, then the report as it stands, the earlier rounds, and the note.
    """
    sections = [
        REVISION_PROMPT,
        render_case(case, context),
        render_order(order),
        render_attachments(attachments),
        render_claim_lines(claim_lines),
        render_report_as_it_stands(
            recommendation=recommendation,
            amount=amount,
            evidence=evidence,
            assessments=assessments,
            concerns=concerns,
            drafted_email=drafted_email,
        ),
        *render_precedent(precedent),
        *render_corrections(context.merchant_corrections),
        *render_conversation(conversation),
        render_feedback(feedback),
    ]
    return messages("\n\n".join(sections))


def build_revision_plan_messages(
    *,
    claim_lines: Sequence[ClaimLine],
    recommendation: Recommendation,
    amount: AmountDerivation,
    evidence: Sequence[EvidenceFinding],
    assessments: Sequence[Assessment],
    concerns: Sequence[str],
    drafted_email: DraftedEmail | None,
    feedback: str,
    conversation: Sequence[EarlierExchange] = (),
) -> list[BaseMessage]:
    """Ask whether a reply needs expensive evidence work, using only the stored report."""
    sections = [
        render_claim_lines(claim_lines),
        render_report_as_it_stands(
            recommendation=recommendation,
            amount=amount,
            evidence=evidence,
            assessments=assessments,
            concerns=concerns,
            drafted_email=drafted_email,
        ),
        *render_conversation(conversation),
        render_feedback(feedback),
    ]
    return [
        SystemMessage(content=REVISION_PLAN_PROMPT),
        HumanMessage(content="\n\n".join(sections)),
    ]


def build_revision_turn_messages(
    *,
    recommendation: Recommendation,
    amount: AmountDerivation,
    evidence: Sequence[EvidenceFinding],
    assessments: Sequence[Assessment],
    concerns: Sequence[str],
    drafted_email: DraftedEmail | None,
    feedback: str,
    conversation: Sequence[EarlierExchange] = (),
) -> list[BaseMessage]:
    """One new turn on the investigation's own thread after a send-back (FR-R.2).

    The claim, order, images and precedent are already in that conversation, so only the
    report as it stands, the earlier rounds and the note are new. No system message: the
    rules are already the first message on the thread.
    """
    sections = [
        REVISION_TURN_PROMPT,
        render_report_as_it_stands(
            recommendation=recommendation,
            amount=amount,
            evidence=evidence,
            assessments=assessments,
            concerns=concerns,
            drafted_email=drafted_email,
        ),
        *render_conversation(conversation),
        render_feedback(feedback),
    ]
    return [HumanMessage(content=kept_warm("\n\n".join(sections)))]


def build_claim_revision_messages(
    *,
    case: Case,
    order: Order | None,
    attachments: Sequence[Attachment],
    context: ClaimContext,
    ambiguity: str,
    candidate_lines: Sequence[ClaimLine],
    requested_details: Sequence[str],
    concerns: Sequence[str],
    drafted_email: DraftedEmail | None,
    feedback: str,
    conversation: Sequence[EarlierExchange] = (),
) -> list[BaseMessage]:
    """Answer a representative about a claim whose split was never settled (FR-1a.4)."""
    sections = [
        CLAIM_REVISION_PROMPT,
        render_case(case, context),
        render_order(order),
        render_attachments(attachments),
        render_candidates(candidate_lines),
        render_claim_report_as_it_stands(
            ambiguity=ambiguity,
            requested_details=requested_details,
            concerns=concerns,
            drafted_email=drafted_email,
        ),
        *render_corrections(context.merchant_corrections),
        *render_conversation(conversation),
        render_feedback(feedback),
    ]
    return messages("\n\n".join(sections))


def build_screening_revision_messages(
    *,
    case: Case,
    context: ClaimContext,
    findings: Sequence[str],
    drafted_email: DraftedEmail | None,
    feedback: str,
    conversation: Sequence[EarlierExchange] = (),
) -> list[BaseMessage]:
    """Answer a representative about a claim the quick checks turned away (FR-0.6, FR-R.8).

    The order and the images are deliberately absent: nothing was investigated and nothing
    will be, so the run is not shown evidence about a claim it cannot reopen.
    """
    sections = [
        SCREENING_REVISION_PROMPT,
        render_case(case, context),
        render_why_it_was_stopped(findings, drafted_email),
        *render_conversation(conversation),
        render_feedback(feedback),
    ]
    return messages("\n\n".join(sections))
