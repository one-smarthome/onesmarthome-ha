"""Bidirectional control channel: read a slot, scale it, write it back.

Dimmers, LED colour components and sliders all share one shape: a readable slot
in some native CLU range paired with a write action, where HA expects a
different range (e.g. 0-255 brightness). This module bundles the read target,
the write action, the native range and rounding precision, and does the linear
rescaling in both directions.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from .action import WriteAction
from .state_object import ReadTarget

if TYPE_CHECKING:
    from .hub import GrentonHub

Range = tuple[float, float]


def rescale(value: float, source: Range, target: Range) -> float:
    """Linearly project ``value`` from ``source`` onto ``target``.

    A zero-width source range collapses to the target minimum instead of
    dividing by zero.
    """
    src_lo, src_hi = source
    tgt_lo, tgt_hi = target
    span = src_hi - src_lo
    fraction = (value - src_lo) / span if span > 0 else 0.0
    return tgt_lo + fraction * (tgt_hi - tgt_lo)


def render_value(value: float, precision: int) -> str:
    """Format a number the way the CLU expects it in an action payload.

    Integer channels must send ``"5"`` not ``"5.0"`` -- the CLU rejects the
    trailing decimal -- so precision 0 collapses to an int string.
    """
    rounded = round(value, precision)
    if precision == 0:
        return str(int(rounded))
    return str(rounded)


@dataclass(slots=True)
class ControlChannel:
    """A readable CLU slot coupled with the action that writes it."""

    action: WriteAction
    target: ReadTarget
    native_range: Range
    precision: int = 2

    def subscribe(self, hub: GrentonHub) -> None:
        hub.subscribe(self.target)

    def native_value(self, hub: GrentonHub) -> float | None:
        """Current value in native CLU units, or None if unknown."""
        raw = hub.read(self.target)
        if raw is None or raw == "":
            return None
        return float(raw)

    def value_in(self, hub: GrentonHub, out_range: Range) -> float | None:
        """Current value rescaled from native units into ``out_range``."""
        native = self.native_value(hub)
        if native is None:
            return None
        return rescale(native, self.native_range, out_range)

    async def write_native(self, hub: GrentonHub, value: float) -> bool:
        """Send a value already expressed in native CLU units.

        Returns whether the CLU confirmed the write, so the owning entity can
        surface a failure to the user.
        """
        self.action.fill(render_value(value, self.precision))
        return await hub.send(self.action)

    async def write_from(self, hub: GrentonHub, in_range: Range, value: float) -> bool:
        """Rescale ``value`` from ``in_range`` into native units, then send it."""
        return await self.write_native(hub, rescale(value, in_range, self.native_range))
