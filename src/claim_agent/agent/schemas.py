"""The forms the AI fills in. It never replies with prose to be interpreted.

Every answer the model gives has a fixed shape with named fields, and a reply that
does not fit is rejected rather than patched up (NFR-2). This file is the whole
list of those shapes, kept in one place so that what the model is allowed to say
can be reviewed at a glance.

**Read this before adding a field: nothing here may carry an amount of money.**
Not a total, not a price, not a subtotal, not a percentage of one. The model says
*what* was damaged; a deterministic function in `claim_agent.domain.reimbursement`
says *how much* (FR-1.21). That is enforced by there being nowhere to put a figure
rather than by asking the model not to give one — a schema with no money field
cannot leak money, whatever the model does. A test fails if a field of type
`Decimal`, or a field whose name reads like an amount, is added here.

The one number these forms do carry is confidence, which is a fraction between
zero and one and is not money.

The email fields are the other place to be careful. The model writes the wording,
because it can speak to the actual claim, but it writes `{{amount}}` where a figure
belongs and code substitutes the real one afterwards. Any other money-shaped text
anywhere in what it wrote is rejected (FR-1.21).

These shapes are deliberately separate from the ones in `claim_agent.domain`, even
where they look similar. What the model is permitted to assert is a narrower thing
than what a finished report holds: a report carries amounts, identifiers we
assigned, and the results of rules the model does not get a say in.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from claim_agent.domain.assessment import AssessmentName, Confidence
from claim_agent.domain.evidence import EvidenceKind, EvidenceState
from claim_agent.domain.outcome import Recommendation

AMOUNT_PLACEHOLDER = "{{amount}}"
"""Where the model writes a figure it is not allowed to know.

The email wording is the model's, every number in it is ours. The model puts this
marker where the amount belongs and code replaces it with the figure the
arithmetic produced (FR-1.21). A drafted email that still contains the marker
after substitution, or that contains money written any other way, is refused.
"""


class ImageObservation(BaseModel):
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
    confidence: Confidence = Field(description="How sure you are, from 0 to 1.")


class ClaimedProductProposal(BaseModel):
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
    confidence: Confidence = Field(description="How sure you are, from 0 to 1.")


class ClaimSplit(BaseModel):
    """Which products a claim is for — the conclusion of the triage pass (FR-1a.1).

    `is_ambiguous` is the important field. Set it when it cannot be established
    which products are meant, and say what is unclear in `ambiguity`: a rep told
    "the photos show a damaged 24oz bottle, but the order has two different 24oz
    bottles at different prices" settles that in seconds, whereas a wrong split is
    silent and expensive (FR-1a.4). Never resolve an ambiguity by choosing the
    likelier candidate.

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
        description="What exactly is unclear, and what would resolve it. Null if nothing is.",
    )
    reasoning: str = Field(description="How you reached this split.")
    confidence: Confidence = Field(description="How sure you are of the split, from 0 to 1.")


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


class AssessmentJudgement(BaseModel):
    """One of the four judgements, with the reasoning that makes it reviewable (FR-2.3).

    The reasoning is not decoration. A rep has to be able to disagree with this one
    judgement without discarding the other three, and they can only do that if they
    can see what it rested on.
    """

    model_config = ConfigDict(extra="forbid")

    name: AssessmentName = Field(description="Which of the four questions this answers.")
    passed: bool = Field(description="Your answer to it.")
    reasoning: str = Field(description="Why, in one or two plain sentences.")
    confidence: Confidence = Field(description="How sure you are, from 0 to 1.")
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


class InvestigationConclusion(BaseModel):
    """The conclusion of one claim line's investigation — the model's whole answer.

    Everything a rep is shown about a claim line traces back to a field here, apart
    from the amount and the results of the rules, which code supplies.

    `recommendation` is the model's own choice of one of the four outcomes
    (FR-1.14), including refusing a claim. Code may afterwards withhold a
    recommendation of payment that the requirements forbid, and can never move one
    towards paying; what was recommended here is kept either way, so a rep can see
    where the rules disagreed.

    `concerns` is where anything that does not fit goes: an ambiguity, a weak piece
    of evidence, a judgement that was close. Silence here is treated as a defect
    rather than a clean result, because a rep who cannot tell why the system is
    unsure will either rubber-stamp it or redo the work (FR-2.5).

    `email_subject` and `email_body` are the exact wording that would be sent to
    the merchant if a rep approved it (FR-2.7). Write `{{amount}}` where a figure
    belongs and nowhere else — the figure is substituted afterwards, and any other
    money-shaped text is rejected. The words "draft", "unsent" and the like must
    not appear: that the email is a draft is recorded beside it, not inside it, so
    no such marker can ever reach a merchant (FR-1.17).

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
        default=None, description="What is unclear and what would resolve it, or null."
    )
    recommendation: Recommendation = Field(description="What you recommend doing about this line.")
    reasoning: str = Field(description="Why you recommend it.")
    concerns: tuple[str, ...] = Field(
        default=(),
        description="Anything weak, conflicting or uncertain a reviewer should know.",
    )
    confidence: Confidence = Field(
        description="How sure you are of this recommendation overall, from 0 to 1."
    )
    corrections_considered: tuple[str, ...] = Field(
        default=(),
        description="Case ids of past rep corrections that changed your conclusion.",
    )
    email_subject: str = Field(description="Subject line of the email to the merchant.")
    email_body: str = Field(
        description=(
            "The email to the merchant, in the exact wording that would be sent. "
            "Write {{amount}} where a figure belongs; never write a figure yourself."
        )
    )
