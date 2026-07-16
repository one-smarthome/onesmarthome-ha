"""Number entity for a settable slider, with mode/class/unit configuration."""

from __future__ import annotations

import voluptuous as vol
from homeassistant.components.number import NumberDeviceClass, NumberEntity
from homeassistant.components.number.const import DEVICE_CLASS_UNITS
from homeassistant.const import CONF_UNIT_OF_MEASUREMENT
from homeassistant.helpers import selector
from homeassistant.helpers.device_registry import DeviceInfo

from ..runtime.action import WriteAction
from ..runtime.channel import render_value
from ..runtime.hub import GrentonHub
from ..runtime.state_object import ReadTarget
from .base import GrentonEntity
from .configurable import EntityConfigurator, FormContext, OptionForm
from .sensor import _unit_form

_MODES = ["auto", "slider", "box"]


class GrentonNumber(GrentonEntity, EntityConfigurator, NumberEntity):
    """A settable numeric control bounded by the widget's min/max/precision."""

    def __init__(
        self,
        hub: GrentonHub,
        unique_id: str,
        name: str,
        minimum: float,
        maximum: float,
        precision: int,
        value: ReadTarget,
        set_value: WriteAction,
        device_info: DeviceInfo | None = None,
    ) -> None:
        GrentonEntity.__init__(self, hub, unique_id, name, device_info)
        EntityConfigurator.__init__(self)
        self._precision = precision
        self._value = value
        self._set_value = set_value
        self._attr_native_min_value = minimum
        self._attr_native_max_value = maximum
        # Precision -> step: 0 decimals => 1, 1 decimal => 0.1, etc.
        self._attr_native_step = 10 ** (-precision)
        hub.subscribe(value)
        self._watch_clus(value.clu_id, set_value.clu_id)

    def option_forms(self) -> list[OptionForm]:
        return [
            OptionForm("mode", self._mode_form),
            OptionForm("device_class", self._class_form),
            OptionForm("unit", self._unit_form),
        ]

    def _mode_form(self, ctx: FormContext) -> vol.Schema:
        return vol.Schema(
            {
                vol.Required(
                    "mode", default=ctx.stored.get("mode") or "slider"
                ): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=_MODES,
                        mode=selector.SelectSelectorMode.DROPDOWN,
                        translation_key="slider_modes",
                    )
                ),
            }
        )

    def _class_form(self, ctx: FormContext) -> vol.Schema:
        return vol.Schema(
            {
                vol.Required(
                    "device_class", default=ctx.stored.get("device_class")
                ): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=[dc.value for dc in NumberDeviceClass],
                        mode=selector.SelectSelectorMode.DROPDOWN,
                        translation_key="slider_device_classes",
                        sort=True,
                    )
                ),
            }
        )

    def _unit_form(self, ctx: FormContext) -> "vol.Schema | None":
        chosen = ctx.gathered.get("device_class")
        if not chosen:
            return None
        try:
            units = DEVICE_CLASS_UNITS.get(NumberDeviceClass(chosen), set())
        except (ValueError, KeyError):
            return None
        return _unit_form(ctx, units)

    @property
    def native_value(self) -> float | None:
        value = self.hub.read(self._value)
        # Only a real numeric reading maps onto a number state; anything else
        # (an unread slot, a text token) is unknown.
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return float(value)
        return None

    async def async_set_native_value(self, value: float) -> None:
        # Every write verb reaches the same CLU, which rejects a trailing decimal
        # on an integer channel (precision 0): a lamel script builds its time-map
        # key from tostring(target), and "0-2.0" matches nothing -> no movement.
        # render_value collapses precision-0 values to a bare int string for all
        # kinds (scripts included), so do not special-case "script" here.
        rendered = render_value(value, self._precision)
        self._set_value.fill(rendered)
        await self._execute(self._set_value, f"set value {rendered}")

    @property
    def mode(self) -> str:
        mode = self.current_settings().get("mode")
        return mode if mode in _MODES else "slider"

    @property
    def device_class(self) -> NumberDeviceClass | None:
        chosen = self.current_settings().get("device_class")
        if chosen:
            try:
                return NumberDeviceClass(chosen)
            except ValueError:
                return None
        return None

    @property
    def native_unit_of_measurement(self) -> str | None:
        return self.current_settings().get(CONF_UNIT_OF_MEASUREMENT)
