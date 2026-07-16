"""Binary sensor entity with an invertible reading and a user device class."""

from __future__ import annotations

import voluptuous as vol
from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.helpers import selector
from homeassistant.helpers.device_registry import DeviceInfo

from ..runtime.hub import GrentonHub
from ..runtime.state_object import ReadTarget
from .base import GrentonEntity, as_bool
from .configurable import EntityConfigurator, FormContext, OptionForm


class GrentonBinarySensor(GrentonEntity, EntityConfigurator, BinarySensorEntity):
    """A contact reading, optionally inverted, with a user-chosen class."""

    def __init__(
        self,
        hub: GrentonHub,
        unique_id: str,
        name: str,
        state: ReadTarget,
        reverse: bool,
        device_info: DeviceInfo | None = None,
    ) -> None:
        GrentonEntity.__init__(self, hub, unique_id, name, device_info)
        EntityConfigurator.__init__(self)
        self._state = state
        self._reverse = reverse
        hub.subscribe(state)
        self._watch_clus(state.clu_id)

    def option_forms(self) -> list[OptionForm]:
        return [OptionForm("device_class", self._class_form)]

    def _class_form(self, ctx: FormContext) -> vol.Schema:
        return vol.Schema(
            {
                vol.Required(
                    "device_class", default=ctx.stored.get("device_class")
                ): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=[dc.value for dc in BinarySensorDeviceClass],
                        mode=selector.SelectSelectorMode.DROPDOWN,
                        translation_key="binary_sensor_device_classes",
                        sort=True,
                    )
                ),
            }
        )

    @property
    def is_on(self) -> bool | None:
        value = as_bool(self.hub.read(self._state))
        if value is None:
            return None
        return not value if self._reverse else value

    @property
    def device_class(self) -> BinarySensorDeviceClass | None:
        chosen = self.current_settings().get("device_class")
        if chosen:
            try:
                return BinarySensorDeviceClass(chosen)
            except ValueError:
                return None
        return None
