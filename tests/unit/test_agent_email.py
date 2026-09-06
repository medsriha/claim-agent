from __future__ import annotations

from decimal import Decimal

import pytest

from claim_agent.agent.email import (
    MISSING_EVIDENCE_WORDING,
    draft_markers_the_model_wrote,
    finish_email,
    money_the_model_wrote,
    name_what_is_missing,
)
from claim_agent.agent.schemas import InvestigationConclusion
from claim_agent.domain.evidence import REQUIRED_EVIDENCE, EvidenceFinding, EvidenceKind
from claim_agent.domain.evidence import EvidenceState as State
from claim_agent.domain.outcome import Recommendation
from claim_agent.domain.reimbursement import AmountComponent, AmountDerivation
from claim_agent.errors import ModelOutputRejectedError


def a_conclusion(
    *,
    subject: str = "Your claim CASE-1005",
    body: str = "Hi there,\n\nWe have looked at your claim.\n\nThanks,\nShipBob Support",
    recommendation: Recommendation = Recommendation.APPROVE,
) -> InvestigationConclusion:
    return InvestigationConclusion(
        evidence=(),
        recommendation=recommendation,
        reasoning="The photographs show the damage described.",
        email_subject=subject,
        email_body=body,
    )


def an_amount(usd: str) -> AmountDerivation:
    return AmountDerivation(
        components=(
            AmountComponent(
                product_name="Liposomal Tripeptide Collagen",
                quantity=1,
                unit_price=Decimal(usd),
                sku="0180",
            ),
        ),
        items_total_usd=Decimal(usd),
        proposed_usd=Decimal(usd),
        amount_usd=Decimal(usd),
        cap_usd=Decimal("100.00"),
        cap_applied=False,
        priced_from="INV-1",
    )


def nothing_payable() -> AmountDerivation:
    return AmountDerivation(
        components=(),
        items_total_usd=Decimal("0.00"),
        proposed_usd=Decimal("0.00"),
        amount_usd=Decimal("0.00"),
        cap_usd=Decimal("100.00"),
        cap_applied=False,
        priced_from="INV-1",
    )


def test_the_figure_is_added_by_code_after_the_models_wording() -> None:
    conclusion = a_conclusion(body="We have approved your claim.")

    email = finish_email(
        conclusion,
        recommendation=Recommendation.APPROVE,
        amount=an_amount("0.10"),
        contact_email="ops@merchant.example",
    )

    assert email.body == "We have approved your claim.\n\nApproved amount: $0.10"


def test_the_figure_never_passes_through_a_floating_point_number() -> None:
    conclusion = a_conclusion(body="We have approved your claim.")

    email = finish_email(
        conclusion,
        recommendation=Recommendation.APPROVE,
        amount=an_amount("1.005"),
        contact_email="ops@merchant.example",
    )

    assert email.body.endswith("Approved amount: $1.01")
    assert f"{1.005:.2f}" == "1.00"


def test_an_email_is_still_written_when_the_case_has_no_contact_address() -> None:
    conclusion = a_conclusion(body="We have approved your claim.")

    email = finish_email(
        conclusion,
        recommendation=Recommendation.APPROVE,
        amount=an_amount("52.00"),
        contact_email=None,
    )

    assert email.to is None
    assert email.body.endswith("Approved amount: $52.00")


def test_every_finished_email_is_marked_unsent() -> None:
    for recommendation in (Recommendation.APPROVE, Recommendation.REQUEST_INFO):
        amount = an_amount("52.00") if recommendation is Recommendation.APPROVE else None
        body = (
            "We have approved your claim."
            if recommendation is Recommendation.APPROVE
            else "Please send a photo of the damaged product."
        )
        email = finish_email(
            a_conclusion(recommendation=recommendation, body=body),
            recommendation=recommendation,
            amount=amount,
            contact_email="ops@merchant.example",
            requested_details=(
                ("a photo of the damaged product",)
                if recommendation is Recommendation.REQUEST_INFO
                else ()
            ),
        )
        assert email.is_draft is True


MONEY_THE_MODEL_MUST_NOT_WRITE = (
    "$52",
    "$52.00",
    "$ 52.00",
    "£10",
    "€10",
    "US$100",
    "52 €",
    "52 dollars",
    "52 USD",
    "52USD",
    "USD 52",
    "50 cents",
    "twenty bucks",
    "ten euros",
    "fifty-two dollars",
    "one hundred dollars",
    "one hundred and fifty dollars",
    "52.00",
    "9.99",
    "0.10",
    "1,200.00",
)


@pytest.mark.parametrize("written", MONEY_THE_MODEL_MUST_NOT_WRITE)
def test_money_the_model_wrote_is_recognised(written: str) -> None:
    assert money_the_model_wrote(f"We will refund {written} to you.")


NUMBERS_THAT_ARE_NOT_MONEY = (
    "We received 2 bottles of Liposomal Tripeptide Collagen.",
    "1 of the 6 items in the order arrived broken.",
    "Your order was delivered on 11 February 2026.",
    "Delivered 2026-02-11 and the claim was opened 11.02.2026.",
    "Case CASE-1005, shipment 342578703, SKU 0180.",
    "Order 1234567890 contained 12 items.",
    "Please reply within 14 days.",
    "The outer box weighs 2 pounds.",
    "The bottle holds 1.5 litres.",
    "50 per cent of the order was unaffected.",
)


@pytest.mark.parametrize("written", NUMBERS_THAT_ARE_NOT_MONEY)
def test_ordinary_numbers_in_a_merchant_email_are_left_alone(written: str) -> None:
    assert money_the_model_wrote(written) == ()


def test_an_email_carrying_a_figure_the_model_wrote_is_refused() -> None:
    conclusion = a_conclusion(body="We will refund $52.00 for the damaged bottle.")

    with pytest.raises(ModelOutputRejectedError) as refusal:
        finish_email(
            conclusion,
            recommendation=Recommendation.APPROVE,
            amount=an_amount("52.00"),
            contact_email="ops@merchant.example",
        )

    assert refusal.value.details["in_body"] == ["$52.00"]


def test_a_figure_in_the_subject_line_is_refused_as_well() -> None:
    conclusion = a_conclusion(subject="Your claim CASE-1005: $52.00 approved")

    with pytest.raises(ModelOutputRejectedError) as refusal:
        finish_email(
            conclusion,
            recommendation=Recommendation.APPROVE,
            amount=an_amount("52.00"),
            contact_email="ops@merchant.example",
        )

    assert refusal.value.details["in_subject"] == ["$52.00"]


def test_the_figure_this_file_inserts_is_not_mistaken_for_the_models_own() -> None:
    conclusion = a_conclusion(body="We have approved your claim.")

    email = finish_email(
        conclusion,
        recommendation=Recommendation.APPROVE,
        amount=an_amount("52.00"),
        contact_email="ops@merchant.example",
    )

    assert money_the_model_wrote(email.body)
    assert email.body == "We have approved your claim.\n\nApproved amount: $52.00"


WORDING_THAT_DESCRIBES_THE_EMAIL = (
    "This is a draft and has not been approved.",
    "DRAFT: your claim CASE-1005",
    "This message is unsent.",
    "This reply has not yet been sent.",
    "Held for review by our team.",
    "Do not send this to the customer.",
    "Internal use only.",
)


@pytest.mark.parametrize("written", WORDING_THAT_DESCRIBES_THE_EMAIL)
def test_an_email_describing_itself_as_a_draft_is_recognised(written: str) -> None:
    assert draft_markers_the_model_wrote(written)


WORDING_ABOUT_THE_CLAIM_RATHER_THAN_THE_EMAIL = (
    "Your claim is under review and we will be back in touch.",
    "Your claim is pending approval by our support team.",
    "Your reimbursement is awaiting approval.",
)


@pytest.mark.parametrize("written", WORDING_ABOUT_THE_CLAIM_RATHER_THAN_THE_EMAIL)
def test_wording_about_the_claim_still_being_decided_is_allowed(written: str) -> None:
    assert draft_markers_the_model_wrote(written) == ()


def test_an_email_that_calls_itself_a_draft_is_refused() -> None:
    conclusion = a_conclusion(body="This is a draft. We will refund you shortly.")

    with pytest.raises(ModelOutputRejectedError) as refusal:
        finish_email(
            conclusion,
            recommendation=Recommendation.APPROVE,
            amount=an_amount("52.00"),
            contact_email="ops@merchant.example",
        )

    assert refusal.value.details["in_body"] == ["draft"]


def test_an_email_that_recommends_paying_but_has_no_amount_is_refused() -> None:
    conclusion = a_conclusion(body="We have approved your claim.")

    with pytest.raises(ModelOutputRejectedError):
        finish_email(
            conclusion,
            recommendation=Recommendation.APPROVE,
            amount=None,
            contact_email="ops@merchant.example",
        )


def test_an_approval_whose_amount_comes_to_nothing_is_refused() -> None:
    conclusion = a_conclusion(body="We have approved your claim.")

    with pytest.raises(ModelOutputRejectedError):
        finish_email(
            conclusion,
            recommendation=Recommendation.APPROVE,
            amount=nothing_payable(),
            contact_email="ops@merchant.example",
        )


def test_the_capped_amount_is_added_after_the_models_wording() -> None:
    conclusion = a_conclusion(body="We have approved your claim and a credit is on its way.")

    email = finish_email(
        conclusion,
        recommendation=Recommendation.APPROVE,
        amount=an_amount("52.00"),
        contact_email="ops@merchant.example",
    )

    assert email.body == (
        "We have approved your claim and a credit is on its way.\n\nApproved amount: $52.00"
    )


def test_a_request_that_needs_no_figure_is_finished_untouched() -> None:
    conclusion = a_conclusion(
        body="Please send a photo of the outer shipping box.",
        recommendation=Recommendation.REQUEST_INFO,
    )

    email = finish_email(
        conclusion,
        recommendation=Recommendation.REQUEST_INFO,
        amount=None,
        contact_email="ops@merchant.example",
        requested_details=("a photo of the outer shipping box",),
    )

    assert email.body == "Please send a photo of the outer shipping box."
    assert email.to == "ops@merchant.example"


def test_naturally_reworded_requests_are_not_appended_a_second_time() -> None:
    details = (
        "A photograph of the outer box the order arrived in, even if it appears undamaged",
        "The two image files referenced in the customer's email about the L Carnitine, "
        "which were not included with the claim",
    )
    body = """Before we can complete our review, please send the following:

- A photograph of the outer box the order arrived in, even if the box itself appears undamaged.
- The two image files referenced in your customer's email regarding the L Carnitine, which were not included with the claim.

Once we have these, we will continue our review."""

    email = finish_email(
        a_conclusion(body=body, recommendation=Recommendation.REQUEST_INFO),
        recommendation=Recommendation.REQUEST_INFO,
        amount=None,
        contact_email="ops@merchant.example",
        requested_details=details,
    )

    assert email.body == body
    assert "Please provide:" not in email.body


def test_a_genuinely_omitted_request_is_still_appended() -> None:
    missing = "a photograph of the damaged Blue Razz Liquid Carnitine"

    email = finish_email(
        a_conclusion(
            body="Please send the invoice for this order.",
            recommendation=Recommendation.REQUEST_INFO,
        ),
        recommendation=Recommendation.REQUEST_INFO,
        amount=None,
        contact_email="ops@merchant.example",
        requested_details=("the invoice for this order", missing),
    )

    assert email.body.endswith(f"Please provide:\n- {missing}")


def test_every_piece_of_evidence_has_merchant_facing_wording() -> None:
    assert set(MISSING_EVIDENCE_WORDING) == set(EvidenceKind)
    for wording in MISSING_EVIDENCE_WORDING.values():
        assert wording != ""
        assert wording[0].islower()


def test_a_gap_is_named_rather_than_summed_up_as_more_information() -> None:
    findings = (
        *(
            EvidenceFinding(kind=kind, state=State.PRESENT, observed="Seen.", attachment_id="a")
            for kind in REQUIRED_EVIDENCE
            if kind is not EvidenceKind.OUTER_PACKAGING_PHOTO
        ),
        EvidenceFinding(
            kind=EvidenceKind.OUTER_PACKAGING_PHOTO,
            state=State.MISSING,
            observed="No photograph of the outer box was attached.",
        ),
    )

    assert name_what_is_missing(findings) == (
        "a photo of the outer shipping box the order arrived in, damaged or not",
    )


def test_an_unusable_photo_is_asked_for_again_alongside_a_missing_one() -> None:
    findings = (
        EvidenceFinding(kind=EvidenceKind.INVOICE, state=State.PRESENT, observed="Seen."),
        EvidenceFinding(
            kind=EvidenceKind.CUSTOMER_CONFIRMATION,
            state=State.MISSING,
            observed="No message from the customer was attached.",
        ),
        EvidenceFinding(
            kind=EvidenceKind.DAMAGED_PRODUCT_PHOTO,
            state=State.UNUSABLE,
            observed="A photograph too dark to make anything out.",
            problem="The photo is too dark.",
        ),
        EvidenceFinding(
            kind=EvidenceKind.OUTER_PACKAGING_PHOTO, state=State.PRESENT, observed="Seen."
        ),
    )

    assert name_what_is_missing(findings) == (
        MISSING_EVIDENCE_WORDING[EvidenceKind.CUSTOMER_CONFIRMATION],
        MISSING_EVIDENCE_WORDING[EvidenceKind.DAMAGED_PRODUCT_PHOTO],
    )


def test_evidence_we_could_not_read_ourselves_is_never_asked_for() -> None:
    findings = (
        *(
            EvidenceFinding(kind=kind, state=State.PRESENT, observed="Seen.", attachment_id="a")
            for kind in REQUIRED_EVIDENCE
            if kind is not EvidenceKind.INVOICE
        ),
        EvidenceFinding(
            kind=EvidenceKind.INVOICE,
            state=State.UNREADABLE,
            observed="The invoice could not be fetched.",
            problem="We could not download it.",
        ),
    )

    assert name_what_is_missing(findings) == ()


def test_nothing_is_asked_for_when_all_four_pieces_of_evidence_are_in_hand() -> None:
    findings = tuple(
        EvidenceFinding(kind=kind, state=State.PRESENT, observed="Seen.", attachment_id="a")
        for kind in REQUIRED_EVIDENCE
    )

    assert name_what_is_missing(findings) == ()


def test_the_same_wording_always_finishes_the_same_way() -> None:
    conclusion = a_conclusion(body="We have approved your claim.")

    first = finish_email(
        conclusion,
        recommendation=Recommendation.APPROVE,
        amount=an_amount("52.00"),
        contact_email="ops@merchant.example",
    )
    second = finish_email(
        conclusion,
        recommendation=Recommendation.APPROVE,
        amount=an_amount("52.00"),
        contact_email="ops@merchant.example",
    )

    assert first == second
