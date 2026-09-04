"""Claim policy values — the single named place they live (FR-0.7, NFR-7).

Every value here is a lever an operator may need to change without touching
logic, so each is overridable with a `POLICY_`-prefixed environment variable.

`reimbursement_cap_usd` is stated in REQUIREMENTS.md (FR-1.20). The rest are
judgement calls that REQUIREMENTS.md explicitly leaves unspecified: the defaults
below are provisional placeholders and need ShipBob sign-off before production.
"""

from __future__ import annotations

from decimal import Decimal
from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from claim_agent.domain.models import TerminalReason

DEFAULT_TERMINAL_REASON_PRECEDENCE = (
    TerminalReason.SHIPMENT_INSURED,
    TerminalReason.CLAIM_TOO_OLD,
    TerminalReason.WRONG_CLAIM_TYPE,
    TerminalReason.MISSING_KEY_INFORMATION,
)
"""Which reason to lead with when a claim fails several checks at once.

Insurance comes first because an insured claim belongs to a different process
entirely, and telling a merchant "too old" instead of "claim on your insurance"
sends them the wrong way. Missing information comes last on purpose: it is the
only recoverable reason, and asking a merchant for photos on a claim being closed
for age wastes their time. This order is our judgement, not a ShipBob rule.
"""


class Policy(BaseSettings):
    """Thresholds and limits applied to every claim."""

    model_config = SettingsConfigDict(
        env_prefix="POLICY_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Stated by REQUIREMENTS.md.
    reimbursement_cap_usd: Decimal = Field(
        default=Decimal("100.00"),
        description="Maximum reimbursement (FR-1.20).",
    )

    # Provisional — not specified by ShipBob.
    max_claim_age_days: int = Field(
        default=60,
        description="Age gate: days from delivery to case creation (FR-0.2). PROVISIONAL.",
    )
    age_limit_inclusive: bool = Field(
        default=True,
        description="Whether a claim filed exactly on the limit still passes (FR-0.2). PROVISIONAL.",
    )
    high_value_order_usd: Decimal = Field(
        default=Decimal("500.00"),
        description="Order value at which a shipment is flagged high-value (FR-0.5). PROVISIONAL.",
    )
    high_value_inclusive: bool = Field(
        default=True,
        description="Whether an order landing exactly on the threshold counts as high value "
        "(FR-0.5). PROVISIONAL.",
    )
    damaged_in_transit_sub_category: str = Field(
        default="Claim | Damaged in Transit",
        description="The only claim type handled here, matched exactly (FR-0.2). PROVISIONAL.",
    )
    min_description_length: int = Field(
        default=1,
        ge=1,
        description="Shortest description that counts as present, after trimming spaces "
        "(FR-0.2). PROVISIONAL.",
    )
    terminal_reason_precedence: tuple[TerminalReason, ...] = Field(
        default=DEFAULT_TERMINAL_REASON_PRECEDENCE,
        description="Order terminal reasons are ranked in; the first one heads the merchant "
        "email (FR-0.2, FR-0.4). PROVISIONAL.",
    )
    min_assessment_confidence: float = Field(
        default=0.7,
        ge=0.0,
        le=1.0,
        description="Below this, recommend escalate rather than approve (FR-1.15). PROVISIONAL.",
    )
    max_agent_steps: int = Field(
        default=12,
        gt=0,
        description="Per-run step budget; exhaustion escalates (FR-1.3, FR-1.16). PROVISIONAL.",
    )
    max_tool_retries: int = Field(
        default=2,
        ge=0,
        description="Retries per tool call before failing toward the rep (FR-1.3). PROVISIONAL.",
    )

    @field_validator("terminal_reason_precedence")
    @classmethod
    def _must_rank_every_reason(
        cls, value: tuple[TerminalReason, ...]
    ) -> tuple[TerminalReason, ...]:
        """Refuse an order that leaves a reason out or lists one twice.

        Every reason has to appear exactly once, or a claim could fail a check whose
        reason has nowhere to sit in the ranking. The result would depend on the order
        the checks happened to run in, which is the one thing FR-0.6 rules out.
        """
        if sorted(value) != sorted(TerminalReason):
            missing = sorted(set(TerminalReason) - set(value))
            raise ValueError(
                "terminal_reason_precedence must list each terminal reason exactly once; "
                f"got {list(value)}, missing {missing}"
            )
        return value


@lru_cache
def get_policy() -> Policy:
    """Return the claim policy for this process.

    Cached like the settings: read once, so a threshold cannot change midway through
    judging a claim.
    """
    return Policy()
