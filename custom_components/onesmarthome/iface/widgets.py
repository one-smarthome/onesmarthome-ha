"""Widget dataclasses and the type-tagged parser that builds them.

Each tile in the interface JSON is tagged with a ``type`` string. :func:`parse_widget`
looks that tag up and delegates to the matching parser, producing a small frozen
dataclass that carries only the refs and metadata the entity factory needs. The
widget's ``ga_type`` is kept verbatim so it can drive the HA device model and
translation key downstream.

Unknown ``type`` values raise :class:`KeyError`; the interface loader catches that
and drops the tile, so one unrecognised widget never breaks the whole import.
"""

from __future__ import annotations

from dataclasses import dataclass

from .refs import ActionRef, ValueRef, first_action, parse_action_ref, parse_value_ref


@dataclass(frozen=True)
class Widget:
    """Identity every widget shares."""

    widget_id: str
    ga_type: str


# --- value tiles ------------------------------------------------------------


@dataclass(frozen=True)
class Reading:
    """A labelled read-only value channel."""

    label: str
    value: ValueRef


@dataclass(frozen=True)
class ValueWidget(Widget):
    """A single read-only value tile (``VALUE_V2``)."""

    reading: Reading


@dataclass(frozen=True)
class ValueDoubleWidget(Widget):
    """Two read-only values side by side (``VALUE_DOUBLE``)."""

    left: Reading
    right: Reading


# --- switch tiles -----------------------------------------------------------


@dataclass(frozen=True)
class SwitchChannel:
    """One on/off channel: a state plus its action list."""

    row_id: int
    label: str
    state: ValueRef
    actions: tuple[ActionRef, ...]


@dataclass(frozen=True)
class SwitchWidget(Widget):
    """A bistable switch tile (``ON_OFF`` / ``ON_OFF_DOUBLE``)."""

    channels: tuple[SwitchChannel, ...]


# --- dimmer / led -----------------------------------------------------------


@dataclass(frozen=True)
class DimmerWidget(Widget):
    """A brightness-only dimmable light (``DIMMER_V2``)."""

    label: str
    minimum: float
    maximum: float
    precision: int
    value: ValueRef
    set_value: ActionRef


@dataclass(frozen=True)
class ColorChannel:
    """A read/write LED colour dimension bounded by a native range."""

    state: ValueRef
    action: ActionRef
    minimum: float
    maximum: float


@dataclass(frozen=True)
class LedWidget(Widget):
    """An RGB LED light assembled from colour channels (``LED``)."""

    label: str
    state: ValueRef
    actions: tuple[ActionRef, ...]
    hue: ColorChannel
    saturation: ColorChannel
    brightness: ColorChannel


# --- slider -----------------------------------------------------------------


@dataclass(frozen=True)
class SliderWidget(Widget):
    """A settable numeric control with an optional click action (``SLIDER``)."""

    label: str
    minimum: float
    maximum: float
    precision: int
    value: ValueRef
    set_value: ActionRef
    click: ActionRef | None


# --- scenes -------------------------------------------------------------------


@dataclass(frozen=True)
class SceneChannel:
    """One scene trigger: a label plus the action it fires."""

    label: str
    click: ActionRef


@dataclass(frozen=True)
class SceneWidget(Widget):
    """One or two fire-and-forget scene buttons (``SCENE`` / ``SCENE_DOUBLE``)."""

    channels: tuple[SceneChannel, ...]


# --- contact sensors --------------------------------------------------------


@dataclass(frozen=True)
class ContactChannel:
    """One contact channel: a state, an inversion flag, an optional button."""

    label: str
    state: ValueRef
    reverse: bool
    click: ActionRef | None


@dataclass(frozen=True)
class ContactSensorWidget(Widget):
    """A single contact sensor (``CONTACT_SENSOR``)."""

    channel: ContactChannel


@dataclass(frozen=True)
class ContactSensorDoubleWidget(Widget):
    """Two contact channels in one tile (``CONTACT_SENSOR_DOUBLE``)."""

    left: ContactChannel
    right: ContactChannel


# --- multisensor ------------------------------------------------------------


@dataclass(frozen=True)
class MultisensorWidget(Widget):
    """Seven environmental readings in one tile (``MULTISENSOR``)."""

    label: str
    air_co2: ValueRef
    sound: ValueRef
    air_voc: ValueRef
    light: ValueRef
    pressure: ValueRef
    humidity: ValueRef
    temperature: ValueRef


# --- roller shutters --------------------------------------------------------


@dataclass(frozen=True)
class RollerShutterWidget(Widget):
    """Legacy state-only roller shutter (``ROLLER_SHUTTER``)."""

    label: str
    state: ValueRef
    click: ActionRef


@dataclass(frozen=True)
class RollerShutterV3Widget(Widget):
    """Full position/tilt cover (``ROLLER_SHUTTER_V3``)."""

    label: str
    state: ValueRef
    position: ValueRef
    set_position: ActionRef
    tilt: ValueRef | None
    set_tilt: ActionRef | None
    stop: ActionRef | None


# --- camera -----------------------------------------------------------------


@dataclass(frozen=True)
class CameraWidget(Widget):
    """A passthrough video stream (``CAMERA``)."""

    label: str
    stream: str


# --- parsers ----------------------------------------------------------------


def _reading(raw: dict) -> Reading:
    return Reading(label=raw["label"], value=parse_value_ref(raw["object"]["value"]))


def _parse_value(raw: dict) -> ValueWidget:
    return ValueWidget(
        widget_id=raw["id"],
        ga_type=raw["type"],
        reading=_reading(raw),
    )


def _parse_value_double(raw: dict) -> ValueDoubleWidget:
    return ValueDoubleWidget(
        widget_id=raw["id"],
        ga_type=raw["type"],
        left=_reading(raw["componentLeft"]),
        right=_reading(raw["componentRight"]),
    )


def _switch_channel(raw: dict) -> SwitchChannel:
    return SwitchChannel(
        row_id=int(raw["rowId"]),
        label=raw["label"],
        state=parse_value_ref(raw["state"]),
        actions=tuple(parse_action_ref(a) for a in raw["actions"]),
    )


def _parse_switch(raw: dict) -> SwitchWidget:
    return SwitchWidget(
        widget_id=raw["id"],
        ga_type=raw["type"],
        channels=tuple(_switch_channel(c) for c in raw["components"]),
    )


def _parse_dimmer(raw: dict) -> DimmerWidget:
    obj = raw["object"]
    return DimmerWidget(
        widget_id=raw["id"],
        ga_type=raw["type"],
        label=raw["label"],
        minimum=float(raw["min"]),
        maximum=float(raw["max"]),
        precision=int(raw["precision"]),
        value=parse_value_ref(obj["value"]),
        set_value=parse_action_ref(obj["setValueAction"]),
    )


def _color_channel(raw: dict) -> ColorChannel:
    rng = raw["range"]
    return ColorChannel(
        state=parse_value_ref(raw["state"]),
        action=parse_action_ref(raw["actions"][0]),
        minimum=int(rng["min"]),
        maximum=int(rng["max"]),
    )


def _parse_led(raw: dict) -> LedWidget:
    by_type = {c["type"]: c for c in raw["components"]}
    button = by_type["BUTTON_BISTABLE"]
    return LedWidget(
        widget_id=raw["id"],
        ga_type=raw["type"],
        label=button["label"],
        state=parse_value_ref(button["state"]),
        actions=tuple(parse_action_ref(a) for a in button["actions"]),
        hue=_color_channel(by_type["SLIDER_HUE"]),
        saturation=_color_channel(by_type["SLIDER_SATURATION"]),
        brightness=_color_channel(by_type["SLIDER_BRIGHTNESS"]),
    )


def _parse_slider(raw: dict) -> SliderWidget:
    obj = raw["object"]
    click = obj.get("clickAction")
    return SliderWidget(
        widget_id=raw["id"],
        ga_type=raw["type"],
        label=raw["label"],
        minimum=float(raw["min"]),
        maximum=float(raw["max"]),
        precision=int(raw["precision"]),
        value=parse_value_ref(obj["value"]),
        set_value=parse_action_ref(obj["setValueAction"]),
        click=parse_action_ref(click) if click else None,
    )


def _scene_channel(raw: dict) -> SceneChannel:
    # A scene component is a monostable button with a flat action list; the
    # CLICK gesture is the one that fires the scene.
    actions = [parse_action_ref(a) for a in raw["actions"]]
    click = first_action(actions, "CLICK") or actions[0]
    return SceneChannel(label=raw["label"], click=click)


def _parse_scene(raw: dict) -> SceneWidget:
    return SceneWidget(
        widget_id=raw["id"],
        ga_type=raw["type"],
        channels=tuple(_scene_channel(c) for c in raw["components"]),
    )


def _contact_channel(label: str, reverse: bool, obj: dict) -> ContactChannel:
    click = obj.get("clickAction")
    return ContactChannel(
        label=label,
        state=parse_value_ref(obj["value"]),
        reverse=reverse,
        click=parse_action_ref(click) if click else None,
    )


def _parse_contact(raw: dict) -> ContactSensorWidget:
    return ContactSensorWidget(
        widget_id=raw["id"],
        ga_type=raw["type"],
        channel=_contact_channel(raw["label"], raw["reverseState"], raw["object"]),
    )


def _contact_double_channel(raw: dict) -> ContactChannel:
    return _contact_channel(raw["label"], raw["reverseState"], raw["object"])


def _parse_contact_double(raw: dict) -> ContactSensorDoubleWidget:
    return ContactSensorDoubleWidget(
        widget_id=raw["id"],
        ga_type=raw["type"],
        left=_contact_double_channel(raw["componentLeft"]),
        right=_contact_double_channel(raw["componentRight"]),
    )


def _parse_multisensor(raw: dict) -> MultisensorWidget:
    def channel(key: str) -> ValueRef:
        return parse_value_ref(raw[key]["value"])

    return MultisensorWidget(
        widget_id=raw["id"],
        ga_type=raw["type"],
        label=raw["label"],
        air_co2=channel("objectAirCo2"),
        sound=channel("objectSound"),
        air_voc=channel("objectAirVoc"),
        light=channel("objectLight"),
        pressure=channel("objectPressure"),
        humidity=channel("objectHumidity"),
        temperature=channel("objectTemperature"),
    )


def _parse_roller_shutter(raw: dict) -> RollerShutterWidget:
    first = raw["components"][0]
    return RollerShutterWidget(
        widget_id=raw["id"],
        ga_type=raw["type"],
        label=first["label"],
        state=parse_value_ref(first["state"]),
        click=parse_action_ref(first["actions"][0]),
    )


def _parse_roller_shutter_v3(raw: dict) -> RollerShutterV3Widget:
    obj = raw["object"]
    # A configured lamel-move timeout is how the interface marks a blind that
    # actually supports tilting; without it the tilt channel is omitted.
    has_tilt = obj.get("lamelMoveTimeout") is not None
    stop = obj.get("stopAction")
    return RollerShutterV3Widget(
        widget_id=raw["id"],
        ga_type=raw["type"],
        label=raw["label"],
        state=parse_value_ref(obj["state"]),
        position=parse_value_ref(obj["position"]),
        set_position=parse_action_ref(obj["setPositionAction"]),
        tilt=parse_value_ref(obj["lamelPosition"]) if has_tilt else None,
        set_tilt=parse_action_ref(obj["setLamelPositionAction"]) if has_tilt else None,
        stop=parse_action_ref(stop) if stop else None,
    )


def _parse_camera(raw: dict) -> CameraWidget:
    first = raw["components"][0]
    return CameraWidget(
        widget_id=raw["id"],
        ga_type=raw["type"],
        label=first["label"],
        stream=first["value"],
    )


_PARSERS = {
    "VALUE_V2": _parse_value,
    "VALUE_DOUBLE": _parse_value_double,
    "ON_OFF": _parse_switch,
    "ON_OFF_DOUBLE": _parse_switch,
    "DIMMER_V2": _parse_dimmer,
    "LED": _parse_led,
    "SCENE": _parse_scene,
    "SCENE_DOUBLE": _parse_scene,
    "CONTACT_SENSOR": _parse_contact,
    "CONTACT_SENSOR_DOUBLE": _parse_contact_double,
    "SLIDER": _parse_slider,
    "MULTISENSOR": _parse_multisensor,
    "ROLLER_SHUTTER": _parse_roller_shutter,
    "ROLLER_SHUTTER_V3": _parse_roller_shutter_v3,
    "CAMERA": _parse_camera,
}


def parse_widget(raw: dict) -> Widget:
    """Build the widget dataclass for ``raw``; raises KeyError if unsupported."""
    return _PARSERS[raw["type"]](raw)
