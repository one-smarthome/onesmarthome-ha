"""Shared entity base and the loose-value-to-bool helper.

Every entity this integration exposes is a ``CoordinatorEntity`` bound to the
one :class:`GrentonHub`. The hub publishes a fresh snapshot whenever a report
lands, and :meth:`GrentonEntity._handle_coordinator_update` flushes that into HA
state, so subclasses only ever derive their value lazily from the hub.

Subclasses declare which CLU(s) they depend on via :meth:`_watch_clus`; the
entity then follows the hub's per-CLU health and shows as unavailable while any
watched CLU is offline. Writes go through :meth:`_execute` /
:meth:`_write_channel`, which raise ``HomeAssistantError`` when the CLU does not
confirm, so service calls and automation traces see the failure.
"""

from __future__ import annotations

from homeassistant.core import callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from ..runtime.action import WriteAction
from ..runtime.channel import ControlChannel, Range
from ..runtime.hub import GrentonHub
from ..runtime.values import OshValue

# String tokens the CLU uses for the two boolean states, beyond real bools.
_TRUE_TOKENS = {"ON", "TRUE", "1"}
_FALSE_TOKENS = {"OFF", "FALSE", "0", ""}


def as_bool(value: OshValue) -> bool | None:
    """Interpret a loosely typed CLU value as on/off, or None if unknowable.

    The same logical state can arrive as a real bool, a number, or a string
    token, so each case is handled in turn. None survives as None so callers can
    tell "off" apart from "unknown".
    """
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        token = value.strip().strip('"').upper()
        if token in _TRUE_TOKENS:
            return True
        if token in _FALSE_TOKENS:
            return False
        try:
            return float(token) != 0
        except ValueError:
            return None
    return None


class GrentonEntity(CoordinatorEntity[GrentonHub]):
    """Base for all entities: coordinator wiring plus device grouping."""

    # Keep the labels from the Grenton interface as the default HA names.
    _attr_has_entity_name = False

    def __init__(
        self,
        hub: GrentonHub,
        unique_id: str,
        name: str,
        device_info: DeviceInfo | None = None,
    ) -> None:
        super().__init__(hub)
        self._attr_unique_id = unique_id
        self._attr_name = name
        self._attr_device_info = device_info
        # Every CLU this entity reads from or writes to; availability follows
        # all of them. An entity with no watched CLU is always available.
        self._clu_ids: set[str] = set()

    @property
    def hub(self) -> GrentonHub:
        """The shared hub; an alias for the coordinator with a clearer name."""
        return self.coordinator

    def _watch_clus(self, *clu_ids: str) -> None:
        """Tie this entity's availability to the given CLU(s)."""
        self._clu_ids.update(clu_ids)

    @property
    def available(self) -> bool:
        """Available while the coordinator runs and every watched CLU answers."""
        if not super().available:
            return False
        return all(self.hub.clu_available(clu_id) for clu_id in self._clu_ids)

    async def _execute(self, action: WriteAction, what: str) -> None:
        """Send ``action``; an unconfirmed write surfaces as a loud HA error."""
        if not await self.hub.send(action):
            raise HomeAssistantError(
                f"{self.name}: CLU did not confirm '{what}' on {action.object_name}"
            )

    async def _write_channel(
        self,
        channel: ControlChannel,
        what: str,
        value: float,
        in_range: Range | None = None,
    ) -> None:
        """Write ``value`` through ``channel``; raises like :meth:`_execute`.

        With ``in_range`` the value is rescaled into the channel's native
        range first; without it the value is taken as already native.
        """
        if in_range is None:
            confirmed = await channel.write_native(self.hub, value)
        else:
            confirmed = await channel.write_from(self.hub, in_range, value)
        if not confirmed:
            raise HomeAssistantError(
                f"{self.name}: CLU did not confirm '{what}' on "
                f"{channel.action.object_name}"
            )

    @callback
    def _handle_coordinator_update(self) -> None:
        self.async_write_ha_state()
