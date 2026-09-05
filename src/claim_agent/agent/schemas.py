"""The forms the AI fills in. It never replies with prose to be interpreted."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from claim_agent.domain.assessment import AssessmentName
from claim_agent.domain.evidence import EvidenceKind, EvidenceState
from claim_agent.domain.outcome import Recommendation

# The marker used by approval drafts produced under the previous prompt.
AMOUNT_PLACEHOLDER = "{{amount}}"


class _WithoutSubjectiveConfidence(BaseModel):
    """Accept old stored/test values without advertising confidence to the model."""

    @model_validator(mode="before")
    @classmethod
    def _discard_legacy_confidence(cls, value: object) -> object:
        if not isinstance(value, dict) or "confidence" not in value:
            return value
        without_confidence = dict(value)
        without_confidence.pop("confidence")
        return without_confidence


class ImageObservation(_WithoutSubjectiveConfidence):
    """What one image turned out to be, and whether it is any use (FR-1.4, FR-1.5)."""

    model_config = ConfigDict(extra="forbid")

    shows: str = Field(description="What is visible in this image, in one plain sentence.")
    kind: EvidenceKind | None = Field(
        default=None,
        description="Which of the four kinds of evidence this image is, or null if none of them.",
    )
    is_legible: bool = Field(
        default=True,
        description="False if the image is too dark, blurry or cropped to draw a conclusion from.",
    )
    problem: str | None = Field(
        default=None,
        description=(
            "Why the image cannot be relied on, in words the merchant could act on. "
            "Null when it can be."
        ),
    )


class ClaimedProductProposal(_WithoutSubjectiveConfidence):
    """One product the investigation believes was damaged (FR-1a.1)."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(description="The product's name, as written on the order where possible.")
    quantity: int = Field(ge=1, description="How many of this product are being claimed for.")
    sku: str | None = Field(
        default=None, description="The product's code from the order, or null if not established."
    )
    damage_attachment_ids: tuple[str, ...] = Field(
        default=(),
        description="Ids of the images that show damage to this particular product.",
    )
    reasoning: str = Field(description="Why you believe this product was damaged.")


class ClaimSplit(_WithoutSubjectiveConfidence):
    """Which products a claim is for — the conclusion of the triage pass (FR-1a.1)."""

    model_config = ConfigDict(extra="forbid")

    claimed_products: tuple[ClaimedProductProposal, ...] = Field(
        default=(), description="One entry per damaged product you have identified."
    )
    is_ambiguous: bool = Field(
        default=False,
        description="True if you cannot establish which products are being claimed for.",
    )
    ambiguity: str | None = Field(
        default=None,
        description=(
            "A concise one- or two-sentence summary of what is unclear. Do not include "
            "headings, a numbered analysis, or repeat the requested_details list. Null if "
            "nothing is unclear."
        ),
    )
    requested_details: tuple[str, ...] = Field(
        default=(),
        description=(
            "Every specific detail the merchant can provide to settle an ambiguous split. "
            "Empty when the split is settled or only a representative can resolve it."
        ),
    )
    email_subject: str | None = Field(
        default=None,
        description=(
            "Subject of the merchant email requesting those details. Null when "
            "requested_details is empty."
        ),
    )
    email_body: str | None = Field(
        default=None,
        description=(
            "Exact merchant email requesting every requested detail. Null when "
            "requested_details is empty."
        ),
    )
    concerns: tuple[str, ...] = Field(
        default=(),
        description=(
            "One short item per thing a reviewer needs to know that the merchant email "
            "does not tell them: what the evidence showed, what conflicts with what, and "
            "what you could not establish. Name the image, product or document each one "
            "is about. Do not repeat requested_details — the email already asks for those "
            "— and do not write a headed mini-report."
        ),
    )
    reasoning: str = Field(description="One or two short sentences explaining the split.")


class EvidenceJudgement(BaseModel):
    """The model's read on one of the four pieces of evidence (FR-1.5, FR-2.2)."""

    model_config = ConfigDict(extra="forbid")

    kind: EvidenceKind = Field(description="Which of the four pieces of evidence this is about.")
    state: EvidenceState = Field(
        description="present if usable, missing if absent, unusable if present but not reliable."
    )
    observed: str = Field(description="What you actually saw, in one plain sentence.")
    attachment_id: str | None = Field(
        default=None,
        description="The image this came from. Null only when the evidence is missing.",
    )
    problem: str | None = Field(
        default=None,
        description="If unusable, why — in words the merchant could act on. Otherwise null.",
    )


class AssessmentJudgement(_WithoutSubjectiveConfidence):
    """One of the four judgements, with the reasoning that makes it reviewable (FR-2.3)."""

    model_config = ConfigDict(extra="forbid")

    name: AssessmentName = Field(description="Which of the four questions this answers.")
    passed: bool = Field(description="Your answer to it.")
    reasoning: str = Field(description="Why, in one or two plain sentences.")
    attachment_ids: tuple[str, ...] = Field(
        default=(), description="Ids of the images this judgement rests on."
    )


class DamagedItem(BaseModel):
    """A product this claim line should be reimbursed for, and how many of it."""

    model_config = ConfigDict(extra="forbid")

    product_name: str = Field(description="The product's name exactly as the order writes it.")
    quantity: int = Field(ge=1, description="How many of it were damaged.")
    sku: str | None = Field(default=None, description="The product's code, or null.")


class InvestigationConclusion(_WithoutSubjectiveConfidence):
    """The conclusion of one claim line's investigation — the model's whole answer."""

    model_config = ConfigDict(extra="forbid")

    evidence: tuple[EvidenceJudgement, ...] = Field(
        description="Your read on each of the four pieces of evidence."
    )
    assessments: tuple[AssessmentJudgement, ...] = Field(
        default=(),
        description=(
            "Your answers to the four questions. Leave empty if the evidence is "
            "incomplete, since there is nothing yet to assess."
        ),
    )
    damaged_items: tuple[DamagedItem, ...] = Field(
        default=(),
        description="The products this claim line should be reimbursed for, if any.",
    )
    is_ambiguous: bool = Field(
        default=False,
        description="True if you cannot tell which product on the order was damaged.",
    )
    ambiguity: str | None = Field(
        default=None,
        description=(
            "A concise one- or two-sentence summary of what is unclear, without headings, "
            "numbered analysis, or repeated merchant requests. Null if nothing is unclear."
        ),
    )
    recommendation: Recommendation = Field(description="What you recommend doing about this line.")

    @field_validator("recommendation")
    @classmethod
    def _the_high_value_label_is_not_the_models_to_claim(
        cls, chosen: Recommendation
    ) -> Recommendation:
        """Read a model-chosen high-value approval as the plain approval it is (FR-C.7).

        Whether the damaged goods were expensive is arithmetic, and code does it after the
        rules have run. A model that asks for the label is asking to approve, so that is
        what it gets — read this way rather than refused, since the answer is otherwise
        perfectly good and the rules that hold an approval back must still run over it.
        """
        if chosen is Recommendation.APPROVE_HIGH_VALUE:
            return Recommendation.APPROVE
        return chosen

    reasoning: str = Field(
        description=(
            "One or two short sentences giving the decision basis without retelling every finding "
            "or listing requested_details. This is the findings summary a representative sees "
            "beside the next step; the exact merchant requests appear in the email instead."
        )
    )
    recommended_amount_usd: str | None = Field(
        default=None,
        description=(
            "What ShipBob should pay for this product, in dollars, written as digits with "
            "at most two decimal places and no currency symbol — for example 31.20. Judge "
            "it from how badly the product is damaged and from how comparable past claims "
            "were settled; what the item cost is context, not the answer. Null unless you "
            "are recommending approve."
        ),
    )
    amount_reasoning: str | None = Field(
        default=None,
        description=(
            "One or two short sentences explaining why that figure and not another, so a "
            "representative can disagree with it. Null unless you name one."
        ),
    )
    concerns: tuple[str, ...] = Field(
        default=(),
        description=(
            "Short, separate items for anything weak, conflicting or uncertain a reviewer "
            "should know. Do not repeat requested_details or write a headed mini-report."
        ),
    )
    corrections_considered: tuple[str, ...] = Field(
        default=(),
        description="Case ids of past rep corrections that changed your conclusion.",
    )
    requested_details: tuple[str, ...] = Field(
        default=(),
        description=(
            "Every specific additional detail the merchant must provide for request_info. "
            "Empty for approve and request_rep_clarification."
        ),
    )
    email_subject: str | None = Field(
        default=None,
        description=(
            "Subject line of the email to the merchant. Null when the next action is "
            "request_rep_clarification."
        ),
    )
    email_body: str | None = Field(
        default=None,
        description=(
            "The merchant-facing email wording. "
            "For request_info, name every specific detail the merchant needs to provide. "
            "For approve, communicate the approval but do not write an amount or placeholder; "
            "code adds the capped figure to produce the final wording. Null when the next action is "
            "request_rep_clarification."
        ),
    )


class _RepliesToTheRepresentative(BaseModel):
    """The four things every reworked answer says back, whatever kind of report it was."""

    changed: tuple[str, ...] = Field(
        default=(),
        description=(
            "Each finding, judgement, amount or piece of wording you changed in response to "
            "the feedback, one per item, and why you changed it. Empty only if you changed "
            "nothing at all."
        ),
    )
    left_unchanged: tuple[str, ...] = Field(
        default=(),
        description=(
            "The parts of the earlier report the feedback did not bear on, which you have "
            "carried forward as they were. One short item each."
        ),
    )
    reply_to_representative: str = Field(
        description=(
            "Your answer to the representative in one or two short sentences, written to them "
            "rather than about them. Say plainly if what they asked for is something the rules "
            "do not allow, and ask them directly if you need something only they can tell you."
        )
    )
    needs_more_from_representative: bool = Field(
        default=False,
        description=(
            "True when your reply asks the representative a question you need answered before "
            "this can be settled."
        ),
    )


class RevisionConclusion(InvestigationConclusion, _RepliesToTheRepresentative):
    """A reworked conclusion, after a representative said what was wrong (FR-R.9, FR-R.10)."""

    model_config = ConfigDict(extra="forbid")

    representative_directed_outcome: bool = Field(
        default=False,
        description=(
            "True when the representative told you what to do about this claim and you are "
            "carrying out that instruction rather than recommending something of your own — "
            "'approve it', 'pay the two bottles', 'refund it'. Set it only alongside the "
            "recommendation and amount they asked for. If you cannot work out the amount or "
            "which product they mean, leave it false and ask them instead."
        ),
    )
    concerns_shared_evidence: bool = Field(
        default=False,
        description=(
            "True when the feedback is about the invoice, the customer confirmation or the "
            "photograph of the outer box, which every product on this claim shares."
        ),
    )


class SettledProduct(BaseModel):
    """One product a representative has told the agent this claim is for (FR-1a.4)."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(description="The product's name exactly as the order writes it.")
    quantity: int = Field(
        default=1, ge=1, description="How many of it the representative says were damaged."
    )
    sku: str | None = Field(default=None, description="The product's code from the order, or null.")


class RevisedClaimReport(_RepliesToTheRepresentative):
    """A reworked report about a whole claim rather than one product (FR-R.9, FR-R.10)."""

    model_config = ConfigDict(extra="forbid")

    ambiguity: str | None = Field(
        default=None,
        description=(
            "What is still unclear about this claim after what the representative said, in "
            "one or two short sentences. Null when nothing is unclear any more."
        ),
    )
    requested_details: tuple[str, ...] = Field(
        default=(),
        description=(
            "Every specific detail the merchant must still provide. Leave out anything the "
            "representative has just answered. Empty when nothing is needed from them."
        ),
    )
    email_subject: str | None = Field(
        default=None,
        description=(
            "Subject of the merchant email as it should now read. Null to leave the wording "
            "as it is, and null when nothing should be sent to the merchant at all."
        ),
    )
    email_body: str | None = Field(
        default=None,
        description=(
            "The merchant email as it should now read, requesting every remaining detail and "
            "nothing the representative has already answered. Never write an amount. Null to "
            "leave the wording as it is, and null when nothing should be sent."
        ),
    )
    settled_products: tuple[SettledProduct, ...] = Field(
        default=(),
        description=(
            "The products the representative has just told you this claim is for. Fill this in "
            "whenever they name one, however briefly — 'the 24oz multi surface cleaner is the "
            "one' settles it. Each becomes a claim line that is looked into and priced on its "
            "own. Empty when they have not said which products were damaged."
        ),
    )
    needs_fresh_investigation: bool = Field(
        default=False,
        description=(
            "True only when the representative asks for the whole claim to be investigated "
            "again. Naming a product is not that — put those in settled_products instead, "
            "which is far quicker and answers them directly."
        ),
    )
