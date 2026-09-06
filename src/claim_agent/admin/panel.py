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

_PYDANTIC_VALUE_ERROR_PREFIX = "Value error, "


def describe_policy(live: LivePolicy) -> PolicyView:
    """Set out every claim threshold as the panel needs to see it."""
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
    """Work out the policy that submitting this form should produce."""

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
    """Describe one threshold: what it is called, what it means, and what it holds."""
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
    """Whether the panel shows this value, and will accept a change to it."""
    extra = field.json_schema_extra
    if not isinstance(extra, dict):
        return True
    return extra.get("editable_in_panel") is not False


def _kind_of(name: str, field: FieldInfo) -> PolicyValueKind:
    """Work out which sort of control edits a value, from how the policy declares it."""

    annotation: object = field.annotation

    if annotation is bool:
        return PolicyValueKind.BOOLEAN
    if annotation is int:
        return PolicyValueKind.INTEGER
    if annotation is Decimal:
        return PolicyValueKind.MONEY
    if annotation is float:
        return PolicyValueKind.FRACTION
    if annotation is str:
        return PolicyValueKind.TEXT if _options_of(field) is None else PolicyValueKind.CHOICE
    raise TypeError(f"The admin panel has no way to show the policy value {name!r}.")


def _options_of(field: FieldInfo) -> tuple[str, ...] | None:
    """The choices the policy file lists for a value, or `None` if it lists none."""
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
    """The choices to offer, with whatever is already set guaranteed to be among them."""
    offering: dict[str, None] = {}
    for one in (listed or ()) + (value, startup_value):
        offering.setdefault(one, None)
    return tuple(offering)


def _problems_from(failure: ValidationError) -> list[dict[str, str]]:
    """Turn what the policy refused into one readable complaint per value."""
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
    """Say which submitted values the policy would not accept."""
    distinct = _unique(names)
    listed = ", ".join(distinct)
    if len(distinct) == 1:
        return f"Nothing was changed. This value was not accepted: {listed}."
    return f"Nothing was changed. These values were not accepted: {listed}."


def _unique(names: Sequence[str]) -> list[str]:
    """The names, in the order given, with any repeat dropped."""
    seen: dict[str, None] = {}
    for name in names:
        seen.setdefault(name, None)
    return list(seen)
