"""Switch entity: reads one state, writes through separate ON/OFF actions."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.helpers.device_registry import DeviceInfo

from ..runtime.action import WriteAction
from ..runtime.hub import GrentonHub
from ..runtime.state_object import ReadTarget
from .base import GrentonEntity, as_bool


class GrentonSwitch(GrentonEntity, SwitchEntity):
    """A bistable switch whose transitions fire two distinct CLU actions."""

    def __init__(
        self,
        hub: GrentonHub,
        unique_id: str,
        name: str,
        state: ReadTarget,
        on_action: WriteAction,
        off_action: WriteAction,
        device_info: DeviceInfo | None = None,
    ) -> None:
        GrentonEntity.__init__(self, hub, unique_id, name, device_info)
        self._state = state
        self._on = on_action
        self._off = off_action
        hub.subscribe(state)
        self._watch_clus(state.clu_id, on_action.clu_id, off_action.clu_id)

    @property
    def is_on(self) -> bool | None:
        return as_bool(self.hub.read(self._state))

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._execute(self._on, "turn on")

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._execute(self._off, "turn off")
