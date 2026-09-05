"""The forms the AI fills in. It never replies with prose to be interpreted.

Every answer the model gives has a fixed shape with named fields, and a reply that
does not fit is rejected rather than patched up (NFR-2). This file is the whole
list of those shapes, kept in one place so that what the model is allowed to say
can be reviewed at a glance.

**There is exactly one money field, and it is deliberate.** The agent decides what the
damage is worth — `recommended_amount_usd` on the investigation's conclusion — because how
badly a thing is broken is a judgement and no rule could express it (FR-1.21). Everything
else about money stays out: no totals, no subtotals, no per-item prices, no shares.

That one field is **written as text**, not as a number, and that is not a stylistic
choice. A JSON number becomes a floating point value on the way in, where `0.10` cannot be
held exactly and cents drift. Text goes into an exact decimal untouched. Anything that is
not money — a symbol, a third decimal place, a word — is refused rather than interpreted,
and the claim goes to a person instead.

**No figure the model writes ever reaches a merchant.** The model drafts approval wording
without an amount. Code adds the amount *after* the cap has been applied, so what is sent is
the figure that survived the cap and not the one that was proposed. Any money-shaped text in
the model's wording is rejected. This is the guarantee that did not change when FR-1.21 was
reversed, and it is the one worth defending.

These shapes are deliberately separate from the ones in `claim_agent.domain`, even
where they look similar. What the model is permitted to assert is a narrower thing
than what a finished report holds: a report carries amounts, identifiers we
assigned, and the results of rules the model does not get a say in.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, model_validator

from claim_agent.domain.assessment import AssessmentName
from claim_agent.domain.evidence import EvidenceKind, EvidenceState
from claim_agent.domain.outcome import Recommendation

AMOUNT_PLACEHOLDER = "{{amount}}"
"""The marker used by approval drafts produced under the previous prompt.

New prompts tell the model to omit the amount; code appends the capped figure after
the answer. Keeping this marker lets those older drafts be finished without exposing
it to a representative (FR-1.21).
"""


class _WithoutSubjectiveConfidence(BaseModel):
    """Accept old stored/test values without advertising confidence to the model.

    Confidence used to be a required part of each structured answer. Removing it
    from the fields removes it from the JSON schema supplied to the model. Silently
    discarding the old key keeps replayed answers and rolling deployments readable.
    """

    @model_validator(mode="before")
    @classmethod
    def _discard_legacy_confidence(cls, value: object) -> object:
        if not isinstance(value, dict) or "confidence" not in value:
            return value
        without_confidence = dict(value)
        without_confidence.pop("confidence")
        return without_confidence


class ImageObservation(_WithoutSubjectiveConfidence):
    """What one image turned out to be, and whether it is any use (FR-1.4, FR-1.5).

    Filenames and file types are not offered to the model when it answers this,
    because they carry no signal: every sample attachment is a PNG or a JPEG
    whatever it shows, and two files in one sample case have nearly identical names
    and hold different kinds of evidence. Only what is visible in the image counts.

    `kind` is `None` when the image is none of the four kinds of evidence a claim
    needs — a photograph of a shipping label, say. That is a real answer, not a
    failure.

    `is_legible` false means the image cannot support a conclusion: too dark, too
    blurry, too cropped. `problem` then says which, in words a merchant could act
    on, because that sentence is what they will be asked to fix (FR-1.7).
    """

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
    """One product the investigation believes was damaged (FR-1a.1).

    `name` should be copied from the order's line items wherever the evidence
    supports it, because that is what ties the claim to a real product and to a
    price (FR-1a.2). A name that matches nothing on the order is still worth
    reporting — it is a finding, not an error.

    There is no price field here, and there is not going to be one.
    """

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
    """Which products a claim is for — the conclusion of the triage pass (FR-1a.1).

    `is_ambiguous` is the important field. Set it when it cannot be established
    which products are meant, and say what is unclear in `ambiguity`. Never resolve
    an ambiguity by choosing the likelier candidate.

    When the merchant can settle the ambiguity, `requested_details` names exactly
    what they must provide and the two email fields contain the wording to send them.
    An ambiguity only a representative can resolve leaves all three empty (FR-1a.4).

    An ambiguous split may still list the products it was choosing between. It must
    not present them as settled.
    """

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
    reasoning: str = Field(description="One or two short sentences explaining the split.")


class EvidenceJudgement(BaseModel):
    """The model's read on one of the four pieces of evidence (FR-1.5, FR-2.2).

    `attachment_id` has to name a real attachment on the case whenever the evidence
    is present, so that every finding is traceable to the exact image that produced
    it and a rep can look at the same photograph the system did.

    Note which states are available. `UNREADABLE` is not one the model may choose:
    it means *we* could not fetch or analyse an image, which is a fact about our own
    run rather than a judgement about the evidence, and it is set by the code that
    hit the failure.
    """

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
    """One of the four judgements, with the reasoning that makes it reviewable (FR-2.3).

    The reasoning is not decoration. A rep has to be able to disagree with this one
    judgement without discarding the other three, and they can only do that if they
    can see what it rested on.
    """

    model_config = ConfigDict(extra="forbid")

    name: AssessmentName = Field(description="Which of the four questions this answers.")
    passed: bool = Field(description="Your answer to it.")
    reasoning: str = Field(description="Why, in one or two plain sentences.")
    attachment_ids: tuple[str, ...] = Field(
        default=(), description="Ids of the images this judgement rests on."
    )


class DamagedItem(BaseModel):
    """A product this claim line should be reimbursed for, and how many of it.

    This is the field the money is worked out from, and it is the reason the model
    is asked for it: it says *what*, and a deterministic function turns that into
    *how much* (FR-1.21). Copy the name from the order's line items — ShipBob's
    payment endpoint identifies a product by its name as free text, so the exact
    wording matters (FR-3.3).

    There is no price field and no total field. There is nowhere here to put money.
    """

    model_config = ConfigDict(extra="forbid")

    product_name: str = Field(description="The product's name exactly as the order writes it.")
    quantity: int = Field(ge=1, description="How many of it were damaged.")
    sku: str | None = Field(default=None, description="The product's code, or null.")


class InvestigationConclusion(_WithoutSubjectiveConfidence):
    """The conclusion of one claim line's investigation — the model's whole answer.

    Everything a rep is shown about a claim line traces back to a field here, apart
    from the amount and the results of the rules, which code supplies.

    `recommendation` is the model's own choice of one of the three next actions
    (FR-1.14). Code may afterwards withhold a
    recommendation of payment that the requirements forbid, and can never move one
    towards paying; what was recommended here is kept either way, so a rep can see
    where the rules disagreed.

    `recommended_amount_usd` is the figure that goes with an `approve`, and
    `amount_reasoning` is why it is that figure. Both belong to the model now: the damage
    is what decides what putting it right is worth, and a fixed share of the price could
    not tell a scuffed box from a smashed bottle (FR-1.21). The cap is applied afterwards
    and is the only limit — a figure above it becomes the cap, and the report says so.

    `concerns` is where anything that does not fit goes: an ambiguity, a weak piece
    of evidence, a judgement that was close. Silence here is treated as a defect
    rather than a clean result, because a rep who cannot tell why the system is
    unsure will either rubber-stamp it or redo the work (FR-2.5).

    `requested_details` lists exactly what the merchant can supply for `request_info`.
    `email_subject` and `email_body` are the exact wording that would be sent to the
    merchant if a rep approved an approval or information request (FR-2.7), and the
    email must ask for each listed detail. Both email fields are null when representative
    clarification is needed. Approval wording carries no amount — the capped figure is
    added afterwards — and any money-shaped text the model writes is rejected.
    The words "draft", "unsent" and the like must not appear: that the email is a draft
    is recorded beside it, not inside it, so no such marker can ever reach a merchant
    (FR-1.17).

    `corrections_considered` names the earlier cases whose rep corrections actually
    influenced this conclusion, so a report can say which past correction changed
    what (FR-2.6). Leave it empty when none did.
    """

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


class RevisionConclusion(InvestigationConclusion):
    """A reworked conclusion, after a representative said what was wrong (FR-R.9, FR-R.10).

    **This is the investigation's own form with three fields added, and that is the point.**
    FR-R.9 asks for a full report in the same structure as the first one — same schema, same
    requirements — rather than a patch, so this inherits every field instead of restating them.
    A rule that binds a first answer therefore binds a reworked one, and the two cannot drift.

    Everything inherited means exactly what it meant the first time: report on all four pieces
    of evidence, answer the four questions when the evidence is there, name what should be paid
    for, choose one of the three next actions, and write the merchant's email — carrying the
    parts the representative did not dispute forward unchanged (FR-R.5). Code fills any part
    left out from the earlier report, so leaving one out cannot quietly turn an established
    finding into a missing one.

    `changed` and `left_unchanged` are what let a representative confirm they were understood
    without re-reading the whole report (FR-R.10). `reply_to_representative` is the answer to
    what they actually said — including a refusal, where they asked for something the rules
    forbid (FR-R.8), and including a question, where the rework cannot be settled without
    something only they can supply.

    `needs_more_from_representative` says that the reply contains such a question. It changes
    nothing about the recommendation; it tells a screen that the conversation is waiting on a
    person rather than finished.

    `concerns_shared_evidence` says the feedback was about the invoice, the customer
    confirmation or the photograph of the outer box — the three that describe the parcel and
    are settled once for the whole claim (FR-1a.3). Correcting one of those ought to correct
    every product on the claim; this system flags that and does not do it (FR-R.1a).
    """

    model_config = ConfigDict(extra="forbid")

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
    concerns_shared_evidence: bool = Field(
        default=False,
        description=(
            "True when the feedback is about the invoice, the customer confirmation or the "
            "photograph of the outer box, which every product on this claim shares."
        ),
    )
