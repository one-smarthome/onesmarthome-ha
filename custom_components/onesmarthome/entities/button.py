"""Button entity that fires a single CLU action on press."""

from __future__ import annotations

from typing import Any

from homeassistant.components.button import ButtonEntity
from homeassistant.helpers.device_registry import DeviceInfo

from ..runtime.action import WriteAction
from ..runtime.hub import GrentonHub
from .base import GrentonEntity


class GrentonButton(GrentonEntity, ButtonEntity):
    """A momentary button; stateless, only a click action."""

    def __init__(
        self,
        hub: GrentonHub,
        unique_id: str,
        name: str,
        click: WriteAction,
        device_info: DeviceInfo | None = None,
    ) -> None:
        GrentonEntity.__init__(self, hub, unique_id, name, device_info)
        self._click = click
        self._watch_clus(click.clu_id)

    async def async_press(self, **kwargs: Any) -> None:
        await self._execute(self._click, "press")
