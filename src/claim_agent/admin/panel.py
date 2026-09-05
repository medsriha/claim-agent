from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal
from typing import Any

from pydantic import ValidationError
from pydantic.fields import FieldInfo

from claim_agent.admin.models import (
    PolicyUpdate,
    PolicyValue,
    PolicyValueChoice,
    PolicyValueKind,
    PolicyValueWritten,
    PolicyValueYesNo,
    PolicyView,
)
from claim_agent.errors import InvalidRequestError
from claim_agent.live_policy import LivePolicy
from claim_agent.policy import Policy

# Pydantic puts this in front of the message from any rule we wrote ourselves. The
# rest of the sentence is our own wording and is meant to be read by a person, so
# the prefix comes off before it reaches a screen.
_PYDANTIC_VALUE_ERROR_PREFIX = "Value error, "


def describe_policy(live: LivePolicy) -> PolicyView:
    """Set out every claim threshold as the panel needs to see it.

    Args:
        live: The policy in force, which also knows the values the service started
            with — the panel shows both, so someone can see what they have changed.

    Returns:
        One entry per value the panel offers, in the order the policy file declares
        them, plus when the policy last changed and whether it still matches what
        the service started with. A value the policy file marks as off-panel is left
        out entirely, and a change to one is refused.

    Raises:
        TypeError: A value in the policy file is of a sort the panel has no control
            for. That is a mistake in our own code rather than anything a caller
            did, and a test covers every value so it cannot reach a running
            service quietly.
    """
    current = live.current()
    startup = live.startup_policy
    return PolicyView(
        values=tuple(
            _describe_value(name, field, getattr(current, name), getattr(startup, name))
            for name, field in Policy.model_fields.items()
            if _offered_on_the_panel(field)
        ),
        changed_at=live.changed_at,
        matches_startup=current == startup,
    )


def revise_policy(current: Policy, update: PolicyUpdate) -> Policy:
    """Work out the policy that submitting this form should produce.

    What arrives is laid over the values in force, and the result is checked as a
    whole — the same checking a policy gets when the service starts, so a number
    outside its allowed range is refused here exactly as it would be there.

    Nothing is put in force by this function. It either returns a policy the caller
    may install, or raises, and a caller that never installs anything leaves the
    thresholds exactly as they were.

    Args:
        current: The policy in force. Anything the form leaves out keeps its value
            from here, so a caller may submit one value without restating the rest.
        update: The values submitted, by name.

    Returns:
        A complete, valid policy.

    Raises:
        InvalidRequestError: A name that is not a policy value, or a value the
            policy will not accept. Carries one complaint per value in its
            details, under `values`, so a panel can show each one beside the box it
            belongs to.
    """
    # Unknown names have to be caught here rather than left to the policy itself:
    # it is configured to ignore anything it does not recognise, so a misspelled
    # name would otherwise be accepted and then quietly do nothing.
    unknown = [name for name in update.values if name not in Policy.model_fields]
    if unknown:
        raise InvalidRequestError(
            _no_such_value_message(unknown),
            details={
                "values": [
                    {"name": name, "message": "The claim policy has no value with this name."}
                    for name in unknown
                ]
            },
        )

    # A value the panel does not show is refused rather than quietly accepted. Leaving
    # it off the screen but honouring it here would make the omission cosmetic: anyone
    # sending the request by hand could still change it, which is not what being off
    # the panel is meant to mean.
    off_panel = [
        name for name in update.values if not _offered_on_the_panel(Policy.model_fields[name])
    ]
    if off_panel:
        raise InvalidRequestError(
            _not_on_the_panel_message(off_panel),
            details={
                "values": [
                    {
                        "name": name,
                        "message": (
                            "This value cannot be changed while the service is running. It is "
                            "read from the environment when the service starts."
                        ),
                    }
                    for name in off_panel
                ]
            },
        )

    merged: dict[str, Any] = {**current.model_dump(), **update.values}
    try:
        return Policy(**merged)
    except ValidationError as failure:
        problems = _problems_from(failure)
        raise InvalidRequestError(
            _rejected_message([problem["name"] for problem in problems]),
            details={"values": problems},
        ) from failure


def _describe_value(
    name: str, field: FieldInfo, value: object, startup_value: object
) -> PolicyValue:
    """Describe one threshold: what it is called, what it means, and what it holds.

    Args:
        name: The value's name in the policy file. The panel sends this back when
            the value changes, so it is the name and not a prettier version of it.
        field: How the policy file declares the value. Its description is the
            sentence shown under the label on screen, so the explanation a reader
            sees is the one written beside the value itself.
        value: What the value is now.
        startup_value: What it was when the service started, shown beside the
            current one when the two differ.
    """
    kind = _kind_of(name, field)
    description = field.description or ""
    changed = value != startup_value

    if kind is PolicyValueKind.BOOLEAN:
        return PolicyValueYesNo(
            name=name,
            description=description,
            changed=changed,
            kind=kind,
            value=bool(value),
            startup_value=bool(startup_value),
        )
    if kind is PolicyValueKind.CHOICE:
        return PolicyValueChoice(
            name=name,
            description=description,
            changed=changed,
            kind=kind,
            value=str(value),
            startup_value=str(startup_value),
            options=_offering(_options_of(field), str(value), str(startup_value)),
        )
    return PolicyValueWritten(
        name=name,
        description=description,
        changed=changed,
        kind=kind,
        value=str(value),
        startup_value=str(startup_value),
    )


def _offered_on_the_panel(field: FieldInfo) -> bool:
    """Whether the panel shows this value, and will accept a change to it.

    True unless the policy file says otherwise. Defaulting to shown is deliberate: a
    threshold added to that file turns up on the panel by itself, and keeping one off
    it is the decision somebody has to write down.

    Args:
        field: How the policy file declares the value.
    """
    extra = field.json_schema_extra
    if not isinstance(extra, dict):
        return True
    return extra.get("editable_in_panel") is not False


def _kind_of(name: str, field: FieldInfo) -> PolicyValueKind:
    """Work out which sort of control edits a value, from how the policy declares it.

    Reading it off the declaration rather than keeping a list here is what stops
    the panel and the policy file disagreeing about what a value is.

    Args:
        name: The value's name, used only to say which value is unrecognised.
        field: How the policy file declares the value — its type, and whether it
            lists the choices it should be picked from.

    Raises:
        TypeError: The panel has no control for this sort of value.
    """
    # Deliberately taken as an ordinary object rather than as a type: everything
    # below compares it by identity, and describing it as a type makes the type
    # checker decide that a value cannot be a whole number once it is known not to
    # be a yes-or-no — which is true of instances and quite wrong of the types
    # themselves.
    annotation: object = field.annotation

    # Before the check for a whole number, deliberately: in Python a yes-or-no *is*
    # a whole number, so testing for the number first would turn every toggle into
    # a text box.
    if annotation is bool:
        return PolicyValueKind.BOOLEAN
    if annotation is int:
        return PolicyValueKind.INTEGER
    if annotation is Decimal:
        return PolicyValueKind.MONEY
    if annotation is float:
        return PolicyValueKind.FRACTION
    if annotation is str:
        # Words that name their choices are picked from a list; words that do not are
        # typed. The policy file decides which, by listing them or not.
        return PolicyValueKind.TEXT if _options_of(field) is None else PolicyValueKind.CHOICE
    raise TypeError(f"The admin panel has no way to show the policy value {name!r}.")


def _options_of(field: FieldInfo) -> tuple[str, ...] | None:
    """The choices the policy file lists for a value, or `None` if it lists none.

    Everything is checked rather than trusted. What a field carries alongside its
    type is free-form, so a value could name its choices in a shape this does not
    expect; treating that as "no choices given" turns the control back into a text
    box, which is the safe way to be wrong — nothing becomes unreachable.

    Args:
        field: How the policy file declares the value.
    """
    extra = field.json_schema_extra
    if not isinstance(extra, dict):
        return None
    listed = extra.get("options")
    if not isinstance(listed, list) or not listed:
        return None
    if not all(isinstance(one, str) for one in listed):
        return None
    return tuple(str(one) for one in listed)


def _offering(listed: tuple[str, ...] | None, value: str, startup_value: str) -> tuple[str, ...]:
    """The choices to offer, with whatever is already set guaranteed to be among them.

    A value set from the environment need not be one the policy file lists, and a
    control that cannot show what is currently in force would silently change it the
    moment somebody saved the form. So anything already in play is added to the end
    rather than the list being trusted to contain it.

    Args:
        listed: The choices the policy file names, in its order.
        value: What the value is now.
        startup_value: What it was when the service started, which the panel also
            offers as a way back.

    Returns:
        The listed choices in their original order, then anything in force or at
        startup that was missing from them, each appearing once.
    """
    offering: dict[str, None] = {}
    for one in (listed or ()) + (value, startup_value):
        offering.setdefault(one, None)
    return tuple(offering)


def _problems_from(failure: ValidationError) -> list[dict[str, str]]:
    """Turn what the policy refused into one readable complaint per value.

    Args:
        failure: What building the policy raised.

    Returns:
        A name and a sentence for each complaint, in the order they were reported.
        A complaint about the policy as a whole rather than one value carries an
        empty name; nothing in the policy raises one today, but a complaint with
        nowhere to sit must not be dropped on the floor (NFR-4).
    """
    problems = []
    for error in failure.errors():
        location = error["loc"]
        message = error["msg"].removeprefix(_PYDANTIC_VALUE_ERROR_PREFIX)
        problems.append({"name": str(location[0]) if location else "", "message": message})
    return problems


def _no_such_value_message(names: Sequence[str]) -> str:
    """Say that a submitted name is not part of the claim policy at all."""
    listed = ", ".join(names)
    if len(names) == 1:
        return f"Nothing was changed. The claim policy has no value called {listed}."
    return f"Nothing was changed. The claim policy has no values called {listed}."


def _not_on_the_panel_message(names: Sequence[str]) -> str:
    """Say that a submitted value is one the panel deliberately does not change."""
    listed = ", ".join(names)
    if len(names) == 1:
        return f"Nothing was changed. {listed} cannot be changed from the admin panel."
    return f"Nothing was changed. These cannot be changed from the admin panel: {listed}."


def _rejected_message(names: Sequence[str]) -> str:
    """Say which submitted values the policy would not accept.

    The names are listed even though each also carries its own complaint, so that
    a reader who sees only this sentence still knows what to go and look at.
    """
    distinct = _unique(names)
    listed = ", ".join(distinct)
    if len(distinct) == 1:
        return f"Nothing was changed. This value was not accepted: {listed}."
    return f"Nothing was changed. These values were not accepted: {listed}."


def _unique(names: Sequence[str]) -> list[str]:
    """The names, in the order given, with any repeat dropped.

    One value can be refused for two reasons at once, and naming it twice in the
    same sentence reads like a mistake.
    """
    seen: dict[str, None] = {}
    for name in names:
        seen.setdefault(name, None)
    return list(seen)
