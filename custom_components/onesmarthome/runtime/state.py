"""Latest-value cache for every subscribed CLU slot.

The CLU answers a subscription with a *positional* list of values, so each CLU
store remembers the exact order in which slots were subscribed. That order is
carved into fixed-size registration chunks; each chunk registers on its own
socket, and a report is lined up against the chunk whose socket it arrived on.
Reads are synchronous, letting HA entities pull their current value without
awaiting anything.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..const import REGISTER_CHUNK_SIZE
from .state_object import ReadTarget
from .values import OshValue, coerce_value

# A slot that has been subscribed but never reported reads back as None so
# entities surface "unknown" instead of a fake empty value.
_UNREAD: OshValue = None


@dataclass(frozen=True)
class VariableKey:
    """Subscription key for a named variable."""

    name: str


@dataclass(frozen=True)
class AttributeKey:
    """Subscription key for an object attribute."""

    object_name: str
    name: str


SubscriptionKey = VariableKey | AttributeKey


def _key_for(target: ReadTarget) -> SubscriptionKey:
    if target.is_attribute:
        return AttributeKey(target.object_name, target.index)
    return VariableKey(target.index)


class CluStore:
    """Per-CLU value cache plus the ordered, chunked subscription list."""

    def __init__(self) -> None:
        self._values: dict[SubscriptionKey, OshValue] = {}
        self._order: list[SubscriptionKey] = []

    def subscribe(self, target: ReadTarget) -> None:
        """Track ``target``; the first subscription fixes its report slot."""
        key = _key_for(target)
        if key not in self._values:
            self._values[key] = _UNREAD
            self._order.append(key)

    def read(self, target: ReadTarget) -> OshValue | None:
        """Latest value for ``target``, or None if unread or never subscribed."""
        return self._values.get(_key_for(target))

    @property
    def has_subscriptions(self) -> bool:
        return bool(self._order)

    def ordered_keys(self) -> list[SubscriptionKey]:
        """Subscription keys in the order the CLU reports their values."""
        return self._order

    def chunks(self) -> list[list[SubscriptionKey]]:
        """The subscription list carved into registration chunks.

        Each chunk holds at most REGISTER_CHUNK_SIZE keys and registers on a
        socket of its own, which is what later routes its reports back to it.
        """
        return [
            self._order[start : start + REGISTER_CHUNK_SIZE]
            for start in range(0, len(self._order), REGISTER_CHUNK_SIZE)
        ]

    def apply_chunk(self, keys: list[SubscriptionKey], values: list[OshValue]) -> None:
        """Store one chunk's positional report.

        The CLU reports a chunk's values in the order its keys registered. A
        short report updates only the leading keys of the chunk.
        """
        for key, value in zip(keys, values):
            self._values[key] = coerce_value(value)


class StateStore:
    """All CLU stores, keyed by CLU id."""

    def __init__(self, clu_ids: list[str]) -> None:
        self._clus: dict[str, CluStore] = {clu_id: CluStore() for clu_id in clu_ids}

    def clu(self, clu_id: str) -> CluStore | None:
        return self._clus.get(clu_id)

    def subscribe(self, target: ReadTarget) -> None:
        store = self._clus.get(target.clu_id)
        if store is not None:
            store.subscribe(target)

    def read(self, target: ReadTarget) -> OshValue | None:
        store = self._clus.get(target.clu_id)
        return store.read(target) if store is not None else None
