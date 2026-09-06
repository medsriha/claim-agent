from __future__ import annotations

import re
from collections.abc import Sequence
from decimal import ROUND_HALF_UP

from claim_agent.agent.schemas import (
    AMOUNT_PLACEHOLDER,
    ClaimSplit,
    InvestigationConclusion,
    RevisionPlan,
)
from claim_agent.domain.evidence import EvidenceFinding, EvidenceKind, gaps_the_merchant_can_fill
from claim_agent.domain.models import DraftedEmail
from claim_agent.domain.outcome import Recommendation
from claim_agent.domain.reimbursement import CENTS, AmountDerivation
from claim_agent.errors import ModelOutputRejectedError

# How each of the four pieces of evidence is described to a merchant (FR-1.7).
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
# The currency symbols a figure can be written with.
_CURRENCY_SYMBOLS = r"$£€¥₹¢"
# A figure written in digits, thousands separators and decimals included.
_NUMBER = r"\d[\d,]*(?:\.\d+)?"
# Numbers written as words, so "fifty-two dollars" is caught as well as "$52".
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
# Words that turn a number into an amount of money.
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


def _any_of(options: Sequence[str]) -> str:
    """Build the "one of these" half of a pattern, longest option first."""
    return "|".join(sorted(options, key=len, reverse=True))


# A number written out in words, however many words it takes: "one hundred and fifty".
_WRITTEN_NUMBER = (
    rf"(?:{_any_of(_NUMBER_WORDS)})(?:[\s-]+(?:and[\s-]+)?(?:{_any_of(_NUMBER_WORDS)}))*"
)
# Every shape money can take in text the model wrote, in the order they are searched.
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
# Words that would tell a merchant this email is not the real thing.
_DRAFT_MARKERS = (
    r"drafts?",
    r"drafted",
    r"unsent",
    r"not\s+(?:yet\s+)?(?:been\s+)?sent",
    r"do\s+not\s+send",
    r"for\s+review",
    r"internal\s+use\s+only",
)
# The markers above as one search.
_DRAFT_MARKER_PATTERN = re.compile(rf"\b(?:{'|'.join(_DRAFT_MARKERS)})\b", re.IGNORECASE)
_REQUEST_WORD_PATTERN = re.compile(r"[a-z0-9]+(?:'[a-z]+)?", re.IGNORECASE)
_REQUEST_STOP_WORDS = frozenset(
    {
        "a",
        "an",
        "and",
        "about",
        "concerning",
        "for",
        "from",
        "in",
        "of",
        "on",
        "or",
        "please",
        "provide",
        "regarding",
        "send",
        "that",
        "the",
        "this",
        "to",
        "which",
        "with",
        "your",
    }
)
# Small wording normalization used only to avoid appending a request twice.
_REQUEST_WORD_ALIASES = {
    "photograph": "photo",
    "photographs": "photo",
    "photos": "photo",
}

# A structured agent answer that carries merchant email wording.
EmailWording = InvestigationConclusion | ClaimSplit | RevisionPlan


def finish_email(
    conclusion: EmailWording,
    *,
    recommendation: Recommendation,
    amount: AmountDerivation | None,
    contact_email: str | None,
    requested_details: Sequence[str] = (),
) -> DraftedEmail:
    """Turn the wording the model wrote into the finished draft a representative reviews."""
    subject = conclusion.email_subject
    body = conclusion.email_body
    if subject is None or body is None:
        raise ModelOutputRejectedError(
            "The action needs a merchant email, but the investigation did not draft both its "
            "subject and body."
        )

    _refuse_money_the_model_wrote(conclusion)
    _refuse_wording_that_calls_itself_a_draft(conclusion)

    if recommendation.is_approval:
        # Adding the amount last is deliberate: the figure is money-shaped, so the
        # checks above have to see the model's own words and nothing else.
        figure = _as_money(_payable(amount))
        if AMOUNT_PLACEHOLDER in subject or AMOUNT_PLACEHOLDER in body:
            # Reports drafted under the earlier prompt used a marker. Finish them safely
            # instead of exposing implementation wording to a representative.
            subject = subject.replace(AMOUNT_PLACEHOLDER, figure)
            body = body.replace(AMOUNT_PLACEHOLDER, figure)
        else:
            body = f"{body.rstrip()}\n\nApproved amount: {figure}"
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
        if (
            isinstance(conclusion, InvestigationConclusion)
            and conclusion.recommendation is not Recommendation.REQUEST_INFO
        ):
            # A rule can withhold the model's approval because merchant-fillable evidence
            # is missing. Its approval wording is no longer suitable, so use a small
            # deterministic request instead of telling the merchant they were approved.
            subject = "More information needed for your damage claim"
            body = "We need some additional information before we can complete your claim."
        missing_from_body = [detail for detail in details if not _request_is_covered(detail, body)]
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


def _request_is_covered(detail: str, body: str) -> bool:
    """Recognize a requested detail already expressed naturally in the email body."""
    normalized_detail = " ".join(detail.lower().split())
    normalized_body = " ".join(body.lower().split())
    if normalized_detail in normalized_body:
        return True

    wanted = _request_words(detail)
    if not wanted:
        return False
    units = re.split(r"\n+|(?<=[.!?])\s+", body)
    for unit in units:
        expressed = _request_words(unit)
        shared = wanted & expressed
        required_overlap = 1.0 if len(wanted) < 4 else 0.8
        if len(shared) / len(wanted) >= required_overlap:
            return True
    return False


def _request_words(value: str) -> set[str]:
    """Reduce request wording to the content words used by the coverage check."""
    words: set[str] = set()
    for raw in _REQUEST_WORD_PATTERN.findall(value.replace(chr(0x2019), "'")):
        word = raw.lower().removesuffix("'s")
        if word in _REQUEST_STOP_WORDS:
            continue
        words.add(_REQUEST_WORD_ALIASES.get(word, word))
    return words


def money_the_model_wrote(text: str) -> tuple[str, ...]:
    """Find every piece of text that reads as an amount of money, in order."""
    found: list[str] = []
    for pattern in _MONEY_PATTERNS:
        for match in pattern.finditer(text):
            fragment = match.group(0).strip()
            if fragment not in found:
                found.append(fragment)
    return tuple(found)


def draft_markers_the_model_wrote(text: str) -> tuple[str, ...]:
    """Find every word describing the email as something other than what would be sent."""
    found: list[str] = []
    for match in _DRAFT_MARKER_PATTERN.finditer(text):
        marker = match.group(0)
        if marker not in found:
            found.append(marker)
    return tuple(found)


def name_what_is_missing(findings: Sequence[EvidenceFinding]) -> tuple[str, ...]:
    """Say, in words a merchant can act on, which pieces of evidence still have to arrive."""
    return tuple(MISSING_EVIDENCE_WORDING[kind] for kind in gaps_the_merchant_can_fill(findings))


def _refuse_money_the_model_wrote(conclusion: EmailWording) -> None:
    """Refuse the email if the model put a figure anywhere in it (FR-1.21)."""
    in_subject = money_the_model_wrote(conclusion.email_subject or "")
    in_body = money_the_model_wrote(conclusion.email_body or "")
    if not in_subject and not in_body:
        return
    raise ModelOutputRejectedError(
        "The drafted email contains an amount of money written by the investigation. "
        "Every figure has to be worked out from the invoice, so the email cannot be used.",
        details={"in_subject": list(in_subject), "in_body": list(in_body)},
    )


def _refuse_wording_that_calls_itself_a_draft(conclusion: EmailWording) -> None:
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
    """Hand back the amount to write into the email, or refuse the email for want of one."""
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
    """Write the figure the way a merchant reads it: "$52.00"."""
    return f"${amount.amount_usd.quantize(CENTS, rounding=ROUND_HALF_UP)}"
