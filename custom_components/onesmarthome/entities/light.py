"""Light entities: a brightness-only dimmer and an HS-colour LED."""

from __future__ import annotations

from typing import Any

from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
    ATTR_HS_COLOR,
    ATTR_WHITE,
    ColorMode,
    LightEntity,
)
from homeassistant.helpers.device_registry import DeviceInfo

from ..runtime.action import WriteAction
from ..runtime.channel import ControlChannel
from ..runtime.hub import GrentonHub
from ..runtime.state_object import ReadTarget
from .base import GrentonEntity, as_bool

_HA_BRIGHTNESS = (0.0, 255.0)
_HA_HUE = (0.0, 360.0)
_HA_SATURATION = (0.0, 100.0)


class GrentonDimmer(GrentonEntity, LightEntity):
    """A single dimmer channel surfaced as a brightness-only light.

    There is no power flag: "on" simply means the level sits above the channel
    minimum. Turning off writes the minimum and stashes the prior level so the
    next turn-on restores it.
    """

    _attr_supported_color_modes = {ColorMode.BRIGHTNESS}
    _attr_color_mode = ColorMode.BRIGHTNESS

    def __init__(
        self,
        hub: GrentonHub,
        unique_id: str,
        name: str,
        channel: ControlChannel,
        device_info: DeviceInfo | None = None,
    ) -> None:
        GrentonEntity.__init__(self, hub, unique_id, name, device_info)
        self._channel = channel
        self._last_brightness: int | None = None
        channel.subscribe(hub)
        self._watch_clus(channel.target.clu_id, channel.action.clu_id)

    @property
    def is_on(self) -> bool | None:
        native = self._channel.native_value(self.hub)
        if native is None:
            return None
        return native > self._channel.native_range[0]

    @property
    def brightness(self) -> int | None:
        value = self._channel.value_in(self.hub, _HA_BRIGHTNESS)
        return None if value is None else int(value)

    async def async_turn_on(self, **kwargs: Any) -> None:
        if ATTR_BRIGHTNESS in kwargs:
            brightness = kwargs[ATTR_BRIGHTNESS]
        else:
            brightness = self._last_brightness or self.brightness or 255
        await self._write_channel(
            self._channel, "set brightness", brightness, _HA_BRIGHTNESS
        )
        self._last_brightness = brightness

    async def async_turn_off(self, **kwargs: Any) -> None:
        current = self.brightness
        if current:
            self._last_brightness = current
        await self._write_channel(
            self._channel, "turn off", self._channel.native_range[0]
        )


class GrentonLed(GrentonEntity, LightEntity):
    """An RGB LED with HS colour and an optional, exclusive white channel."""

    def __init__(
        self,
        hub: GrentonHub,
        unique_id: str,
        name: str,
        state: ReadTarget,
        on_action: WriteAction,
        off_action: WriteAction,
        hue: ControlChannel,
        saturation: ControlChannel,
        brightness: ControlChannel,
        white: ControlChannel | None = None,
        device_info: DeviceInfo | None = None,
    ) -> None:
        GrentonEntity.__init__(self, hub, unique_id, name, device_info)
        self._state = state
        self._on = on_action
        self._off = off_action
        self._hue = hue
        self._saturation = saturation
        self._brightness = brightness
        self._white = white

        self._attr_supported_color_modes = {ColorMode.HS}
        if white is not None:
            self._attr_supported_color_modes.add(ColorMode.WHITE)

        hub.subscribe(state)
        hue.subscribe(hub)
        saturation.subscribe(hub)
        brightness.subscribe(hub)
        if white is not None:
            white.subscribe(hub)

        self._watch_clus(state.clu_id, on_action.clu_id, off_action.clu_id)
        for channel in (hue, saturation, brightness, white):
            if channel is not None:
                self._watch_clus(channel.target.clu_id, channel.action.clu_id)

    def _white_active(self) -> bool:
        if self._white is None:
            return False
        native = self._white.native_value(self.hub)
        return native is not None and native > self._white.native_range[0]

    @property
    def color_mode(self) -> ColorMode:
        return ColorMode.WHITE if self._white_active() else ColorMode.HS

    @property
    def is_on(self) -> bool | None:
        color = as_bool(self.hub.read(self._state))
        white_native = self._white.native_value(self.hub) if self._white else None
        if color is None and white_native is None:
            return None
        if color:
            return True
        return self._white_active()

    @property
    def brightness(self) -> int | None:
        if self._white_active() and self._white is not None:
            return int(self._white.value_in(self.hub, _HA_BRIGHTNESS) or 0)
        value = self._brightness.value_in(self.hub, _HA_BRIGHTNESS)
        return None if value is None else int(value)

    @property
    def hs_color(self) -> tuple[float, float] | None:
        hue = self._hue.value_in(self.hub, _HA_HUE)
        saturation = self._saturation.value_in(self.hub, _HA_SATURATION)
        if hue is None or saturation is None:
            return None
        return (hue, saturation)

    async def _clear_white(self) -> None:
        if self._white is not None:
            await self._write_channel(
                self._white, "clear white", self._white.native_range[0]
            )

    async def async_turn_on(self, **kwargs: Any) -> None:
        # A white request lights white and powers off the colour side so the two
        # modes never run at once.
        if ATTR_WHITE in kwargs and self._white is not None:
            await self._write_channel(
                self._white, "set white", kwargs[ATTR_WHITE], _HA_BRIGHTNESS
            )
            await self._execute(self._off, "turn off colour")
            return

        if ATTR_HS_COLOR in kwargs:
            hue, saturation = kwargs[ATTR_HS_COLOR]
            await self._write_channel(self._hue, "set hue", hue, _HA_HUE)
            await self._write_channel(
                self._saturation, "set saturation", saturation, _HA_SATURATION
            )

        if ATTR_BRIGHTNESS in kwargs:
            await self._write_channel(
                self._brightness,
                "set brightness",
                kwargs[ATTR_BRIGHTNESS],
                _HA_BRIGHTNESS,
            )

        if ATTR_HS_COLOR in kwargs or ATTR_BRIGHTNESS in kwargs:
            await self._clear_white()

        # A bare "on" still needs the explicit ON action; raising brightness
        # above zero already powers the LED on its own.
        if ATTR_BRIGHTNESS not in kwargs:
            await self._execute(self._on, "turn on")

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._clear_white()
        await self._execute(self._off, "turn off")
