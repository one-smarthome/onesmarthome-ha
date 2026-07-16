"""References from the interface JSON into runtime read/write primitives.

The JSON describes two kinds of CLU endpoints with a shared ``callType`` tag:

* a *value* is something to read -- it becomes a :class:`ReadTarget`;
* an *action* is something to write -- it becomes a :class:`WriteAction`.

These ref objects are the bridge: they hold the parsed JSON fields and know how
to materialise the matching runtime object on demand. Actions additionally keep
their triggering ``event`` (ON/OFF/CLICK) so the factory can sort a flat action
list into the right behaviours.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..runtime.action import WriteAction
from ..runtime.state_object import ReadTarget

# JSON ``callType`` for a value: attribute vs. named variable.
_ATTRIBUTE_CALL = "ATTRIBUTE"

# JSON action ``callType`` -> the runtime :class:`WriteAction` kind string.
_ACTION_KIND = {
    "VARIABLE": "variable",
    "ATTRIBUTE": "attribute",
    "METHOD": "method",
    "SCRIPT": "script",
}

# Scripts are not slot-addressed, so they carry no index.
_SCRIPT_CALL = "SCRIPT"


@dataclass(frozen=True)
class ValueRef:
    """A readable endpoint described in the interface JSON."""

    clu_id: str
    object_name: str
    index: str
    is_attribute: bool

    @property
    def target(self) -> ReadTarget:
        """The runtime read target this reference points at."""
        return ReadTarget(
            clu_id=self.clu_id,
            object_name=self.object_name,
            index=self.index,
            is_attribute=self.is_attribute,
        )


@dataclass(frozen=True)
class ActionRef:
    """A writable endpoint described in the interface JSON."""

    clu_id: str
    object_name: str
    kind: str
    index: str | None
    template: str
    # The gesture that fires this action; used only to bucket actions.
    event: str

    def build(self) -> WriteAction:
        """A fresh runtime write action for this reference."""
        return WriteAction(
            clu_id=self.clu_id,
            object_name=self.object_name,
            kind=self.kind,
            index=self.index,
            template=self.template,
        )


def parse_value_ref(raw: dict) -> ValueRef:
    """Read one value reference out of its JSON object."""
    return ValueRef(
        clu_id=raw["cluId"],
        object_name=raw["objectName"],
        index=raw["index"],
        is_attribute=raw["callType"] == _ATTRIBUTE_CALL,
    )


def parse_action_ref(raw: dict) -> ActionRef:
    """Read one action reference out of its JSON object."""
    call_type = raw["callType"]
    return ActionRef(
        clu_id=raw["cluId"],
        object_name=raw["objectName"],
        kind=_ACTION_KIND[call_type],
        index=None if call_type == _SCRIPT_CALL else raw["index"],
        template=raw["value"],
        event=raw["event"],
    )


def first_action(refs: list[ActionRef], event: str) -> ActionRef | None:
    """The first action carrying ``event``, or None when absent."""
    return next((ref for ref in refs if ref.event == event), None)
