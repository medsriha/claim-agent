from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from tests.unit.test_report_models import a_report, a_screening_report

from claim_agent.domain.decision import DecisionStage, RepAction
from claim_agent.domain.models import DraftedEmail
from claim_agent.domain.outcome import Recommendation
from claim_agent.errors import ConflictError
from claim_agent.policy import Policy
from claim_agent.report.models import EmailWording, ReportState
from claim_agent.report.review import approve, send_back

A_MOMENT = datetime(2026, 3, 21, 10, 4, 11, tzinfo=UTC)
POLICY = Policy()

A_REWORDING = EmailWording(
    subject="About your claim",
    body="We are refunding you for the damaged collagen.",
)


# --- Approving as it stands (FR-2.8, FR-2.9, FR-C.1) -------------------------


def test_approving_a_report_leaves_it_approved() -> None:
    """FR-2.9: a report leaves the review in exactly one way, and this is it."""
    outcome = approve(a_report(), policy=POLICY, at=A_MOMENT)

    assert outcome.report.state is ReportState.APPROVED


def test_approving_records_what_the_representative_chose() -> None:
    """FR-C.1: every review action produces one durable record of what a person chose."""
    outcome = approve(a_report(), policy=POLICY, at=A_MOMENT)

    assert outcome.decision is not None
    assert outcome.decision.action is RepAction.APPROVED
    assert outcome.decision.case_id == "CASE-1001"
    assert outcome.decision.case_id == "CASE-1001"
    assert outcome.decision.report_version == 1
    assert outcome.decision.decided_at == A_MOMENT


def test_the_record_cannot_say_who_decided_and_says_so_rather_than_guessing() -> None:
    """FR-C.1: a record that silently has no author is worse than one that says it has none."""
    outcome = approve(a_report(), policy=POLICY, at=A_MOMENT)

    assert outcome.decision is not None
    assert outcome.decision.decided_by is None


def test_the_record_keeps_how_sure_the_investigation_said_it_was() -> None:
    """FR-C.1: nothing has ever checked that claim, and this is what makes checking possible."""
    outcome = approve(a_report(confidence=0.82), policy=POLICY, at=A_MOMENT)

    assert outcome.decision is not None
    assert outcome.decision.stated_confidence == 0.82


def test_a_stopped_claim_can_be_approved_and_names_the_whole_claim() -> None:
    """FR-C.1: a stopped claim has no products, so its decision names the claim instead."""
    outcome = approve(a_screening_report(), policy=POLICY, at=A_MOMENT)

    assert outcome.decision is not None
    assert outcome.decision.case_id == "CASE-1004"
    assert outcome.decision.stage is DecisionStage.SCREENING
    assert outcome.decision.decision_id == "DEC-CASE-1004-00"


# --- Approving after changing something (FR-2.8, FR-2.1) ---------------------


def test_approving_at_a_different_figure_is_recorded_as_an_override() -> None:
    """FR-C.2: a correction is worth remembering when the decision differs from the advice."""
    outcome = approve(a_report(), decided_amount_usd=Decimal("31.20"), policy=POLICY, at=A_MOMENT)

    assert outcome.decision is not None
    assert outcome.decision.action is RepAction.APPROVED_WITH_OVERRIDE
    assert outcome.decision.amount_changed
    assert not outcome.decision.outcome_changed


def test_approving_a_different_outcome_is_recorded_as_an_override() -> None:
    """FR-C.2: not "the wording was clumsy" but "the answer was wrong"."""
    outcome = approve(
        a_report(),
        decided_outcome=Recommendation.REQUEST_REP_CLARIFICATION,
        policy=POLICY,
        at=A_MOMENT,
    )

    assert outcome.decision is not None
    assert outcome.decision.action is RepAction.APPROVED_WITH_OVERRIDE
    assert outcome.decision.outcome_changed


def test_what_was_settled_on_is_kept_beside_what_was_advised() -> None:
    """FR-2.1: a report approved at a different figure must not show only the old one."""
    outcome = approve(a_report(), decided_amount_usd=Decimal("31.20"), policy=POLICY, at=A_MOMENT)

    assert outcome.report.amount_usd == Decimal("52.00")
    assert outcome.report.decided is not None
    assert outcome.report.decided.amount_usd == Decimal("31.20")
    assert outcome.report.reviews[-1].decided.amount_usd == Decimal("31.20")


def test_rewording_the_email_is_a_flag_on_the_approval_rather_than_an_action_of_its_own() -> None:
    """FR-2.8: direct edits are for wording, and are done before approving rather than instead."""
    outcome = approve(a_report(), edited_email=A_REWORDING, policy=POLICY, at=A_MOMENT)

    assert outcome.decision is not None
    assert outcome.decision.action is RepAction.APPROVED
    assert outcome.decision.email_edited
    assert outcome.report.drafted_email is not None
    assert outcome.report.drafted_email.body == f"{A_REWORDING.body}\n\nApproved amount: $52.00"
    assert outcome.report.reviews[-1].edited_email == A_REWORDING


def test_the_report_keeps_everything_it_said_before_the_decision() -> None:
    """NFR-3: what the system said and what a person then decided stay told apart."""
    report = a_report()

    outcome = approve(report, decided_amount_usd=Decimal("31.20"), policy=POLICY, at=A_MOMENT)

    assert outcome.report.content == report.content
    assert outcome.report.reviews[-1].review_number == 1


# --- A figure over the cap (FR-1.20, FR-R.8, FR-C.4) -------------------------


def test_a_figure_over_the_cap_is_accepted_and_recorded() -> None:
    """FR-C.4: losing the decision a person made is worse than recording one somebody may query."""
    outcome = approve(a_report(), decided_amount_usd=Decimal("150.00"), policy=POLICY, at=A_MOMENT)

    assert outcome.report.state is ReportState.APPROVED
    assert outcome.report.decided is not None
    assert outcome.report.decided.amount_usd == Decimal("150.00")


def test_a_figure_over_the_cap_is_flagged_in_the_report() -> None:
    """FR-R.8: say so plainly rather than silently complying or silently ignoring it."""
    outcome = approve(a_report(), decided_amount_usd=Decimal("150.00"), policy=POLICY, at=A_MOMENT)

    assert outcome.report.reviews[-1].over_the_cap_by == Decimal("50.00")


def test_a_figure_within_the_cap_is_not_flagged() -> None:
    """FR-1.20: a note about a limit nobody crossed is noise in front of the findings."""
    outcome = approve(a_report(), policy=POLICY, at=A_MOMENT)

    assert outcome.report.reviews[-1].over_the_cap_by is None


# --- Approving twice (FR-C.4, FR-3.5) ----------------------------------------


def test_approving_the_same_report_the_same_way_twice_leaves_one_decision() -> None:
    """FR-3.5: a double-click or a retry after a slow reply must not count as two decisions."""
    once = approve(a_report(), policy=POLICY, at=A_MOMENT)
    twice = approve(once.report, policy=POLICY, at=A_MOMENT)

    assert twice.decision is None
    assert twice.report == once.report
    assert twice.report.decisions_taken == 1


def test_approving_an_approved_report_differently_is_refused() -> None:
    """FR-2.9: a decision a person took is not something a later request may quietly replace."""
    approved = approve(a_report(), policy=POLICY, at=A_MOMENT).report

    with pytest.raises(ConflictError) as refused:
        approve(approved, decided_amount_usd=Decimal("31.20"), policy=POLICY, at=A_MOMENT)

    assert refused.value.status_code == 409
    assert refused.value.code == "conflict"


def test_rewording_the_email_after_approval_is_refused() -> None:
    """FR-2.7: the wording is what was approved, so changing it changes what was agreed."""
    approved = approve(a_report(), policy=POLICY, at=A_MOMENT).report

    with pytest.raises(ConflictError):
        approve(approved, edited_email=A_REWORDING, policy=POLICY, at=A_MOMENT)


# --- Sending a report back (FR-2.8, FR-R.1) ----------------------------------


def test_sending_a_report_back_parks_it_and_records_the_note() -> None:
    """FR-2.8: the rep describes what is wrong in their own words, and it is kept as written."""
    outcome = send_back(a_report(), feedback="The packaging photo is the box.", at=A_MOMENT)

    assert outcome.report.state is ReportState.CHANGES_REQUESTED
    assert outcome.decision is not None
    assert outcome.decision.action is RepAction.SENT_BACK
    assert outcome.decision.rep_words == "The packaging photo is the box."


def test_sending_a_report_back_settles_no_figure() -> None:
    """FR-R.1: nothing was chosen, so what was decided is still what was advised."""
    outcome = send_back(a_report(), feedback="Look again.", at=A_MOMENT)

    assert outcome.report.decided is None
    assert outcome.decision is not None
    assert not outcome.decision.amount_changed
    assert not outcome.decision.agreed_with_recommendation


def test_two_different_notes_on_one_report_are_two_decisions() -> None:
    """FR-C.1: a rep who says one thing and then another has decided twice, and both are kept."""
    once = send_back(a_report(), feedback="The packaging photo is the box.", at=A_MOMENT)
    twice = send_back(once.report, feedback="And the invoice is the wrong order.", at=A_MOMENT)

    assert once.decision is not None
    assert twice.decision is not None
    assert once.decision.decision_id != twice.decision.decision_id
    assert twice.report.decisions_taken == 2


def test_a_report_sent_back_can_still_be_approved() -> None:
    """FR-2.9: a case may cycle through revision any number of times and still needs a person."""
    parked = send_back(a_report(), feedback="Look again.", at=A_MOMENT).report

    outcome = approve(parked, policy=POLICY, at=A_MOMENT)

    assert outcome.report.state is ReportState.APPROVED
    assert outcome.decision is not None
    assert outcome.decision.decision_id.endswith("-01")


def test_an_approved_report_cannot_be_sent_back() -> None:
    """FR-2.9, FR-3.1: un-approving would undo something that releases execution."""
    approved = approve(a_report(), policy=POLICY, at=A_MOMENT).report

    with pytest.raises(ConflictError) as refused:
        send_back(approved, feedback="Actually, no.", at=A_MOMENT)

    assert refused.value.status_code == 409


# --- Nothing here decides on its own (FR-2.9) --------------------------------


def test_nothing_approves_a_report_except_approving_it() -> None:
    """FR-2.9: no time limit, no level of confidence, and no number of rounds reaches approved."""
    report = a_report(confidence=1.0)

    parked = send_back(report, feedback="One.", at=A_MOMENT).report
    parked = send_back(parked, feedback="Two.", at=A_MOMENT).report
    parked = send_back(parked, feedback="Three.", at=A_MOMENT).report

    assert parked.state is ReportState.CHANGES_REQUESTED


def test_deciding_the_same_way_twice_produces_the_same_record() -> None:
    """NFR-1: a record that changes when nothing changed is one nobody can rely on."""
    first = approve(a_report(), policy=POLICY, at=A_MOMENT)
    second = approve(a_report(), policy=POLICY, at=A_MOMENT)

    assert first == second


def test_each_round_of_review_is_numbered_in_the_report() -> None:
    """NFR-5: three identical headings say nothing about the order they happened in."""
    parked = send_back(a_report(), feedback="One.", at=A_MOMENT).report
    parked = send_back(parked, feedback="Two.", at=A_MOMENT).report
    approved = approve(parked, policy=POLICY, at=A_MOMENT).report

    assert [review.review_number for review in approved.reviews] == [1, 2, 3]


def test_a_rewording_replaces_the_wording_and_never_the_recipient() -> None:
    """FR-3.2: who hears about a claim comes from the claim, not from whoever reviews it."""
    outcome = approve(a_report(), edited_email=A_REWORDING, policy=POLICY, at=A_MOMENT)

    assert outcome.report.drafted_email is not None
    assert outcome.report.drafted_email.body == f"{A_REWORDING.body}\n\nApproved amount: $52.00"
    assert outcome.report.drafted_email.subject == A_REWORDING.subject
    assert outcome.report.drafted_email.to == "merchant@example.test"


def test_changing_the_approved_amount_updates_the_email_amount() -> None:
    """The merchant email must communicate the amount the representative actually approves."""
    report = a_report(
        drafted_email=DraftedEmail(
            to="merchant@example.test",
            subject="About your claim",
            body="Your claim is approved.\n\nApproved amount: $52.00",
        )
    )

    outcome = approve(
        report,
        decided_amount_usd=Decimal("31.20"),
        policy=POLICY,
        at=A_MOMENT,
    )

    assert outcome.report.drafted_email is not None
    assert "$31.20" in outcome.report.drafted_email.body
    assert "$52.00" not in outcome.report.drafted_email.body


def test_a_report_with_nothing_to_send_stays_with_nothing_to_send() -> None:
    """FR-2.7: a rep-clarification report cannot gain a merchant email during review."""
    outcome = approve(
        a_report(
            recommendation=Recommendation.REQUEST_REP_CLARIFICATION,
            amount_usd=None,
            drafted_email=None,
        ),
        edited_email=A_REWORDING,
        policy=POLICY,
        at=A_MOMENT,
    )

    assert outcome.report.drafted_email is None
