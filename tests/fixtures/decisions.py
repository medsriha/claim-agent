"""Building decision records for tests.

Every field has a default that makes a plain, agreed-with, investigated decision, so a test names
only the thing it is about. A test that wants a representative to have changed something says so
and says nothing else.

**All of it is invented**, like everything else under `tests/fixtures`. Nothing in the running
system writes a decision yet.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from claim_agent.domain.decision import DecisionRecord, DecisionStage, Proposal, RepAction
from claim_agent.domain.outcome import Recommendation

A_MOMENT = datetime(2026, 3, 21, 10, 4, 11, tzinfo=UTC)
"""The moment FR-C.1's own reference record was decided at."""


def investigated(**overrides: Any) -> DecisionRecord:
    """One investigated claim a representative approved exactly as it stood."""
    fields: dict[str, Any] = {
        "decision_id": "DEC-CASE-9001-01",
        "case_id": "CASE-9001",
        "stage": DecisionStage.INVESTIGATION,
        "report_version": 1,
        "action": RepAction.APPROVED,
        "recommended": Proposal(outcome=Recommendation.APPROVE, amount_usd=Decimal("31.20")),
        "decided": Proposal(outcome=Recommendation.APPROVE, amount_usd=Decimal("31.20")),
        "email_edited": False,
        "stated_confidence": 0.9,
        "order_value_usd": Decimal("52.00"),
        "defect_type": "Both product and shipping box damaged",
        "damage_type": "Damage due to poor/bad packaging",
        "carrier": "Royal Mail Tracked 48",
        "rep_minutes": 8,
        "rep_words": None,
        "decided_by": None,
        "decided_at": A_MOMENT,
    }
    fields.update(overrides)
    return DecisionRecord(**fields)


def screened(**overrides: Any) -> DecisionRecord:
    """One claim the quick checks stopped, approved as it stood.

    No outcome on either side, and no statement of how sure anything was — a stopped claim
    never reaches the AI (FR-C.1).
    """
    fields: dict[str, Any] = {
        "decision_id": "DEC-CASE-9002-01",
        "case_id": "CASE-9002",
        "stage": DecisionStage.SCREENING,
        "report_version": 1,
        "action": RepAction.APPROVED,
        "recommended": Proposal(outcome=None, amount_usd=None),
        "decided": Proposal(outcome=None, amount_usd=None),
        "email_edited": False,
        "stated_confidence": None,
        "order_value_usd": Decimal("52.00"),
        "defect_type": "Both product and shipping box damaged",
        "damage_type": "Damage due to poor/bad packaging",
        "carrier": "Royal Mail Tracked 48",
        "rep_minutes": 3,
        "rep_words": None,
        "decided_by": None,
        "decided_at": A_MOMENT,
    }
    fields.update(overrides)
    return DecisionRecord(**fields)
