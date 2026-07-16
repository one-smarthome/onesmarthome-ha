"""Turn parsed widgets into the flat list of Home Assistant entities.

This is the one place that knows how each widget type maps onto entities: how
many, of which class, with which unique-id suffixes and which CLU read/write
refs. It replaces the original device + adapter split, and the per-page grouping
is gone since the hub serves one shared pool.

The unique-id suffixes here are part of the integration's external contract:
changing one orphans the matching entity in a user's HA registry.
"""

from __future__ import annotations

from homeassistant.components.sensor import SensorDeviceClass

from .iface import Interface
from .iface.refs import ActionRef, first_action
from .iface.widgets import (
    CameraWidget,
    ColorChannel,
    ContactChannel,
    ContactSensorDoubleWidget,
    ContactSensorWidget,
    DimmerWidget,
    LedWidget,
    MultisensorWidget,
    Reading,
    RollerShutterV3Widget,
    RollerShutterWidget,
    SceneWidget,
    SliderWidget,
    SwitchWidget,
    ValueDoubleWidget,
    ValueWidget,
    Widget,
)
from .runtime.action import WriteAction
from .runtime.channel import ControlChannel
from .runtime.hub import GrentonHub
from .runtime.state_object import ReadTarget
from .entities.base import GrentonEntity
from .entities.binary_sensor import GrentonBinarySensor
from .entities.button import GrentonButton
from .entities.camera import GrentonCamera
from .entities.cover import GrentonCover
from .entities.light import GrentonDimmer, GrentonLed
from .entities.number import GrentonNumber
from .entities.sensor import (
    GrentonMeasurementSensor,
    GrentonRollerStateSensor,
    GrentonValueSensor,
)
from .entities.switch import GrentonSwitch

# White is not described by the interface; the firmware reserves these fixed
# feature indices on the same LED object for it.
_LED_WHITE_SET_INDEX = "12"
_LED_WHITE_STATE_INDEX = "15"
_LED_WHITE_RANGE = (0.0, 255.0)

# Each multisensor channel's fixed (attribute, device class, unit, id suffix).
_MULTISENSOR_CHANNELS = [
    ("air_co2", SensorDeviceClass.CO2, "ppm"),
    ("sound", SensorDeviceClass.SOUND_PRESSURE, "dB"),
    ("air_voc", SensorDeviceClass.VOLATILE_ORGANIC_COMPOUNDS_PARTS, "ppb"),
    ("light", SensorDeviceClass.ILLUMINANCE, "lx"),
    ("pressure", SensorDeviceClass.PRESSURE, "hPa"),
    ("humidity", SensorDeviceClass.HUMIDITY, "%"),
    ("temperature", SensorDeviceClass.TEMPERATURE, "°C"),
]


def _device_info(_widget: Widget) -> None:
    """Do not create HA devices for widgets.

    Keeping entities ungrouped avoids Home Assistant's post-setup device naming
    step. Entity names still come from the Grenton interface labels.
    """
    return None


def _channel(state, action: ActionRef, native_range: tuple[float, float], precision: int = 2) -> ControlChannel:
    return ControlChannel(
        action=action.build(),
        target=state.target,
        native_range=native_range,
        precision=precision,
    )


def _color_channel(color: ColorChannel) -> ControlChannel:
    return _channel(color.state, color.action, (color.minimum, color.maximum))


def build_entities(interface: Interface, hub: GrentonHub) -> list[GrentonEntity]:
    """Build every entity for every widget in ``interface``."""
    entities: list[GrentonEntity] = []
    for widget in interface.widgets:
        builder = _BUILDERS.get(type(widget))
        if builder is not None:
            entities.extend(builder(widget, hub))
    return entities


# --- per-widget builders ----------------------------------------------------


def _value(widget: ValueWidget, hub: GrentonHub) -> list[GrentonEntity]:
    return [_reading_sensor(widget, hub, widget.reading, "_0", _device_info(widget))]


def _value_double(widget: ValueDoubleWidget, hub: GrentonHub) -> list[GrentonEntity]:
    info = _device_info(widget)
    return [
        _reading_sensor(widget, hub, widget.left, "_0", info),
        _reading_sensor(widget, hub, widget.right, "_1", info),
    ]


def _reading_sensor(widget, hub, reading: Reading, suffix, info) -> GrentonValueSensor:
    return GrentonValueSensor(
        hub,
        f"{widget.widget_id}{suffix}",
        reading.label,
        reading.value.target,
        info,
    )


def _switch(widget: SwitchWidget, hub: GrentonHub) -> list[GrentonEntity]:
    info = _device_info(widget)
    entities: list[GrentonEntity] = []
    for channel in widget.channels:
        on = first_action(list(channel.actions), "ON")
        off = first_action(list(channel.actions), "OFF")
        if on is None or off is None:
            continue
        entities.append(
            GrentonSwitch(
                hub,
                f"{widget.widget_id}_{channel.row_id}",
                channel.label,
                channel.state.target,
                on.build(),
                off.build(),
                info,
            )
        )
    return entities


def _dimmer(widget: DimmerWidget, hub: GrentonHub) -> list[GrentonEntity]:
    channel = _channel(
        widget.value,
        widget.set_value,
        (widget.minimum, widget.maximum),
        widget.precision,
    )
    return [
        GrentonDimmer(hub, f"{widget.widget_id}_0", widget.label, channel, _device_info(widget))
    ]


def _led(widget: LedWidget, hub: GrentonHub) -> list[GrentonEntity]:
    on = first_action(list(widget.actions), "ON")
    off = first_action(list(widget.actions), "OFF")
    if on is None or off is None:
        return []

    white = ControlChannel(
        action=WriteAction(
            clu_id=on.clu_id,
            object_name=on.object_name,
            kind="method",
            index=_LED_WHITE_SET_INDEX,
            template="0",
        ),
        target=ReadTarget(
            clu_id=on.clu_id,
            object_name=on.object_name,
            index=_LED_WHITE_STATE_INDEX,
            is_attribute=True,
        ),
        native_range=_LED_WHITE_RANGE,
    )

    return [
        GrentonLed(
            hub,
            f"{widget.widget_id}_0",
            widget.label,
            widget.state.target,
            on.build(),
            off.build(),
            _color_channel(widget.hue),
            _color_channel(widget.saturation),
            _color_channel(widget.brightness),
            white,
            _device_info(widget),
        )
    ]


def _slider(widget: SliderWidget, hub: GrentonHub) -> list[GrentonEntity]:
    info = _device_info(widget)
    entities: list[GrentonEntity] = [
        GrentonNumber(
            hub,
            f"{widget.widget_id}_slider",
            widget.label,
            widget.minimum,
            widget.maximum,
            widget.precision,
            widget.value.target,
            widget.set_value.build(),
            info,
        )
    ]
    if widget.click is not None:
        entities.append(
            GrentonButton(
                hub, f"{widget.widget_id}_button", widget.label, widget.click.build(), info
            )
        )
    return entities


def _scene(widget: SceneWidget, hub: GrentonHub) -> list[GrentonEntity]:
    info = _device_info(widget)
    return [
        GrentonButton(
            hub,
            f"{widget.widget_id}_scene_{index}",
            channel.label,
            channel.click.build(),
            info,
        )
        for index, channel in enumerate(widget.channels)
    ]


def _contact_entities(widget, hub, channel: ContactChannel, sensor_suffix, button_suffix, info):
    entities: list[GrentonEntity] = [
        GrentonBinarySensor(
            hub,
            f"{widget.widget_id}{sensor_suffix}",
            channel.label,
            channel.state.target,
            channel.reverse,
            info,
        )
    ]
    if channel.click is not None:
        entities.append(
            GrentonButton(
                hub,
                f"{widget.widget_id}{button_suffix}",
                channel.label,
                channel.click.build(),
                info,
            )
        )
    return entities


def _contact(widget: ContactSensorWidget, hub: GrentonHub) -> list[GrentonEntity]:
    return _contact_entities(
        widget, hub, widget.channel, "_binary_sensor", "_button", _device_info(widget)
    )


def _contact_double(widget: ContactSensorDoubleWidget, hub: GrentonHub) -> list[GrentonEntity]:
    info = _device_info(widget)
    return [
        *_contact_entities(
            widget, hub, widget.left, "_binary_sensor_left", "_button_left", info
        ),
        *_contact_entities(
            widget, hub, widget.right, "_binary_sensor_right", "_button_right", info
        ),
    ]


def _multisensor(widget: MultisensorWidget, hub: GrentonHub) -> list[GrentonEntity]:
    info = _device_info(widget)
    entities: list[GrentonEntity] = []
    for attr, device_class, unit in _MULTISENSOR_CHANNELS:
        ref = getattr(widget, attr)
        entities.append(
            GrentonMeasurementSensor(
                hub,
                f"{widget.widget_id}_{attr}",
                widget.label,
                ref.target,
                device_class,
                unit,
                info,
            )
        )
    return entities


def _roller_shutter(widget: RollerShutterWidget, hub: GrentonHub) -> list[GrentonEntity]:
    info = _device_info(widget)
    return [
        GrentonRollerStateSensor(
            hub, f"{widget.widget_id}_sensor", widget.label, widget.state.target, info
        ),
        GrentonButton(
            hub, f"{widget.widget_id}_button", widget.label, widget.click.build(), info
        ),
    ]


def _roller_shutter_v3(widget: RollerShutterV3Widget, hub: GrentonHub) -> list[GrentonEntity]:
    return [
        GrentonCover(
            hub,
            widget.widget_id,
            widget.label,
            widget.state.target,
            widget.position.target,
            widget.set_position.build(),
            widget.tilt.target if widget.tilt is not None else None,
            widget.set_tilt.build() if widget.set_tilt is not None else None,
            widget.stop.build() if widget.stop is not None else None,
            _device_info(widget),
        )
    ]


def _camera(widget: CameraWidget, hub: GrentonHub) -> list[GrentonEntity]:
    return [
        GrentonCamera(
            hub, f"{widget.widget_id}_0", widget.label, widget.stream, _device_info(widget)
        )
    ]


_BUILDERS = {
    ValueWidget: _value,
    ValueDoubleWidget: _value_double,
    SwitchWidget: _switch,
    DimmerWidget: _dimmer,
    LedWidget: _led,
    SceneWidget: _scene,
    SliderWidget: _slider,
    ContactSensorWidget: _contact,
    ContactSensorDoubleWidget: _contact_double,
    MultisensorWidget: _multisensor,
    RollerShutterWidget: _roller_shutter,
    RollerShutterV3Widget: _roller_shutter_v3,
    CameraWidget: _camera,
}
