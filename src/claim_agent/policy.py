"""Claim policy values — the single named place they live (FR-0.7, NFR-7).

Every value here is a lever an operator may need to change without touching
logic, so each is overridable with a `POLICY_`-prefixed environment variable.

`reimbursement_cap_usd` is stated in REQUIREMENTS.md (FR-1.20). The rest are
judgement calls that REQUIREMENTS.md explicitly leaves unspecified: the defaults
below are provisional placeholders and need ShipBob sign-off before production.

**Some values are marked `NOT_ON_PANEL`.** The admin panel is built from this
file, so by default a value here is a value someone can change from a screen
while the service runs. That is only useful for a value the running service
actually reads: seven of the ones marked belong to the AI investigation, which is
being built and is not yet reachable, so changing them from a panel would do
nothing observable and would suggest otherwise. Once the investigation runs, they
are the marks to revisit. The marking changes nothing about the value itself —
every one of them is still read, still overridable from the environment, and
still used wherever it is used.
"""

from __future__ import annotations

from decimal import Decimal
from functools import lru_cache

from pydantic import Field, JsonValue
from pydantic_settings import BaseSettings, SettingsConfigDict

# The claim types ShipBob is known to use. Exactly one, because exactly one is quoted in
# REQUIREMENTS.md, and the document listing the rest is not in this repository. There are
# certainly others; we do not know what they are, so they are not listed here. Adding a
# guess would put a claim type on screen that nobody has confirmed exists.
#
# This constrains the choice offered on the admin panel and nothing else. The value itself
# stays free text, so `POLICY_DAMAGED_IN_TRANSIT_SUB_CATEGORY` can still be set to a claim
# type absent from this list — which is how a real one would be configured before anyone
# gets round to adding it here. A list this short must not be able to make a real claim
# type impossible to handle.
KNOWN_CLAIM_SUB_CATEGORIES = ("Claim | Damaged in Transit",)


NOT_ON_PANEL: dict[str, JsonValue] = {"editable_in_panel": False}
"""Marks a value the admin panel neither shows nor accepts a change to.

Written beside the value it applies to, rather than kept as a list somewhere
else, so that a reader of this file can see which values reach a screen and the
two can never drift apart.
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
    uninsured_refund_percentage: int = Field(
        default=60,
        ge=0,
        le=100,
        description="Percentage of a damaged item's price that is refunded on an uninsured "
        "shipment. Applied to each item before the reimbursement cap is checked "
        "(FR-1.19, FR-1.20). PROVISIONAL.",
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
        # Offered as a choice on the panel rather than typed, because a claim type is
        # matched exactly and a typo here turns every claim away. Still a plain string, so
        # the environment can set one this list has never seen.
        json_schema_extra={"options": list(KNOWN_CLAIM_SUB_CATEGORIES)},
    )
    min_description_length: int = Field(
        default=1,
        ge=1,
        description="Shortest description that counts as present, after trimming spaces "
        "(FR-0.2). PROVISIONAL.",
        json_schema_extra=NOT_ON_PANEL,
    )
    # The seven below are read by the AI investigation, which is being built but is not
    # yet reachable over HTTP. Nothing a running service does looks at them, so a panel
    # offering them would be offering a change nobody could see the effect of. When the
    # investigation is reachable, these markings are the ones to take off.
    min_assessment_confidence: float = Field(
        default=0.7,
        ge=0.0,
        le=1.0,
        description="Below this, recommend escalate rather than approve (FR-1.15). PROVISIONAL.",
        json_schema_extra=NOT_ON_PANEL,
    )
    max_agent_steps: int = Field(
        default=12,
        gt=0,
        description="Per-run step budget; exhaustion escalates (FR-1.3, FR-1.16). PROVISIONAL.",
        json_schema_extra=NOT_ON_PANEL,
    )
    max_tool_retries: int = Field(
        default=2,
        ge=0,
        description="Retries per tool call before failing toward the rep (FR-1.3). PROVISIONAL.",
        json_schema_extra=NOT_ON_PANEL,
    )
    max_image_analyses_per_run: int = Field(
        default=20,
        gt=0,
        description="Most images one run may look at, whatever its step budget allows. Looking "
        "at an image is the costliest thing the system does (NFR-8). PROVISIONAL.",
        json_schema_extra=NOT_ON_PANEL,
    )
    precedent_results_per_line: int = Field(
        default=5,
        gt=0,
        description="Most similar past claims shown to the investigation, per product "
        "(FR-S.5). Every one costs the model something to read, and a long list buries the "
        "closest match among weaker ones. PROVISIONAL.",
        json_schema_extra=NOT_ON_PANEL,
    )
    min_precedent_similarity: float = Field(
        default=0.35,
        ge=0.0,
        le=1.0,
        description="How alike a past claim must be to be shown at all, from 0 to 1 (FR-S.5). "
        "Too low and unrelated claims are offered as precedent, which is worse than offering "
        "none. PROVISIONAL.",
        json_schema_extra=NOT_ON_PANEL,
    )
    cap_applies_to_whole_claim: bool = Field(
        default=True,
        description="Whether the reimbursement cap limits the whole claim as well as each line. "
        "REQUIREMENTS.md open question 2; when true, lines summing above the cap are escalated "
        "rather than trimmed (FR-1.20). PROVISIONAL.",
        json_schema_extra=NOT_ON_PANEL,
    )


@lru_cache
def get_policy() -> Policy:
    """Return the claim policy for this process.

    Cached like the settings: read once, so a threshold cannot change midway through
    judging a claim.
    """
    return Policy()
