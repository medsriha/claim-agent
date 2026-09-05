"""Finishing the merchant email: putting the real figure in, and refusing invented ones.

Nothing here reaches a model. Every test hands in a conclusion of its own making —
the shape the model would have filled in — because what is under test is what
happens to that wording afterwards, not how it was produced.

Two halves matter equally, and both are covered on purpose. Money the model wrote
has to be caught, or an invented figure reaches a merchant. Numbers that are not
money have to be left alone, or a good claim is sent to a person over "2 bottles".
"""

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
from claim_agent.agent.schemas import AMOUNT_PLACEHOLDER, InvestigationConclusion
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
    """Build the answer the model would have given, with only the wording that matters set."""
    return InvestigationConclusion(
        evidence=(),
        recommendation=recommendation,
        reasoning="The photographs show the damage described.",
        confidence=0.9,
        email_subject=subject,
        email_body=body,
    )


def an_amount(usd: str) -> AmountDerivation:
    """Build a worked-out amount for a single damaged bottle, priced from an invoice."""
    return AmountDerivation(
        components=(
            AmountComponent(
                product_name="Liposomal Tripeptide Collagen",
                quantity=1,
                unit_price=Decimal(usd),
                # This file is about substituting the figure, not about working it out,
                # so the item refunds its whole price and the amount below is the figure
                # under test.
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
    """Build the amount that comes back when nothing on the claim could be priced."""
    return AmountDerivation(
        components=(),
        items_total_usd=Decimal("0.00"),
        proposed_usd=Decimal("0.00"),
        amount_usd=Decimal("0.00"),
        cap_usd=Decimal("100.00"),
        cap_applied=False,
        priced_from="INV-1",
    )


def test_the_real_figure_replaces_the_marker_the_model_left() -> None:
    """FR-1.21: the model says a figure belongs here, and code says which figure it is."""
    conclusion = a_conclusion(body=f"We will refund {AMOUNT_PLACEHOLDER} for the damaged bottle.")

    email = finish_email(
        conclusion,
        recommendation=Recommendation.APPROVE,
        amount=an_amount("52.00"),
        contact_email="ops@merchant.example",
    )

    assert email.body == "We will refund $52.00 for the damaged bottle."
    assert AMOUNT_PLACEHOLDER not in email.body


def test_the_marker_is_replaced_in_the_subject_line_too() -> None:
    """FR-2.7: the subject is part of the exact wording a merchant would receive."""
    conclusion = a_conclusion(subject=f"Your claim CASE-1005: {AMOUNT_PLACEHOLDER} approved")

    email = finish_email(
        conclusion,
        recommendation=Recommendation.APPROVE,
        amount=an_amount("52.00"),
        contact_email="ops@merchant.example",
    )

    assert email.subject == "Your claim CASE-1005: $52.00 approved"


def test_a_figure_is_written_to_the_exact_cent() -> None:
    """FR-1.21: the figure a merchant reads is the one the arithmetic produced, to the cent."""
    conclusion = a_conclusion(body=f"We will refund {AMOUNT_PLACEHOLDER}.")

    email = finish_email(
        conclusion,
        recommendation=Recommendation.APPROVE,
        amount=an_amount("0.10"),
        contact_email="ops@merchant.example",
    )

    assert email.body == "We will refund $0.10."


def test_the_figure_never_passes_through_a_floating_point_number() -> None:
    """NFR-2: money stays an exact decimal, so no cent can drift on its way to a merchant.

    An amount of 1.005 is the case that tells the two apart. Held as an exact decimal
    and rounded the way money is rounded, it is $1.01. Turned into a floating point
    number first it becomes very slightly less than 1.005 and rounds down to $1.00,
    which is a cent the merchant would never get back.
    """
    conclusion = a_conclusion(body=f"We will refund {AMOUNT_PLACEHOLDER}.")

    email = finish_email(
        conclusion,
        recommendation=Recommendation.APPROVE,
        amount=an_amount("1.005"),
        contact_email="ops@merchant.example",
    )

    assert email.body == "We will refund $1.01."
    assert f"{1.005:.2f}" == "1.00"


def test_an_email_is_still_written_when_the_case_has_no_contact_address() -> None:
    """FR-2.7: the wording is worth having even when there is nobody to send it to yet."""
    conclusion = a_conclusion(body=f"We will refund {AMOUNT_PLACEHOLDER}.")

    email = finish_email(
        conclusion,
        recommendation=Recommendation.APPROVE,
        amount=an_amount("52.00"),
        contact_email=None,
    )

    assert email.to is None
    assert email.body == "We will refund $52.00."


def test_every_finished_email_is_marked_unsent() -> None:
    """FR-1.17: nothing this file produces can describe itself as already sent."""
    for recommendation in (Recommendation.APPROVE, Recommendation.REQUEST_INFO):
        amount = an_amount("52.00") if recommendation is Recommendation.APPROVE else None
        body = (
            f"We will refund {AMOUNT_PLACEHOLDER}."
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
    """FR-1.21: no monetary figure may be read out of model output, however it is written."""
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
    f"We will refund {AMOUNT_PLACEHOLDER} for the damaged bottle.",
)


@pytest.mark.parametrize("written", NUMBERS_THAT_ARE_NOT_MONEY)
def test_ordinary_numbers_in_a_merchant_email_are_left_alone(written: str) -> None:
    """FR-1.7: a good claim must not be sent to a person because the email counted bottles.

    Quantities, dates, order numbers and product codes are what a useful merchant email
    is made of. Reading any of them as a figure would refuse an email that is entirely
    correct.
    """
    assert money_the_model_wrote(written) == ()


def test_a_currency_symbol_beside_the_marker_counts_as_money() -> None:
    """FR-1.21: the marker stands for the whole figure, so "${{amount}}" would double the sign."""
    assert money_the_model_wrote(f"We will refund ${AMOUNT_PLACEHOLDER}.")
    assert money_the_model_wrote(f"We will refund {AMOUNT_PLACEHOLDER}$.")


def test_an_email_carrying_a_figure_the_model_wrote_is_refused() -> None:
    """FR-1.21: an invented figure is refused outright rather than corrected."""
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
    """FR-1.21: a subject reaches a merchant exactly as a body does."""
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
    """FR-1.21: the search reads the model's words, and runs before the real figure goes in."""
    conclusion = a_conclusion(body=f"We will refund {AMOUNT_PLACEHOLDER}.")

    email = finish_email(
        conclusion,
        recommendation=Recommendation.APPROVE,
        amount=an_amount("52.00"),
        contact_email="ops@merchant.example",
    )

    assert money_the_model_wrote(email.body)
    assert email.body == "We will refund $52.00."


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
    """FR-1.17: a marker inside the wording is a marker that can reach a merchant."""
    assert draft_markers_the_model_wrote(written)


WORDING_ABOUT_THE_CLAIM_RATHER_THAN_THE_EMAIL = (
    "Your claim is under review and we will be back in touch.",
    "Your claim is pending approval by our support team.",
    "Your reimbursement is awaiting approval.",
)


@pytest.mark.parametrize("written", WORDING_ABOUT_THE_CLAIM_RATHER_THAN_THE_EMAIL)
def test_wording_about_the_claim_still_being_decided_is_allowed(written: str) -> None:
    """FR-1.17: telling a merchant the claim is not settled is the honest thing to write.

    The ban is on the email describing itself, not on the email saying a person has yet
    to decide. Refusing these would refuse exactly the wording the requirement wants.
    """
    assert draft_markers_the_model_wrote(written) == ()


def test_an_email_that_calls_itself_a_draft_is_refused() -> None:
    """FR-1.17, FR-2.7: a rep must read the exact words a merchant would get, and no others."""
    conclusion = a_conclusion(body="This is a draft. We will refund you shortly.")

    with pytest.raises(ModelOutputRejectedError) as refusal:
        finish_email(
            conclusion,
            recommendation=Recommendation.APPROVE,
            amount=an_amount("52.00"),
            contact_email="ops@merchant.example",
        )

    assert refusal.value.details["in_body"] == ["draft"]


def test_a_marker_left_where_no_figure_can_go_is_refused() -> None:
    """FR-1.21: an email reading "we will refund {{amount}}" must never look sendable.

    Nothing is being recommended for payment, so there is no figure to write. Leaving
    the marker showing would put unfinished wording in front of a rep as though it were
    ready to go.
    """
    conclusion = a_conclusion(
        body=f"We will refund {AMOUNT_PLACEHOLDER} once we have the photos.",
        recommendation=Recommendation.REQUEST_INFO,
    )

    with pytest.raises(ModelOutputRejectedError) as refusal:
        finish_email(
            conclusion,
            recommendation=Recommendation.REQUEST_INFO,
            amount=None,
            contact_email="ops@merchant.example",
            requested_details=("a photo of the outer shipping box",),
        )

    assert refusal.value.details["recommendation"] == "request_info"


def test_a_marker_is_refused_on_a_non_approval_even_when_an_amount_was_worked_out() -> None:
    """FR-1.21: a figure is only ever written into an email that recommends paying it.

    An amount can be worked out for a line the rules then decline to pay. Filling it in
    would promise a merchant money nobody is recommending they receive.
    """
    conclusion = a_conclusion(
        body=f"We will refund {AMOUNT_PLACEHOLDER}.",
        recommendation=Recommendation.REQUEST_REP_CLARIFICATION,
    )

    with pytest.raises(ModelOutputRejectedError):
        finish_email(
            conclusion,
            recommendation=Recommendation.REQUEST_REP_CLARIFICATION,
            amount=an_amount("52.00"),
            contact_email="ops@merchant.example",
        )


def test_an_email_that_recommends_paying_but_has_no_amount_is_refused() -> None:
    """FR-1.21: approval without a worked-out figure has nothing honest to write."""
    conclusion = a_conclusion(body=f"We will refund {AMOUNT_PLACEHOLDER}.")

    with pytest.raises(ModelOutputRejectedError):
        finish_email(
            conclusion,
            recommendation=Recommendation.APPROVE,
            amount=None,
            contact_email="ops@merchant.example",
        )


def test_an_approval_whose_amount_comes_to_nothing_is_refused() -> None:
    """FR-1.21: a refund of no money is a fault upstream, not an email to send a merchant."""
    conclusion = a_conclusion(body=f"We will refund {AMOUNT_PLACEHOLDER}.")

    with pytest.raises(ModelOutputRejectedError):
        finish_email(
            conclusion,
            recommendation=Recommendation.APPROVE,
            amount=nothing_payable(),
            contact_email="ops@merchant.example",
        )


def test_an_approval_email_that_never_mentions_the_amount_is_refused() -> None:
    """An approval email must communicate the exact amount the report approved."""
    conclusion = a_conclusion(body="We have approved your claim and a credit is on its way.")

    with pytest.raises(ModelOutputRejectedError):
        finish_email(
            conclusion,
            recommendation=Recommendation.APPROVE,
            amount=an_amount("52.00"),
            contact_email="ops@merchant.example",
        )


def test_a_request_that_needs_no_figure_is_finished_untouched() -> None:
    """FR-1.7: the ordinary case, where the model asks for something and promises nothing."""
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


def test_every_piece_of_evidence_has_merchant_facing_wording() -> None:
    """FR-1.7: a request names the specific gap, so a fifth kind cannot arrive unworded."""
    assert set(MISSING_EVIDENCE_WORDING) == set(EvidenceKind)
    for wording in MISSING_EVIDENCE_WORDING.values():
        # Each one has to drop into "this claim is missing ...", so it reads as a
        # fragment of a sentence rather than as a sentence of its own.
        assert wording != ""
        assert wording[0].islower()


def test_a_gap_is_named_rather_than_summed_up_as_more_information() -> None:
    """FR-1.7: "a photo of the outer shipping box" is actionable; "more information" is not."""
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
    """FR-1.7: a photo too dark to use is something the merchant can send again."""
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

    # Always in the fixed reporting order, whatever order the findings arrived in, so
    # two requests to two merchants read the same way.
    assert name_what_is_missing(findings) == (
        MISSING_EVIDENCE_WORDING[EvidenceKind.CUSTOMER_CONFIRMATION],
        MISSING_EVIDENCE_WORDING[EvidenceKind.DAMAGED_PRODUCT_PHOTO],
    )


def test_evidence_we_could_not_read_ourselves_is_never_asked_for() -> None:
    """FR-1.7: a merchant cannot act on our own download failing, so they are not asked to."""
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
    """FR-1.6: a complete claim has no gaps, and an empty request is not sent."""
    findings = tuple(
        EvidenceFinding(kind=kind, state=State.PRESENT, observed="Seen.", attachment_id="a")
        for kind in REQUIRED_EVIDENCE
    )

    assert name_what_is_missing(findings) == ()


def test_the_same_wording_always_finishes_the_same_way() -> None:
    """NFR-1: nothing here reads a clock or a model, so two runs agree."""
    conclusion = a_conclusion(body=f"We will refund {AMOUNT_PLACEHOLDER}.")

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
