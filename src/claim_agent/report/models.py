"""What a report is: a few facts a screen needs, and the document a person reads.

A **report** is what one representative decides on. There is one for each damaged product on a
claim, and one for a claim the quick checks turned away before it ever had products in it
(FR-2.1, FR-0.4, FR-C.1).

Almost everything a representative reads lives in `markdown`, written by
`claim_agent.report.render`. The handful of fields beside it are the ones the system itself has to
work with rather than read: the list of a claim's reports draws a row from them, and the record of
what somebody decided compares against them. Anything a person needs and a machine does not is in
the writing.

Nothing here reads a clock, talks to anything, or judges a claim.
"""

from __future__ import annotations

from decimal import Decimal
from enum import StrEnum
from typing import Self

from pydantic import BaseModel, ConfigDict, model_validator

from claim_agent.domain.assessment import Confidence
from claim_agent.domain.decision import DecisionStage, Proposal
from claim_agent.domain.models import DraftedEmail, UtcDatetime
from claim_agent.domain.outcome import Recommendation


class ReportState(StrEnum):
    """Where a report has got to in its review (FR-2.8, FR-2.9).

    `AWAITING_REVIEW` is a report nobody has acted on yet.

    `CHANGES_REQUESTED` is one a representative sent back with a note. It is a resting place
    rather than a stage: the part of the system that would rework a report around that note is
    not built, so nothing picks one up. A representative can still approve it.

    `APPROVED` is final. A report leaves the review in exactly one way and this is it — there is
    no time limit, no level of confidence and no number of rounds that reaches it instead
    (FR-2.9). Once here a report cannot be reopened, sent back, or approved again differently.
    """

    AWAITING_REVIEW = "awaiting_review"
    CHANGES_REQUESTED = "changes_requested"
    APPROVED = "approved"


class SiblingLine(BaseModel):
    """One of the *other* damaged products on the same claim, as a single row (FR-2.9a).

    A representative approving one product should be able to see that the second is still waiting
    on a photograph, without opening it.

    **Never stored inside a report.** `state` changes the moment somebody approves that other
    product, and a report carrying a copy of it would say "waiting" beside something approved ten
    minutes ago. These are looked up fresh each time a report is read.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    claim_line_id: str
    product_name: str
    recommendation: Recommendation | None
    amount_usd: Decimal | None
    state: ReportState


class Report(BaseModel):
    """One report: what a representative reads, plus the few facts a screen has to work with.

    Frozen, because a report is the account of something that has already happened. The one thing
    about it that changes is where its review has got to, and that is done by making a new copy
    rather than by editing this one — the same way a past claim is withdrawn.

    Fields:
        report_id: Names this report for as long as it exists, across every version of it.
        version: Which version this is. Only reworking a report after feedback makes a second
            one, and that stage is not built, so every report today is version 1 (FR-R.13).
        case_id: The claim this belongs to (FR-2.9a).
        product_name: The damaged product's name. `None` on a claim the quick checks stopped,
            which has no product in it. Kept beside the report because the row shown for one
            product beside another has to name it, and a report's own words are prose (FR-2.9a).
        claim_line_id: The one damaged product this is about. **`None` names the whole claim**,
            which is what a claim the quick checks stopped gets: splitting a claim into products
            happens later and a stopped claim never gets there (FR-C.1).
        user_id: The merchant, by the identifier that stays the same between claims (FR-3.8).
        stage: Which part of the system produced this — the quick checks, or the investigation.
            The same words the record of a decision uses, deliberately one list rather than two
            that could drift apart.
        state: Where the review has got to.
        recommendation: What the system advised. **`None` on a stopped claim**, which has no
            damaged product for the four recommendations to be about; its reasons are what it has
            to say instead.
        amount_usd: What the system advised paying, or `None` where nothing would be paid.
        confidence: How sure the investigation said it was of its own recommendation, from 0 to 1.
            `None` on a stopped claim, where nothing was asked of the AI, and on a run that never
            reached a conclusion — which must not be read as low confidence.
        carrier: Who carried the parcel, as ShipBob names them. `None` when the shipment could
            not be read.
        defect_type: What the merchant said was wrong, in ShipBob's own wording, read out of the
            case description. `None` when the description did not say — which is not the same as
            nothing being wrong.
        damage_type: How the merchant said it happened, on the same terms as `defect_type`.

            Both are kept because they are among the few things about a claim known *before*
            anybody looks at it, which is what makes them worth grouping decisions by. They are
            what the *merchant* said, never checked against anything, and this report does not
            weigh them.
        order_value_usd: What the order was worth. Kept beside the report because the record of
            what a representative decided groups decisions by value, and the claim's context is
            written into the report's words rather than held as fields (FR-C.7). `None` when the
            order could not be read, which is not an order worth nothing.
        decided: What the representative settled on, once they have approved. `None` until then.
            Kept beside what was advised so a report approved at a different figure does not show
            the old one next to the word "approved" (FR-2.1).
        decisions_taken: How many review actions have been taken on this report. It is what keeps
            two different notes sent back on the same report from being recorded as one (FR-C.1).
        drafted_email: The merchant's email, exactly as the report's own words show it. Kept as
            a field as well because a representative rewords it before approving, and pulling it
            back out of the writing would be the screen reading prose for data (FR-2.7, FR-2.8).
            `None` when there is nothing to send.
        markdown: The report itself, in the words a representative reads.
        created_at: When this version was written.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    report_id: str
    version: int
    case_id: str
    claim_line_id: str | None
    product_name: str | None
    user_id: str | None
    stage: DecisionStage
    state: ReportState
    recommendation: Recommendation | None
    amount_usd: Decimal | None
    confidence: Confidence | None
    carrier: str | None
    defect_type: str | None
    damage_type: str | None
    order_value_usd: Decimal | None
    decided: Proposal | None
    decisions_taken: int
    drafted_email: DraftedEmail | None
    markdown: str
    created_at: UtcDatetime

    @model_validator(mode="after")
    def _must_not_exist_in_a_state_nothing_could_read(self) -> Self:
        """Refuse a report that a representative or a later stage could not make sense of.

        Every one of these is a mistake in our own code rather than anything a merchant or
        ShipBob did, so each stops here instead of travelling on and being discovered later:

        - **A stopped claim recommending something.** The four recommendations are about a
          damaged product and a stopped claim has none, so a recommendation or an amount here
          would be an answer nobody gave.
        - **An investigated product with no product named.** Every investigation is about one
          claim line, and one without an id cannot be told apart from a whole claim.
        - **A figure attached to a report nobody approved.** What a representative settled on
          only exists once they have settled on it.
        - **A version below one, or a count of decisions below nothing.** Neither is reachable by
          counting upwards from a report being written.

        Raises `ValueError`, which pydantic reports as a validation error.
        """
        if self.stage is DecisionStage.SCREENING:
            if self.claim_line_id is not None:
                raise ValueError("A claim stopped by the quick checks has no damaged product.")
            if self.recommendation is not None or self.amount_usd is not None:
                raise ValueError("A claim stopped by the quick checks recommends nothing.")
            if self.product_name is not None:
                raise ValueError("A claim stopped by the quick checks names no product.")
        elif self.claim_line_id is None or self.product_name is None:
            raise ValueError("An investigated report has to name the product it is about.")

        if self.decided is not None and self.state is not ReportState.APPROVED:
            raise ValueError("Only an approved report says what the representative settled on.")

        if self.version < 1:
            raise ValueError("A report's first version is 1.")
        if self.decisions_taken < 0:
            raise ValueError("A report cannot have had fewer than no decisions taken on it.")
        return self


class ClaimView(BaseModel):
    """Every report on one claim, so a representative works from a case rather than a list of
    disconnected products (FR-2.9b).

    A view over the reports and nothing more. It decides nothing of its own: approving still
    happens one product at a time, on the report itself.

    `reports` is empty for a claim nobody has asked about yet. That is an ordinary answer, and it
    is not the same as a claim whose reports could not be read — that fails loudly instead.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    case_id: str
    reports: tuple[Report, ...] = ()


class EmailWording(BaseModel):
    """The merchant's email as a representative reworded it (FR-2.8).

    Subject and wording only. **Who hears about a claim is not a representative's to change** —
    the recipient comes from the claim's own contact address — so there is nowhere here to put
    one.

    Rewording is for how an email reads. Changing what it *tells* a merchant is substance, and
    FR-2.8 draws that line by sending substance back as feedback instead.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    subject: str
    body: str


class ReportForReview(BaseModel):
    """One report, and the other damaged products on the same claim beside it (FR-2.9a).

    `siblings` is looked up when the report is read rather than kept inside it, because a
    sibling's review state changes the moment somebody approves it. A copy stored alongside the
    report would say "waiting" next to a product approved ten minutes ago.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    report: Report
    siblings: tuple[SiblingLine, ...] = ()
