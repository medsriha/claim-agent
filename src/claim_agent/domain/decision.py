from __future__ import annotations

from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, ConfigDict

from claim_agent.domain.assessment import Confidence
from claim_agent.domain.models import UtcDatetime
from claim_agent.domain.outcome import Recommendation


class DecisionStage(StrEnum):
    """Which part of the system produced the thing the representative was looking at.

    `SCREENING` is a claim the four quick checks turned away (FR-0.4). It has no products in it,
    because splitting a claim into products happens later and a stopped claim never gets there.
    Nothing was asked of the AI, so there is no statement of how sure anything was.

    `INVESTIGATION` is a claim that was investigated (FR-1b.1). It carries a recommendation
    from the AI, covering every damaged product on the claim.

    The two answer different questions about automation and are always reported apart.
    """

    SCREENING = "screening"
    INVESTIGATION = "investigation"


class RepAction(StrEnum):
    """Which of the three review actions the representative took (FR-2.8).

    `APPROVED` means the report and its email were accepted as they stood.

    `APPROVED_WITH_OVERRIDE` means they were accepted, but the representative changed the
    outcome or the amount first. This is the wording FR-C.1's own reference record uses.

    `SENT_BACK` means the report went back with feedback in the representative's words, so the
    investigation runs again over what they said (FR-R.1).

    There is deliberately no fourth value for editing the email. FR-2.8 lists three actions, and
    reads the third — changing the wording — as something done *before* approving rather than
    instead of it. So an edit is recorded as a flag on the approval, not as an action of its own.
    """

    APPROVED = "approved"
    APPROVED_WITH_OVERRIDE = "approved_with_override"
    SENT_BACK = "sent_back"


class Proposal(BaseModel):
    """One side of the comparison: an outcome and an amount, either advised or chosen.

    The same shape describes what the system recommended and what the representative settled on,
    so the two can be compared field by field. FR-C.2 asks for exactly that comparison — a
    correction is worth remembering when the decision *differs* from the advice, not when
    somebody wrote a paragraph about it.

    `outcome` is `None` on a screening decision, where nothing was established as damaged and
    therefore nothing for the next actions to apply to.

    `amount_usd` is `None` whenever no money is involved, which includes every screening
    decision and every investigated claim that was refused or sent back for more information.
    None means "no amount", never "nothing".
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    outcome: Recommendation | None
    amount_usd: Decimal | None


class DecisionRecord(BaseModel):
    """One review action by one representative, on one claim (FR-C.1).

    The fields follow the record FR-C.1 describes. Four go beyond it, and they are here because
    the figures this store exists to produce cannot be worked out without them:

    - `stage` separates the two populations described in this module's opening.
    - `stated_confidence` is how sure the investigation said it was, kept beside the decision so
      that claim can be checked against what the representative then did. Nothing in this system
      has ever checked it, which is the single most useful thing this store makes possible.
    - `order_value_usd` is what the order was worth, so decisions can be grouped by value. FR-C.7
      asks whether an expensive claim should be held to a stricter standard and leaves the
      question open; grouping by value is how somebody would answer it.
    - `rep_minutes` is how long the review took, in whole minutes, which is the only way to say
      whether any of this saves anyone time. Whole minutes because the figure ends up multiplied
      by an hourly rate, and no amount of money in this system is allowed to come from a float.
    - `defect_type`, `damage_type` and `carrier` are what the merchant said happened and who
      carried the parcel. ShipBob puts the first two in the case description in a fixed form —
      "Damage Type: Damage due to carrier mishandling. Defect Type: Product damaged, but shipping
      box is intact." — and the third is on the shipment. They are kept as ShipBob words them,
      never reworded, and they are here because they are the only things about a claim that are
      known *before* anybody looks at it. Everything else worth grouping by — how sure the system
      was, what it recommended — is something the investigation produced, so grouping by it can
      only describe work already done rather than work about to arrive.

    **Those last three are copied from the report rather than looked up.** There is no store of
    reports to look them up in — that is a gap listed in DESIGN.md, not an oversight here. Copying
    them means a decision can be read without reassembling the claim it came from, and it means a
    figure here could in principle disagree with a report. There is no report to disagree with
    yet, and when there is one, this is the join that has to be built.

    `decided_by` is always empty. There is no sign-in anywhere in this system, so the record
    cannot say which representative decided. FR-C.1 is explicit that the field must exist and be
    left empty rather than filled with a guess: a record that silently has no author is worse
    than one that plainly says it does not know.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    decision_id: str
    case_id: str
    stage: DecisionStage
    report_version: int
    action: RepAction
    recommended: Proposal
    decided: Proposal
    email_edited: bool
    stated_confidence: Confidence | None
    order_value_usd: Decimal | None
    defect_type: str | None
    damage_type: str | None
    carrier: str | None
    rep_minutes: int
    rep_words: str | None
    decided_by: str | None
    decided_at: UtcDatetime

    @property
    def outcome_changed(self) -> bool:
        """Whether the representative settled on a different outcome from the one advised.

        This is the serious kind of disagreement: not "the wording was clumsy" but "the answer
        was wrong". A screening decision always reports false, because it has no outcome on
        either side to compare.
        """
        if self.recommended.outcome is None or self.decided.outcome is None:
            return False
        return self.recommended.outcome != self.decided.outcome

    @property
    def amount_changed(self) -> bool:
        """Whether the representative paid a different amount from the one worked out.

        Read this next to `outcome_changed`: the two together separate "the judgement was wrong"
        from "the judgement was right and something it was given was wrong". An amount that was
        absent on one side and present on the other counts as changed, because it is.
        """
        return self.recommended.amount_usd != self.decided.amount_usd

    @property
    def is_direct_approval(self) -> bool:
        """Whether this went out exactly as the system produced it, untouched.

        The strictest reading, on purpose: approved, same outcome, same amount, and not a word of
        the email rewritten. Anything else took a person's attention, which is the thing being
        measured. A rewritten email is not a disagreement — FR-2.8 treats wording and substance
        differently — but it is still work somebody had to do, so it does not count as direct.
        """
        return (
            self.action is RepAction.APPROVED
            and not self.outcome_changed
            and not self.amount_changed
            and not self.email_edited
        )

    @property
    def agreed_with_recommendation(self) -> bool:
        """Whether the representative accepted the advice on substance, however they worded it.

        Substance means the outcome and the amount. A rewritten email still counts as agreement,
        and so does an approval of a report nobody changed. Sending a report back does not: it
        says the report was not usable as it arrived.

        This is what the confidence comparison is measured against, and it is deliberately the
        looser of the two tests. Whether somebody tidied the prose says nothing about whether the
        system reached the right answer.
        """
        return self.action is not RepAction.SENT_BACK and not (
            self.outcome_changed or self.amount_changed
        )
