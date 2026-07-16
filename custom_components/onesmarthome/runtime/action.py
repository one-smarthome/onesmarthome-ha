"""A writable command targeting a CLU slot.

The write side of the protocol. The interface JSON carries a value *template*
that may embed a ``$value$`` placeholder; :meth:`WriteAction.fill` stamps the
live value into a fresh copy of that template every time, so repeated writes
never compound.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# How the command reaches the slot, mirroring the CLU scripting verbs.
WriteKind = str  # one of: "variable", "attribute", "method", "script"

PLACEHOLDER = "$value$"


@dataclass
class WriteAction:
    """A command the coordinator can send to mutate a CLU slot."""

    clu_id: str
    object_name: str
    kind: WriteKind
    # Slot index; None only for scripts, which are not slot-addressed.
    index: str | None
    # Original template from the JSON, preserved for repeated substitution.
    template: str
    # Current rendered value; starts as the bare template.
    value: str = field(init=False)

    def __post_init__(self) -> None:
        self.value = self.template

    def fill(self, live_value: str) -> None:
        """Render ``live_value`` into the template (or replace it wholesale)."""
        if PLACEHOLDER in self.template:
            self.value = self.template.replace(PLACEHOLDER, live_value)
        else:
            self.value = live_value
