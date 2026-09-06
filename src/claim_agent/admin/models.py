from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, Field

from claim_agent.domain.models import UtcDatetime


class PolicyValueKind(StrEnum):
    """What sort of thing one policy value is, and therefore how it is edited."""

    INTEGER = "integer"
    MONEY = "money"
    FRACTION = "fraction"
    TEXT = "text"
    CHOICE = "choice"
    BOOLEAN = "boolean"


class PolicyValueBase(BaseModel):
    """What every policy value carries, whatever its kind."""

    name: str
    description: str
    changed: bool


class PolicyValueWritten(PolicyValueBase):
    """A value typed into a box: a number, an amount of money, or some words."""

    kind: Literal[
        PolicyValueKind.INTEGER,
        PolicyValueKind.MONEY,
        PolicyValueKind.FRACTION,
        PolicyValueKind.TEXT,
    ]
    value: str
    startup_value: str


class PolicyValueChoice(PolicyValueBase):
    """A value picked from a list rather than typed."""

    kind: Literal[PolicyValueKind.CHOICE]
    value: str
    startup_value: str
    options: tuple[str, ...]


class PolicyValueYesNo(PolicyValueBase):
    """A value that is either yes or no, such as whether the last day still counts."""

    kind: Literal[PolicyValueKind.BOOLEAN]
    value: bool
    startup_value: bool


PolicyValue = Annotated[
    PolicyValueWritten | PolicyValueChoice | PolicyValueYesNo,
    Field(discriminator="kind"),
]
"""One policy value, whichever of the three shapes it takes."""


class PolicyView(BaseModel):
    """The whole claim policy as the panel sees it."""

    values: tuple[PolicyValue, ...]
    changed_at: UtcDatetime | None
    matches_startup: bool


class PolicyUpdate(BaseModel):
    """A change to the claim policy, as the panel submits it."""

    values: dict[str, str | bool | list[str]]
