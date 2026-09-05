from __future__ import annotations

from decimal import Decimal
from typing import Final

REP_HOURLY_RATE_USD: Final = Decimal("50.00")
"""What an hour of a support representative's time is taken to cost. PROVISIONAL."""

REP_HOURLY_RATE_DESCRIPTION: Final = (
    "Assumed fully loaded cost of one support representative hour, including employment costs. "
    "The dashboard multiplies estimated hours saved by this rate. PROVISIONAL — this estimate "
    "was set by this project, not supplied by ShipBob."
)

AI_COST_PER_CLAIM_USD: Final = Decimal("0.42")
"""What investigating one claim with the AI is taken to cost. PROVISIONAL."""

AI_COST_PER_CLAIM_DESCRIPTION: Final = (
    "Estimated AI model and image-processing cost for one investigated product. Claims stopped "
    "by eligibility checks do not incur this cost. PROVISIONAL — this estimate was set by this "
    "project, not supplied by ShipBob."
)

MANUAL_MINUTES_PER_INVESTIGATION: Final = 22
"""Whole minutes one investigated product would take a person working alone. PROVISIONAL."""

MANUAL_MINUTES_PER_INVESTIGATION_DESCRIPTION: Final = (
    "Assumed time for a representative to investigate one damaged product without AI assistance. "
    "Estimated time saved is this amount minus the recorded review time. PROVISIONAL — the "
    "manual process has not been timed."
)

MANUAL_MINUTES_PER_SCREENING: Final = 6
"""Whole minutes one stopped claim would take a person working alone. PROVISIONAL."""

MANUAL_MINUTES_PER_SCREENING_DESCRIPTION: Final = (
    "Assumed time for a representative to identify and close an ineligible claim without the "
    "automated checks. PROVISIONAL — the manual process has not been timed."
)

# Each band as (name, lower edge, upper edge). The upper edge is excluded, except on the last
# band, where it is included so that a claim the system was completely sure of has somewhere to
# go. `band_for` in `performance.py` is the one place that rule is applied.
#
# The lowest edge is 0.70 because that is the level below which the system already refuses to
# recommend paying (FR-1.15), so the bottom band is "claims the rules would have withheld
# anyway". The bands above it split what is left into three, which is enough to see a trend and
# few enough that each one holds a meaningful number of claims.
#
# These do not follow the policy value if somebody changes it from the admin panel. That is a
# simplification: a report covering a year would otherwise re-bucket its whole history the moment
# a threshold moved, and the bands would stop meaning one thing.
CONFIDENCE_BANDS: Final = (
    ("below_the_bar", 0.0, 0.70),
    ("fair", 0.70, 0.85),
    ("high", 0.85, 0.95),
    ("very_high", 0.95, 1.0),
)

# The order value bands the candidate gates are scored over.
#
# The edges are the two figures the requirements already treat as meaningful: $100 is the most
# that may be reimbursed on one claim (FR-1.20), and $500 is where an order is called high value
# (FR-0.5). So the bands are "smaller than anything we could pay out", "in between", and "the
# ones already flagged for extra care". FR-C.7 asks whether that last group should be held to a
# stricter standard and leaves the question open; scoring the bands separately is how somebody
# would answer it.
VALUE_BANDS: Final = (
    ("under_100", None, Decimal("100.00")),
    ("100_to_500", Decimal("100.00"), Decimal("500.00")),
    ("500_and_over", Decimal("500.00"), None),
)

MINIMUM_AGREEMENT_FOR_A_GATE: Final = 0.95
"""How often representatives must have agreed before a gate is worth discussing. PROVISIONAL."""

MINIMUM_DECISIONS_FOR_A_GATE: Final = 200
"""How many decisions a gate must be scored on before the figure means anything. PROVISIONAL."""

GATE_BAR_DESCRIPTION: Final = (
    "A candidate rule is only worth discussing if representatives agreed with the system at least "
    "95% of the time across at least 200 decisions. Both numbers are ours and neither has been "
    "agreed with anyone. Meeting the bar is not permission: FR-2.9 says a person approving is the "
    "only way a claim can be released, and no figure on this screen changes that. PROVISIONAL."
)
