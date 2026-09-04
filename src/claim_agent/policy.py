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

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


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
    high_value_order_usd: Decimal = Field(
        default=Decimal("500.00"),
        description="Order value at which a shipment is flagged high-value (FR-0.5). PROVISIONAL.",
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


@lru_cache
def get_policy() -> Policy:
    """Return the process-wide policy, read once."""
    return Policy()
