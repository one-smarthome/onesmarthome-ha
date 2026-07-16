"""A pointer to one readable slot on a CLU.

The read side of the protocol. A slot is either a named variable or a structured
object attribute; both are addressed by CLU id, object name and index. The
parsing layer constructs these directly from the interface JSON.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ReadTarget:
    """Identifies a single value the coordinator can subscribe to and read."""

    clu_id: str
    object_name: str
    index: str
    # True for an object attribute, False for a named variable.
    is_attribute: bool
