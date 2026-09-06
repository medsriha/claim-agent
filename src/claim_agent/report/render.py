from __future__ import annotations

from collections.abc import Sequence
from decimal import ROUND_HALF_UP, Decimal

from claim_agent.agent.investigate import ClaimFindings
from claim_agent.domain.assessment import Assessment
from claim_agent.domain.decision import Proposal, RepAction
from claim_agent.domain.evidence import EvidenceFinding
from claim_agent.domain.models import Case, DraftedEmail, MerchantCorrection
from claim_agent.domain.outcome import Recommendation
from claim_agent.domain.reimbursement import CENTS, AmountDerivation
from claim_agent.preflight.models import ClaimContext, GateResult, TerminalReport
from claim_agent.report.models import EmailWording

_RECOMMENDATION_IN_WORDS: dict[Recommendation, str] = {
    Recommendation.APPROVE: "Approve — pay this product",
    Recommendation.APPROVE_HIGH_VALUE: (
        "Approve, and take a second look — pay this product, but the damaged goods are high value"
    ),
    Recommendation.REQUEST_INFO: "Request information — go back to the merchant",
    Recommendation.REQUEST_REP_CLARIFICATION: (
        "Representative clarification needed — resolve what is incorrect or ambiguous"
    ),
}
"""Each recommendation as a heading a representative reads, rather than as its stored name."""

_ACTION_IN_WORDS: dict[RepAction, str] = {
    RepAction.APPROVED: "approved this report as it stood",
    RepAction.APPROVED_WITH_OVERRIDE: "approved this report, having changed it",
    RepAction.SENT_BACK: "sent this report back",
}
"""What a representative did, written the way somebody reading the report afterwards would say it."""


def render_investigated_claim(
    *,
    findings: ClaimFindings,
    context: ClaimContext,
    case: Case,
) -> str:
    """Write the report for a claim that was investigated (FR-2.1 to FR-2.7)."""
    sections = [
        _title(f"Damaged: {_products(findings)}", case),
        _what_is_recommended(findings),
        _concerns(findings.concerns),
        _claim_context(context, considered=_corrections_considered(findings)),
        _evidence(findings.evidence),
        _assessments(findings.assessments),
        _how_the_amount_was_reached(findings.amount, findings.outcome.recommendation),
        _the_merchant_email(findings.drafted_email),
    ]
    return "\n\n".join(section for section in sections if section)


def render_stopped_claim(report: TerminalReport, *, case: Case) -> str:
    """Write the report for a claim the quick checks turned away (FR-0.4, FR-2.5)."""
    sections = [
        _title("Claim stopped before investigation", case),
        _why_the_claim_was_stopped(report),
        _concerns(report.findings),
        _claim_context(report.context, considered=()),
        _the_four_checks(report.gates),
        _the_merchant_email(
            report.drafted_email,
            needs_rep_clarification=report.requires_rep_clarification,
        ),
    ]
    return "\n\n".join(section for section in sections if section)


def render_what_the_representative_decided(
    *,
    review_number: int,
    action: RepAction,
    recommended: Proposal,
    decided: Proposal,
    edited_email: EmailWording | None,
    rep_words: str | None,
    over_the_cap_by: Decimal | None,
) -> str:
    """Write the section added to a report when somebody acts on it (FR-2.8, FR-C.1)."""
    lines = [
        f"## Review {review_number} — what the representative decided",
        "",
        f"A representative {_ACTION_IN_WORDS[action]}.",
    ]

    changes = []
    if recommended.outcome != decided.outcome:
        changes.append(
            f"- **Outcome changed** — the system recommended `{recommended.outcome}`, "
            f"and the representative decided `{decided.outcome}`."
        )
    if recommended.amount_usd != decided.amount_usd:
        changes.append(
            f"- **Amount changed** — the system worked out {_money(recommended.amount_usd)}, "
            f"and the representative decided {_money(decided.amount_usd)}."
        )
    if edited_email is not None:
        changes.append("- **The merchant's email was reworded** before it was approved.")
    if changes:
        lines += ["", *changes]

    if over_the_cap_by is not None:
        lines += [
            "",
            f"> **This is {_money(over_the_cap_by)} over the most the system may recommend on "
            "one claim.** The limit is on what the system recommends, not on what a person may "
            "decide, so the decision stands as it was made and is recorded here.",
        ]

    if rep_words:
        lines += ["", "In their own words:", "", f"> {rep_words}"]

    if edited_email is not None:
        lines += [
            "",
            "### The merchant's email, as reworded",
            "",
            "```text",
            f"Subject: {edited_email.subject}",
            "",
            edited_email.body,
            "```",
        ]

    return "\n".join(lines)


def _title(heading: str, case: Case) -> str:
    """Say which claim this is and whose it is, before anything else (FR-2.9a)."""
    merchant = case.account_name or "an unnamed merchant"
    return f"# {heading}\n\nClaim `{case.case_id}`, for {merchant}."


def _products(findings: ClaimFindings) -> str:
    """Every damaged product on the claim, named in the heading (FR-2.9a)."""
    if not findings.lines:
        return "no product established"
    return ", ".join(line.product_name for line in findings.lines)


def _what_is_recommended(findings: ClaimFindings) -> str:
    """Lead with the recommendation, the figure, and how the rules got there (FR-2.1, NFR-3)."""
    recommended = _RECOMMENDATION_IN_WORDS[findings.outcome.recommendation]
    lines = ["## Recommendation", "", f"**{recommended}.**"]

    if findings.outcome.recommendation.is_approval:
        lines += ["", f"**Amount recommended: {_money(findings.amount.amount_usd)}.**"]

    lines += ["", findings.outcome.explanation]

    if findings.outcome.was_overridden:
        stepped_in = ", ".join(_in_words(str(reason)) for reason in findings.outcome.overrides)
        lines += [
            "",
            f"The investigation itself recommended `{findings.outcome.recommended_by_agent}`. "
            f"Rules that stepped in: {stepped_in}.",
        ]

    lines += [
        "",
        "*This is a recommendation. Nothing is sent and nothing is paid until you approve it.*",
    ]
    return "\n".join(lines)


def _concerns(concerns: Sequence[str]) -> str:
    """Say what is weak, conflicting or uncertain, or say plainly that nothing was (FR-2.5)."""
    if not concerns:
        return "## Concerns\n\nNothing was flagged as weak, conflicting or uncertain."
    listed = "\n".join(f"- {concern}" for concern in concerns)
    return f"## Concerns\n\n{listed}"


def _claim_context(context: ClaimContext, *, considered: Sequence[str]) -> str:
    """Surface what a representative should know before approving (FR-2.6)."""
    lines = ["## The claim in context", ""]

    if context.order_value_usd is None:
        lines.append("- **Order value** — the order could not be read, so its value is unknown.")
    else:
        worth = _money(context.order_value_usd)
        care = " This counts as a high-value order." if context.is_high_value else ""
        lines.append(f"- **Order value** — {worth}.{care}")

    if context.days_since_delivery is None:
        lines.append("- **Age** — no delivery date is known, so the claim's age is unknown.")
    else:
        lines.append(f"- **Age** — filed {context.days_since_delivery} day(s) after delivery.")

    lines.append("")
    lines.append(_merchant_corrections(context.merchant_corrections, considered=considered))
    return "\n".join(lines)


def _merchant_corrections(
    corrections: Sequence[MerchantCorrection], *, considered: Sequence[str]
) -> str:
    """List what representatives have already corrected for this merchant (FR-2.6, FR-3.8)."""
    if not corrections:
        return "**Past corrections for this merchant:** none on file."

    lines = ["**Past corrections for this merchant:**", ""]
    for correction in corrections:
        used = " *(this one changed the conclusion)*" if correction.case_id in considered else ""
        lines.append(f"- Claim `{correction.case_id}` — {correction.summary}{used}")
    return "\n".join(lines)


def _evidence(findings: Sequence[EvidenceFinding]) -> str:
    """Show all four pieces of evidence, each naming the image it came from (FR-2.2)."""
    rows = [
        "| Evidence | Found? | From image | What was seen | Problem |",
        "| --- | --- | --- | --- | --- |",
    ]
    for finding in findings:
        rows.append(
            f"| {_in_words(str(finding.kind))} "
            f"| {_in_words(str(finding.state))} "
            f"| {_or_dash(finding.attachment_id)} "
            f"| {_cell(finding.observed)} "
            f"| {_cell(finding.problem)} |"
        )
    return "## The evidence\n\n" + "\n".join(rows)


def _assessments(assessments: Sequence[Assessment]) -> str:
    """Show each question the investigation answered, and why (FR-2.3)."""
    if not assessments:
        return (
            "## The four questions\n\n"
            "None of the four questions was answered. The investigation did not get that far, "
            "which is not the same as answering no to any of them."
        )

    rows = [
        "| Question | Answer | Why |",
        "| --- | --- | --- |",
    ]
    for assessment in assessments:
        answer = "Yes" if assessment.passed else "No"
        rows.append(
            f"| {_in_words(str(assessment.name))} | {answer} | {_cell(assessment.reasoning)} |"
        )

    note = ""
    if len(assessments) < 4:
        note = (
            "\n\nOnly "
            f"{len(assessments)} of the four questions was answered. A question missing here was "
            "never answered, which is not the same as being answered no."
        )
    return "## The four questions\n\n" + "\n".join(rows) + note


def _how_the_amount_was_reached(amount: AmountDerivation, recommended: Recommendation) -> str:
    """Show which items at which prices, from which document, and what the cap did (FR-2.4)."""
    lines = ["## How the amount was reached", ""]

    if recommended.is_approval:
        lines.append(f"**{_money(amount.amount_usd)}.**")
    else:
        lines.append(
            f"Nothing would be paid on this recommendation. Had it been approved, the "
            f"investigation put the damage at {_money(amount.proposed_usd)}."
        )
    lines.append("")

    if amount.reasoning:
        lines += [amount.reasoning, ""]

    if amount.components:
        rows = [
            "| Product | How many | Price each | Line total |",
            "| --- | --- | --- | --- |",
        ]
        for component in amount.components:
            rows.append(
                f"| {_cell(component.product_name)} "
                f"| {component.quantity} "
                f"| {_money(component.unit_price)} "
                f"| {_money(component.line_total)} |"
            )
        lines += rows
        lines += ["", f"What the items cost between them: {_money(amount.items_total_usd)}."]
    else:
        lines.append("No item on the order could be priced for this product.")

    lines.append("")
    lines.append(
        f"Priced from invoice `{amount.priced_from}`."
        if amount.priced_from
        else "There was no invoice to price it from."
    )
    lines.append("")
    lines.append(
        f"The investigation proposed {_money(amount.proposed_usd)}, and the most that may be "
        f"recommended on one claim is {_money(amount.cap_usd)}. "
        + (
            "That limit changed the answer."
            if amount.cap_applied
            else "That limit did not change the answer."
        )
    )
    return "\n".join(lines)


def _the_merchant_email(
    email: DraftedEmail | None, *, needs_rep_clarification: bool = False
) -> str:
    """Show the exact wording that would go to the merchant, and nothing else (FR-2.7)."""
    if email is None:
        if needs_rep_clarification:
            return (
                "## The merchant's email\n\n"
                "There is none. This claim is routed out rather than answered, and no email "
                "explains that to a merchant."
            )
        return (
            "## The merchant's email\n\n"
            "There is none. Nothing was written, or what was written was refused, so what the "
            "merchant is told is yours to decide."
        )

    to = email.to or "**no address on the claim — this cannot be sent**"
    return (
        "## The merchant's email\n\n"
        f"To: {to}\n\n"
        'This is a draft. It has not been sent, and the word "draft" is deliberately absent '
        "from the wording itself so no such marker can ever reach a merchant.\n\n"
        "```text\n"
        f"Subject: {email.subject}\n\n"
        f"{email.body}\n"
        "```"
    )


def _why_the_claim_was_stopped(report: TerminalReport) -> str:
    """Lead a stopped claim's report with every reason it was stopped (FR-0.3, FR-0.4)."""
    reasons = "\n".join(f"- {_in_words(str(reason))}" for reason in report.reasons)
    lines = ["## Why this claim was stopped", "", reasons]
    if report.requires_rep_clarification:
        lines += [
            "",
            "**This claim has to be routed out rather than answered.** The parcel was insured, "
            "and an insured parcel is claimed on its insurance through a process that is not "
            "ours.",
        ]
    lines += ["", "*This is a recommendation. Nothing is sent until you approve it.*"]
    return "\n".join(lines)


def _the_four_checks(gates: Sequence[GateResult]) -> str:
    """Show all four checks, passed and failed alike (FR-0.3, NFR-3)."""
    rows = ["| Check | Passed? | What it found |", "| --- | --- | --- |"]
    for gate in gates:
        rows.append(
            f"| {_in_words(str(gate.gate))} "
            f"| {'Yes' if gate.passed else 'No'} "
            f"| {_cell(gate.explanation)} |"
        )

    looked_at = ["", "What the checks looked at:", ""]
    for gate in gates:
        for name, value in sorted(gate.observed.items()):
            looked_at.append(f"- `{name}` — {_cell(value)}")

    return "## The four checks\n\n" + "\n".join(rows) + "\n" + "\n".join(looked_at)


def _money(amount: Decimal | None) -> str:
    """Write an exact amount as a person would read it."""
    if amount is None:
        return "no amount"
    return f"${amount.quantize(CENTS, ROUND_HALF_UP)}"


def _in_words(name: str) -> str:
    """Write a stored name as words: `outer_packaging_photo` as \"outer packaging photo\"."""
    return name.replace("_", " ")


def _cell(value: str | None) -> str:
    """Put a sentence inside a table cell without letting it break the table."""
    if not value:
        return "—"
    return value.replace("|", "\\|").replace("\n", " ")


def _or_dash(value: str | None) -> str:
    """Write an absent value as a dash, so a blank cell never reads as a mistake."""
    return f"`{value}`" if value else "—"


def _corrections_considered(findings: ClaimFindings) -> tuple[str, ...]:
    """Which earlier claims' corrections the investigation says changed its conclusion (FR-2.6)."""
    if findings.conclusion is None:
        return ()
    return findings.conclusion.corrections_considered
