"""What the admin panel is sent, and what it sends back.

The panel draws a form, so what it needs for each threshold is more than the
value: a label, the sentence explaining what the value is for, and what sort of
control to draw. All of that is taken out of the policy file itself rather than
written down a second time here, so the two cannot drift apart.

**Every value travels as text, numbers included.** An amount of money must never
become a browser number — a $100.00 cap that comes back as 100.00000000000001 is
exactly the failure this project forbids — and sending whole numbers and
fractions the same way means the screen has one rule to follow rather than two.
The one exception is a yes-or-no, which travels as a yes-or-no. The service is the
only thing that ever reads a number out of what was typed.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, Field

from claim_agent.domain.models import UtcDatetime


class PolicyValueKind(StrEnum):
    """What sort of thing one policy value is, and therefore how it is edited.

    The panel draws a control per kind and nothing else decides that, so this is
    the whole vocabulary between the service and the screen.

    `INTEGER` is a whole number, such as a number of days. `MONEY` is an amount in
    dollars and cents. `FRACTION` is a number between nothing and one, used for a
    confidence level. `TEXT` is words. `CHOICE` is words too, but picked from a list
    the service supplies rather than typed — the claim type we handle is one, because
    it is used as a prefix and a typo would turn every claim away. `BOOLEAN` is a yes
    or no.

    Every claim threshold today is one of these six. A value that is a list — an
    order to work through, say — would need a control of its own here, and none
    exists because nothing needs one.
    """

    INTEGER = "integer"
    MONEY = "money"
    FRACTION = "fraction"
    TEXT = "text"
    CHOICE = "choice"
    BOOLEAN = "boolean"


class PolicyValueBase(BaseModel):
    """What every policy value carries, whatever its kind.

    `name` is the value's name in the policy file, which is also what the panel
    sends back when it changes. `description` is the sentence from that file
    saying what the value is for, and it is the service's own wording — including
    the note that a value is provisional and awaiting ShipBob's sign-off.
    `changed` is true when the value in force is no longer the one the service
    started with.
    """

    name: str
    description: str
    changed: bool


class PolicyValueWritten(PolicyValueBase):
    """A value typed into a box: a number, an amount of money, or some words.

    `value` and `startup_value` are text in every case. See the note at the top of
    this file for why a number is not sent as a number.
    """

    kind: Literal[
        PolicyValueKind.INTEGER,
        PolicyValueKind.MONEY,
        PolicyValueKind.FRACTION,
        PolicyValueKind.TEXT,
    ]
    value: str
    startup_value: str


class PolicyValueChoice(PolicyValueBase):
    """A value picked from a list rather than typed.

    `options` are the choices the panel offers, in the order the service gives
    them, and the panel offers exactly those and no others.

    **The list is what the panel offers, not what the service will accept.** The
    value behind it is ordinary text and the service still takes any string, so a
    claim type set from the environment that is absent from the list is perfectly
    valid — it is simply not something the panel would have suggested. When that
    happens the value in force is included in `options` anyway, because a control
    that cannot show what is currently set would quietly change it the moment
    somebody saved the form.
    """

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
"""One policy value, whichever of the three shapes it takes.

`kind` says which shape it is, so a reader — a screen included — can tell them
apart by looking at that one field rather than guessing from what is present.
"""


class PolicyView(BaseModel):
    """The whole claim policy as the panel sees it.

    `values` are in the order they are declared in the policy file, so the form
    reads the way the file does. `changed_at` is when the values in force last
    genuinely changed, and is `None` when they are still the ones the service
    started with. `matches_startup` says the same thing about the values
    themselves, which is what decides whether there is anything to reset.
    """

    values: tuple[PolicyValue, ...]
    changed_at: UtcDatetime | None
    matches_startup: bool


class PolicyUpdate(BaseModel):
    """A change to the claim policy, as the panel submits it.

    `values` holds a value per name — the panel sends the whole form, but a
    caller may send only the names it wants to change; anything left out keeps
    the value it already has.

    A list is still accepted here, and is refused by the policy rather than by this
    shape. Nothing has a list for a value today, so a caller sending one has the
    wrong name or the wrong idea, and the reply says which.

    Money and numbers arrive as text, on purpose. See the note at the top of this
    file.
    """

    values: dict[str, str | bool | list[str]]


class ForgottenCorrections(BaseModel):
    """How many merchant corrections an operator has just thrown away.

    A count rather than nothing at all, because "it worked" and "there was nothing there" look
    identical on a screen otherwise, and somebody clearing a store before a demonstration wants
    to know which of the two happened.
    """

    forgotten: int
