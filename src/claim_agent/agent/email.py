"""Finishing the merchant email the model drafted, and refusing it when the model wrote money.

The investigation writes the wording of the email a merchant would receive, because
it is the only part of the system that knows what actually happened to this claim.
It is not allowed to write a single figure *here*. Where an amount belongs it writes a
marker, `{{amount}}`, and this file puts the real figure there — the amount that came
out of the cap in `claim_agent.domain.reimbursement` (FR-1.21).

**Note what that protects, because it is not what it used to protect.** The
investigation now decides what the damage is worth, so the point is no longer that a
model may not know a figure. The point is that the figure a merchant reads must be the
one that **survived the cap**, and those two can differ: an investigation may recommend
two hundred dollars on a claim that may only be reimbursed a hundred. An email written
with its own figure in it would promise the merchant the wrong number, and it would be
the larger one.

**That is only worth anything if it is enforced.** A model asked not to write money will
usually not write money, and "usually" is not a rule. So the wording is
searched for anything money-shaped before the figure goes in, and an email with
money in it is refused outright rather than tidied up. Refusing sends the claim to a
person (NFR-4); cleaning it up would leave a rep reading wording that neither the
model nor anyone else actually wrote.

**The search runs before the substitution, and there is nothing after it.** The
figure this file inserts is money-shaped by definition, so checking the finished
email would refuse every approval there has ever been. If you are here to add a
second check at the end, that is why there isn't one.

The email also may not describe itself as a draft, for the reason the pre-flight
screen's email gives at more length: a representative has to read the exact wording
that would be sent (FR-2.7), so a marker inside the text is a marker that can reach
a merchant. That the email is unsent is recorded beside it, on the email itself,
which is where a screen showing it to a representative reads it from (FR-1.17).

Two smaller things live here as well. A figure is only ever filled in for a
recommendation of payment, so an email promising money on a claim nobody is
recommending paying cannot be produced. And the plain wording for each of the four
pieces of evidence is here, so a request to a merchant names the thing it wants
rather than asking for "more information" (FR-1.7).

Nothing here reaches out to anything and nothing here reads a clock.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from decimal import ROUND_HALF_UP

from claim_agent.agent.schemas import AMOUNT_PLACEHOLDER, InvestigationConclusion
from claim_agent.domain.evidence import EvidenceFinding, EvidenceKind, gaps_the_merchant_can_fill
from claim_agent.domain.models import DraftedEmail
from claim_agent.domain.outcome import Recommendation
from claim_agent.domain.reimbursement import CENTS, AmountDerivation
from claim_agent.errors import ModelOutputRejectedError

MISSING_EVIDENCE_WORDING: dict[EvidenceKind, str] = {
    EvidenceKind.INVOICE: "the invoice for this order, showing what was bought and what it cost",
    EvidenceKind.CUSTOMER_CONFIRMATION: (
        "a message from the customer who received the parcel, confirming it arrived damaged"
    ),
    EvidenceKind.DAMAGED_PRODUCT_PHOTO: "a photo of the damaged product itself",
    EvidenceKind.OUTER_PACKAGING_PHOTO: (
        "a photo of the outer shipping box the order arrived in, damaged or not"
    ),
}
"""How each of the four pieces of evidence is described to a merchant (FR-1.7).

A merchant asked for "more information" sends the wrong thing and the claim takes
another round trip, so every request names the specific item. This is the whole list,
kept together in one place precisely so the words a merchant reads can be checked at a
glance instead of being hunted for in sentences.

**Nobody at ShipBob has approved this wording.** It is our best guess at how their
support team would say these things, and it is the kind of text a support manager
should be shown before a merchant is.

The outer packaging entry says "damaged or not" on purpose. The box has to have been
photographed, not to be damaged — an intact box with a broken product inside is a
perfectly ordinary claim (FR-1.11) — and a merchant who reads the request as being
only about damaged boxes will not send the photo.
"""

_CURRENCY_SYMBOLS = r"$£€¥₹¢"
"""The currency symbols a figure can be written with.

Not every symbol in the world. These are the ones a model writing to a merchant of a
United States company plausibly reaches for, and each one is unambiguous: none of them
means anything else in an email about a damaged parcel.
"""

_NUMBER = r"\d[\d,]*(?:\.\d+)?"
"""A figure written in digits, thousands separators and decimals included."""

_NUMBER_WORDS = (
    "zero",
    "one",
    "two",
    "three",
    "four",
    "five",
    "six",
    "seven",
    "eight",
    "nine",
    "ten",
    "eleven",
    "twelve",
    "thirteen",
    "fourteen",
    "fifteen",
    "sixteen",
    "seventeen",
    "eighteen",
    "nineteen",
    "twenty",
    "thirty",
    "forty",
    "fifty",
    "sixty",
    "seventy",
    "eighty",
    "ninety",
    "hundred",
    "thousand",
    "million",
)
"""Numbers written as words, so "fifty-two dollars" is caught as well as "$52".

Spelling a figure out is the obvious way around a search for digits, and an amount a
merchant can read is an amount however it is written.
"""

_CURRENCY_WORDS = (
    r"dollars?",
    r"usd",
    r"euros?",
    r"eur",
    r"gbp",
    r"cad",
    r"aud",
    r"cents?",
    r"bucks?",
    r"pounds?\s+sterling",
)
"""Words that turn a number into an amount of money.

**"Pounds" on its own is deliberately not here, and that is the one hole worth knowing
about.** It is a weight as often as it is a currency, and "the 2 pound box" is a
sentence a merchant email can legitimately contain. British pounds are caught by their
symbol and by "pounds sterling"; a figure written as "10 pounds" would get through.
That trade is deliberate: this is a United States company invoicing in dollars, so the
weight reading is the likelier one by a distance.
"""


def _any_of(options: Sequence[str]) -> str:
    """Build the "one of these" half of a pattern, longest option first.

    Longest first so that "seventeen" is tried before "seven". The pattern would still
    match either way, because the search backtracks, but the fragment reported to a
    reader would sometimes be the short half of a longer word.
    """
    return "|".join(sorted(options, key=len, reverse=True))


_WRITTEN_NUMBER = (
    rf"(?:{_any_of(_NUMBER_WORDS)})(?:[\s-]+(?:and[\s-]+)?(?:{_any_of(_NUMBER_WORDS)}))*"
)
"""A number written out in words, however many words it takes: "one hundred and fifty"."""

_MONEY_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(rf"[{_CURRENCY_SYMBOLS}]\s*{_NUMBER}"),
    re.compile(rf"{_NUMBER}\s*[{_CURRENCY_SYMBOLS}]"),
    re.compile(
        rf"[{_CURRENCY_SYMBOLS}]\s*{re.escape(AMOUNT_PLACEHOLDER)}"
        rf"|{re.escape(AMOUNT_PLACEHOLDER)}\s*[{_CURRENCY_SYMBOLS}]"
    ),
    re.compile(
        rf"\b(?:{_NUMBER}|{_WRITTEN_NUMBER})\s*-?\s*(?:{_any_of(_CURRENCY_WORDS)})\b",
        re.IGNORECASE,
    ),
    re.compile(rf"\b(?:usd|eur|gbp|cad|aud|jpy)\s*{_NUMBER}", re.IGNORECASE),
    re.compile(rf"(?<![\d.{_CURRENCY_SYMBOLS}])\d[\d,]*\.\d{{2}}(?![\d.])"),
)
"""Every shape money can take in text the model wrote, in the order they are searched.

Six shapes, and the reasoning behind each one is the same: **a bare number is never
money.** A merchant email is full of bare numbers — how many bottles arrived, which
order it was, what the product code is, what day it was delivered — and treating any of
them as a figure would send a good claim to a person for no reason. A number only
counts as money when something beside it says so:

1. a currency symbol in front of it, "$52.00";
2. a currency symbol behind it, "52 €", which is how much of the world writes it;
3. a currency symbol beside the marker, "${{amount}}". The marker stands for the whole
   figure, symbol included, so a symbol next to it would come out as "$$52.00";
4. a currency word after it, in digits or in words: "52 dollars", "fifty-two dollars";
5. a currency code in front of it, "USD 52";
6. nothing beside it at all, but written to exactly two decimal places, "52.00" or
   "1,200.00". This is the one that catches a figure written with no currency marker
   whatsoever, and it is the one most likely to be wrong about a number that is not
   money.

That last shape is the one to think twice about, because plenty of numbers have a dot
in them. It only matches two decimal places and refuses to match when another digit or
another dot sits beside them, which is what lets a date written "11.02.2026" through
along with "11 February 2026" and "2026-02-11". A time written "3.30" and a clause
numbered "3.14" would both still be refused. Neither is likely in an email to a
merchant, and both fail in the safe direction: a person looks at the claim.
"""

_DRAFT_MARKERS = (
    r"drafts?",
    r"drafted",
    r"unsent",
    r"not\s+(?:yet\s+)?(?:been\s+)?sent",
    r"do\s+not\s+send",
    r"for\s+review",
    r"internal\s+use\s+only",
)
"""Words that would tell a merchant this email is not the real thing.

None of them may appear, for the reason FR-1.17 gives and the pre-flight screen's email
repeats: a representative has to read the exact wording that would be sent, so a marker
inside the text is a marker that can reach a merchant. The email being unsent is
recorded next to it and not in it.

They are written as small searches rather than plain phrases so that one entry covers
the ways a person actually writes it: "not sent", "not yet sent", "not been sent" and
"not yet been sent" are one entry, not four.

**"For review" is the entry most likely to refuse a perfectly good email**, because
"your claim is with our team for review" is a reasonable thing to tell a merchant. It
is here anyway: refusing hands the claim to a person, which costs a few minutes, and
the alternative is an email describing itself. If reps start seeing claims sent for representative clarification
for no visible reason, this is the first entry to look at.

**"Under review", "pending approval" and "awaiting approval" are deliberately not
here.** Those describe the state of the *claim*, which is exactly what a merchant
should be told while a representative is still deciding (FR-1.17), rather than the
state of the email.
"""

_DRAFT_MARKER_PATTERN = re.compile(rf"\b(?:{'|'.join(_DRAFT_MARKERS)})\b", re.IGNORECASE)
"""The markers above as one search.

Every space in them is written as "any whitespace", so a phrase that happens to fall
across two lines is still found."""


def finish_email(
    conclusion: InvestigationConclusion,
    *,
    recommendation: Recommendation,
    amount: AmountDerivation | None,
    contact_email: str | None,
    requested_details: Sequence[str] = (),
) -> DraftedEmail:
    """Turn the wording the model wrote into the finished draft a representative reviews.

    Three things happen, in this order. The wording is checked for money the model wrote
    itself and for anything describing the email as a draft, and either one refuses the
    email. Then, and only for a recommendation of payment, the marker the model left is
    replaced with the figure the arithmetic produced. What comes back is written but
    unsent, and it says so on itself rather than in its words.

    **The figure is only ever filled in on a recommendation of payment.** Any other
    recommendation with a marker still in it is refused, even when an amount was worked
    out along the way. An email promising money on a claim nobody is recommending paying
    is the worst thing this file could produce, and an email reading "we will refund
    {{amount}}" put in front of a representative looking sendable is barely better.

    An approval with no payable amount is refused for the mirror of that reason: there is
    no figure to write, and the only ways to finish the email would be to leave the
    marker showing or to invent a number. The rules that settle a claim line already
    withhold approval when nothing can be priced, so reaching this with one means
    something upstream went wrong, and going to a person is the right answer to that
    (NFR-4).

    An approval whose wording never mentions the figure is refused: the approval email's
    purpose is to communicate the exact amount the report proposes.

    Args:
        conclusion: The investigation's whole answer. Only the subject and body are read
            here; the rest of it is the report's business.
        recommendation: What is being recommended for this claim line, after the rules
            have had their say. Decides whether a figure is filled in at all.
        amount: What a payment would come to, worked out by code from the invoice.
            `None` when no amount was worked out, which is fine for anything but an
            approval.
        contact_email: The merchant's address from the case. `None` is allowed and
            still produces a draft: the wording is worth having, and the later sending
            stage is what refuses to send without a recipient.
        requested_details: The specific merchant-fillable gaps. Required for
            `request_info`; any detail omitted from the model's wording is appended explicitly.

    Returns:
        The finished draft, with the real figure in it and `is_draft` fixed at true.

    Raises:
        ModelOutputRejectedError: the model wrote money itself, described the email as a draft,
            left the marker where no figure can go, or an approval arrived with nothing
            payable. Every one of these is refused rather than repaired, and the caller
            turns the refusal into an representative clarification request to a person (FR-1.21, FR-1.17, NFR-4).
    """
    subject = conclusion.email_subject
    body = conclusion.email_body
    if subject is None or body is None:
        raise ModelOutputRejectedError(
            "The action needs a merchant email, but the investigation did not draft both its "
            "subject and body."
        )

    _refuse_money_the_model_wrote(conclusion)
    _refuse_wording_that_calls_itself_a_draft(conclusion)

    if recommendation is Recommendation.APPROVE:
        if AMOUNT_PLACEHOLDER not in subject and AMOUNT_PLACEHOLDER not in body:
            raise ModelOutputRejectedError(
                "The approval email does not communicate the approved amount. It must include "
                "the amount marker so the exact approved figure can be inserted."
            )
        # Substituting last is deliberate: the figure is money-shaped, so the checks
        # above have to see the model's own words and nothing else.
        figure = _as_money(_payable(amount))
        subject = subject.replace(AMOUNT_PLACEHOLDER, figure)
        body = body.replace(AMOUNT_PLACEHOLDER, figure)
    elif recommendation is Recommendation.REQUEST_INFO:
        if AMOUNT_PLACEHOLDER in subject or AMOUNT_PLACEHOLDER in body:
            raise ModelOutputRejectedError(
                "The drafted email leaves a place for an amount on a claim line that is not "
                "recommended for payment, so there is no figure to put there.",
                details={"recommendation": recommendation.value},
            )
        details = tuple(
            dict.fromkeys(detail.strip() for detail in requested_details if detail.strip())
        )
        if not details:
            raise ModelOutputRejectedError(
                "The investigation proposed asking the merchant for information but did not "
                "identify any specific detail the merchant can provide."
            )
        missing_from_body = [detail for detail in details if detail.lower() not in body.lower()]
        if missing_from_body:
            requested = "\n".join(f"- {detail}" for detail in missing_from_body)
            body = f"{body.rstrip()}\n\nPlease provide:\n{requested}"
    elif AMOUNT_PLACEHOLDER in subject or AMOUNT_PLACEHOLDER in body:
        raise ModelOutputRejectedError(
            "The drafted email leaves a place for an amount on a claim line that is not "
            "recommended for payment, so there is no figure to put there.",
            details={"recommendation": recommendation.value},
        )

    return DraftedEmail(to=contact_email, subject=subject, body=body)


def money_the_model_wrote(text: str) -> tuple[str, ...]:
    """Find every piece of text that reads as an amount of money, in order.

    This is the check that makes "no figure of the model's own reaches a merchant" a rule
    rather than an instruction (FR-1.21). It is meant to be run on the model's own words,
    before the capped figure is substituted into them — the model may name an amount in
    its answer, and may not name one here, because the two can differ by the cap.

    Args:
        text: A subject line or an email body, as the model wrote it.

    Returns:
        The offending fragments, each listed once, in the order the searches found them.
        Empty means the text contains no money, which is the ordinary result. The
        fragments come back rather than a plain yes or no so that a refusal can say what
        it objected to — a representative reading "the model wrote $52.00" knows what
        happened, and "money was found" leaves them guessing (NFR-3).
    """
    found: list[str] = []
    for pattern in _MONEY_PATTERNS:
        for match in pattern.finditer(text):
            fragment = match.group(0).strip()
            if fragment not in found:
                found.append(fragment)
    return tuple(found)


def draft_markers_the_model_wrote(text: str) -> tuple[str, ...]:
    """Find every word describing the email as something other than what would be sent.

    Args:
        text: A subject line or an email body.

    Returns:
        The offending words, each listed once, in the order they appear. Empty is the
        ordinary result.
    """
    found: list[str] = []
    for match in _DRAFT_MARKER_PATTERN.finditer(text):
        marker = match.group(0)
        if marker not in found:
            found.append(marker)
    return tuple(found)


def name_what_is_missing(findings: Sequence[EvidenceFinding]) -> tuple[str, ...]:
    """Say, in words a merchant can act on, which pieces of evidence still have to arrive.

    Covers evidence that never turned up and evidence that turned up unusable, because
    the merchant can send either again. It leaves out anything we could not read
    ourselves — asking someone to send a photo a second time because our own download
    failed is a request they cannot act on (FR-1.7).

    Args:
        findings: What was found for each piece of evidence. A piece nobody looked for
            counts as missing.

    Returns:
        One sentence fragment per gap, always in the fixed reporting order, so two
        requests read the same way. Empty means there is nothing to ask for.
    """
    return tuple(MISSING_EVIDENCE_WORDING[kind] for kind in gaps_the_merchant_can_fill(findings))


def _refuse_money_the_model_wrote(conclusion: InvestigationConclusion) -> None:
    """Refuse the email if the model put a figure anywhere in it (FR-1.21).

    Both the subject and the body are searched. A subject line is part of the exact
    wording that would be sent, so an invented figure there reaches a merchant just as
    surely as one in the body.

    The fragments found go into the error so a representative can see what was objected
    to. They are the model's invention and are labelled as such, never repeated as if
    they were a real amount.
    """
    in_subject = money_the_model_wrote(conclusion.email_subject or "")
    in_body = money_the_model_wrote(conclusion.email_body or "")
    if not in_subject and not in_body:
        return
    raise ModelOutputRejectedError(
        "The drafted email contains an amount of money written by the investigation. "
        "Every figure has to be worked out from the invoice, so the email cannot be used.",
        details={"in_subject": list(in_subject), "in_body": list(in_body)},
    )


def _refuse_wording_that_calls_itself_a_draft(conclusion: InvestigationConclusion) -> None:
    """Refuse the email if its own words say it is a draft (FR-1.17, FR-2.7)."""
    in_subject = draft_markers_the_model_wrote(conclusion.email_subject or "")
    in_body = draft_markers_the_model_wrote(conclusion.email_body or "")
    if not in_subject and not in_body:
        return
    raise ModelOutputRejectedError(
        "The drafted email describes itself as unsent. A representative has to read the "
        "exact wording a merchant would get, so the email cannot be used.",
        details={"in_subject": list(in_subject), "in_body": list(in_body)},
    )


def _payable(amount: AmountDerivation | None) -> AmountDerivation:
    """Hand back the amount to write into the email, or refuse the email for want of one.

    An approval needs a figure above nothing. No amount at all, or one that came to
    nothing, means there is nothing to promise the merchant — and the alternative to
    refusing would be an email offering a refund of no money.
    """
    if amount is None:
        raise ModelOutputRejectedError(
            "Payment is recommended for this claim line, but no amount was worked out "
            "for it, so the merchant email cannot be finished.",
        )
    if not amount.is_payable:
        raise ModelOutputRejectedError(
            "Payment is recommended for this claim line, but the amount worked out for "
            "it comes to nothing, so the merchant email cannot be finished.",
        )
    return amount


def _as_money(amount: AmountDerivation) -> str:
    """Write the figure the way a merchant reads it: "$52.00".

    The marker the model leaves stands for the whole figure, currency symbol included,
    which is why the symbol is added here and why a symbol beside the marker is refused
    as money the model wrote.

    The figure is held as an exact decimal from the invoice all the way to this line and
    is never turned into a floating point number, so no cent can drift on the way to a
    merchant. It arrives already rounded to the cent; rounding again, the same way the
    amount itself was rounded, means a figure that somehow carried a third decimal place
    could never reach an email as one.
    """
    return f"${amount.amount_usd.quantize(CENTS, rounding=ROUND_HALF_UP)}"
