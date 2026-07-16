"""Sensor entities: a configurable value tile, fixed multisensor channels, and
the legacy roller-shutter state enum."""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.components.sensor.const import DEVICE_CLASS_UNITS
from homeassistant.const import CONF_UNIT_OF_MEASUREMENT
from homeassistant.helpers import selector
from homeassistant.helpers.device_registry import DeviceInfo

from ..runtime.hub import GrentonHub
from ..runtime.state_object import ReadTarget
from .base import GrentonEntity
from .configurable import EntityConfigurator, FormContext, OptionForm


def _unit_options(units: set[Any]) -> list[str]:
    """Normalise a device class's unit set into string dropdown options."""
    options: list[str] = []
    for unit in units:
        if unit is None:
            options.append("none")
        elif isinstance(unit, str):
            options.append(unit)
        else:
            # Enum members stringify to their symbolic name; the dropdown
            # needs the wire string they carry in ``value``.
            options.append(str(getattr(unit, "value", unit)))
    return options


def _device_class_form(
    ctx: FormContext, choices: list[str], translation_key: str
) -> vol.Schema:
    """Dropdown of device classes, pre-filled from saved settings."""
    return vol.Schema(
        {
            vol.Required(
                "device_class", default=ctx.stored.get("device_class")
            ): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=choices,
                    mode=selector.SelectSelectorMode.DROPDOWN,
                    translation_key=translation_key,
                    sort=True,
                )
            ),
        }
    )


def _unit_form(ctx: FormContext, units: set[Any]) -> "vol.Schema | None":
    """Unit dropdown for the class chosen earlier, or None when it has no units."""
    options = _unit_options(units)
    if not options:
        return None
    return vol.Schema(
        {
            vol.Required(
                CONF_UNIT_OF_MEASUREMENT,
                default=ctx.stored.get(CONF_UNIT_OF_MEASUREMENT),
            ): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=options,
                    mode=selector.SelectSelectorMode.DROPDOWN,
                )
            ),
        }
    )


# Device classes whose reading accumulates over time: their statistic is a
# running total, which is what the Energy Dashboard sums (e.g. a metering
# relay's kWh counter). Everything else numeric is an instantaneous reading.
_TOTAL_INCREASING_CLASSES = {
    SensorDeviceClass.ENERGY,
    SensorDeviceClass.GAS,
    SensorDeviceClass.WATER,
}

# Device classes that carry no numeric magnitude, so no statistic applies.
_NON_NUMERIC_CLASSES = {
    SensorDeviceClass.DATE,
    SensorDeviceClass.TIMESTAMP,
    SensorDeviceClass.ENUM,
}

# Sentinel dropdown option that switches statistics off for this sensor.
_STATE_CLASS_NONE = "none"
_STATE_CLASS_OPTIONS = [
    _STATE_CLASS_NONE,
    SensorStateClass.MEASUREMENT.value,
    SensorStateClass.TOTAL.value,
    SensorStateClass.TOTAL_INCREASING.value,
]


def _default_state_class(
    device_class: SensorDeviceClass | None,
) -> SensorStateClass | None:
    """Pick a sensible statistic for a device class the user hasn't tuned.

    Cumulative meters become total-increasing so they are Energy-Dashboard
    ready out of the box; other numeric readings become measurements; classes
    with no numeric magnitude get no statistic at all.
    """
    if device_class is None or device_class in _NON_NUMERIC_CLASSES:
        return None
    if device_class in _TOTAL_INCREASING_CLASSES:
        return SensorStateClass.TOTAL_INCREASING
    return SensorStateClass.MEASUREMENT


class GrentonValueSensor(GrentonEntity, EntityConfigurator, SensorEntity):
    """A read-only value tile whose class and unit the user can set."""

    def __init__(
        self,
        hub: GrentonHub,
        unique_id: str,
        name: str,
        value: ReadTarget,
        device_info: DeviceInfo | None = None,
    ) -> None:
        GrentonEntity.__init__(self, hub, unique_id, name, device_info)
        EntityConfigurator.__init__(self)
        self._value = value
        hub.subscribe(value)
        self._watch_clus(value.clu_id)

    def option_forms(self) -> list[OptionForm]:
        return [
            OptionForm("device_class", self._class_form),
            OptionForm("unit", self._unit_form),
            OptionForm("state_class", self._state_class_form),
        ]

    def _class_form(self, ctx: FormContext) -> vol.Schema:
        return _device_class_form(
            ctx, [dc.value for dc in SensorDeviceClass], "sensor_device_classes"
        )

    def _unit_form(self, ctx: FormContext) -> "vol.Schema | None":
        chosen = ctx.gathered.get("device_class")
        if not chosen:
            return None
        try:
            units = DEVICE_CLASS_UNITS.get(SensorDeviceClass(chosen), set())
        except (ValueError, KeyError):
            return None
        return _unit_form(ctx, units)

    def _state_class_form(self, ctx: FormContext) -> vol.Schema:
        chosen = ctx.gathered.get("device_class") or ctx.stored.get("device_class")
        try:
            device_class = SensorDeviceClass(chosen) if chosen else None
        except ValueError:
            device_class = None
        # A non-numeric class (date/timestamp/enum) carries no statistic, so
        # offer only "off" rather than letting the user pick a value HA rejects.
        if device_class in _NON_NUMERIC_CLASSES:
            options = [_STATE_CLASS_NONE]
            default = _STATE_CLASS_NONE
        else:
            options = _STATE_CLASS_OPTIONS
            default = ctx.stored.get("state_class")
            if default is None:
                derived = _default_state_class(device_class)
                default = derived.value if derived else _STATE_CLASS_NONE
        return vol.Schema(
            {
                vol.Required("state_class", default=default): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=options,
                        mode=selector.SelectSelectorMode.DROPDOWN,
                        translation_key="sensor_state_classes",
                    )
                ),
            }
        )

    @property
    def native_value(self) -> Any:
        value = self.hub.read(self._value)
        # An unread slot or an empty token renders as unknown, not as "".
        return None if value == "" else value

    @property
    def device_class(self) -> SensorDeviceClass | None:
        chosen = self.current_settings().get("device_class")
        if chosen:
            try:
                return SensorDeviceClass(chosen)
            except ValueError:
                return None
        return None

    @property
    def native_unit_of_measurement(self) -> str | None:
        return self.current_settings().get(CONF_UNIT_OF_MEASUREMENT)

    @property
    def state_class(self) -> SensorStateClass | None:
        chosen = self.current_settings().get("state_class")
        if chosen == _STATE_CLASS_NONE:
            return None
        if chosen:
            try:
                return SensorStateClass(chosen)
            except ValueError:
                return None
        # Not configured yet: derive a default from the device class so a
        # power/energy reading is Energy-Dashboard ready once its class is set.
        return _default_state_class(self.device_class)


class GrentonMeasurementSensor(GrentonEntity, SensorEntity):
    """A multisensor channel with a class and unit baked in at build time."""

    def __init__(
        self,
        hub: GrentonHub,
        unique_id: str,
        name: str,
        value: ReadTarget,
        device_class: SensorDeviceClass,
        unit: str,
        device_info: DeviceInfo | None = None,
    ) -> None:
        GrentonEntity.__init__(self, hub, unique_id, name, device_info)
        self._value = value
        self._attr_device_class = device_class
        self._attr_native_unit_of_measurement = unit
        hub.subscribe(value)
        self._watch_clus(value.clu_id)

    @property
    def native_value(self) -> Any:
        value = self.hub.read(self._value)
        # An unread slot or an empty token renders as unknown, not as "".
        return None if value == "" else value


class GrentonRollerStateSensor(GrentonEntity, SensorEntity):
    """Translates a legacy shutter's numeric state code into an enum option."""

    _attr_device_class = SensorDeviceClass.ENUM
    _attr_translation_key = "roller_shutter_state"

    _CODES = {0: "stopped", 1: "opening", 2: "closing", 3: "locked"}
    # Everything the CLU can report, plus the fallback for codes we don't map.
    _attr_options = [*_CODES.values(), "unknown"]

    def __init__(
        self,
        hub: GrentonHub,
        unique_id: str,
        name: str,
        state: ReadTarget,
        device_info: DeviceInfo | None = None,
    ) -> None:
        GrentonEntity.__init__(self, hub, unique_id, name, device_info)
        self._state = state
        hub.subscribe(state)
        self._watch_clus(state.clu_id)

    @property
    def native_value(self) -> str:
        return self._CODES.get(self.hub.read(self._state), "unknown")
