"""Cover entity for V3 roller shutters and blinds.

Position is shared 0-100 (closed-open) between the CLU and HA. Tilt is not: the
CLU uses a lamel angle 0-90 where 0 is fully open, while HA uses 0-100 where 100
is fully open, so tilt is rescaled and flipped in both directions.

State is push-driven: the CLU only reports a blind's settled position/lamel angle
*after* the movement finishes (a dozen-odd seconds of travel), so a plain
read-from-store cover would leave HA showing the old value until then. To keep
the UI responsive -- as it was before the 1.2 rewrite -- a command shows its
commanded target at once (an optimistic override) and holds it until the CLU
pushes a genuinely new reading, at which point the real value takes over. The
pre-command baseline is captured so that a re-report of the *same* old value
(e.g. a keep-alive resubscribe mid-travel) does not release the hold early.
"""

from __future__ import annotations

from typing import Any

from homeassistant.components.cover import (
    ATTR_POSITION,
    ATTR_TILT_POSITION,
    CoverDeviceClass,
    CoverEntity,
    CoverEntityFeature,
)
from homeassistant.core import callback
from homeassistant.helpers.device_registry import DeviceInfo

from ..runtime.action import WriteAction
from ..runtime.channel import rescale
from ..runtime.hub import GrentonHub
from ..runtime.state_object import ReadTarget
from .base import GrentonEntity

_CLU_TILT = (0.0, 90.0)
_HA_TILT = (0.0, 100.0)


class GrentonCover(GrentonEntity, CoverEntity):
    """Position control plus optional tilt and stop, wired to what exists."""

    _attr_device_class = CoverDeviceClass.SHUTTER

    def __init__(
        self,
        hub: GrentonHub,
        unique_id: str,
        name: str,
        state: ReadTarget,
        position: ReadTarget,
        set_position: WriteAction,
        tilt: ReadTarget | None = None,
        set_tilt: WriteAction | None = None,
        stop: WriteAction | None = None,
        device_info: DeviceInfo | None = None,
    ) -> None:
        GrentonEntity.__init__(self, hub, unique_id, name, device_info)
        self._state = state
        self._position = position
        self._set_position = set_position
        self._tilt = tilt
        self._set_tilt = set_tilt
        self._stop = stop

        # Optimistic overrides shown until the CLU confirms the move (see the
        # module docstring); the baselines hold the pre-command reading so a
        # stale re-report does not clear the override before the blind settles.
        self._optimistic_position: int | None = None
        self._position_baseline: int | None = None
        self._optimistic_tilt: int | None = None
        self._tilt_baseline: int | None = None

        hub.subscribe(state)
        hub.subscribe(position)
        if tilt is not None:
            hub.subscribe(tilt)
        self._watch_clus(state.clu_id, position.clu_id, set_position.clu_id)

        features = (
            CoverEntityFeature.OPEN
            | CoverEntityFeature.CLOSE
            | CoverEntityFeature.SET_POSITION
        )
        if stop is not None:
            features |= CoverEntityFeature.STOP
        if set_tilt is not None:
            features |= (
                CoverEntityFeature.OPEN_TILT
                | CoverEntityFeature.CLOSE_TILT
                | CoverEntityFeature.SET_TILT_POSITION
            )
            if stop is not None:
                features |= CoverEntityFeature.STOP_TILT
        self._attr_supported_features = features

    def _reported_position(self) -> int | None:
        """Position as last reported by the CLU, or None if unknown."""
        value = self.hub.read(self._position)
        # An unread slot or a non-numeric token means the position is unknown.
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return int(value)
        return None

    def _reported_tilt(self) -> int | None:
        """Lamel tilt (HA units) as last reported by the CLU, or None."""
        if self._tilt is None:
            return None
        value = self.hub.read(self._tilt)
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            return None
        return int(100 - rescale(float(value), _CLU_TILT, _HA_TILT))

    @property
    def current_cover_position(self) -> int | None:
        if self._optimistic_position is not None:
            return self._optimistic_position
        return self._reported_position()

    @property
    def current_cover_tilt_position(self) -> int | None:
        if self._optimistic_tilt is not None:
            return self._optimistic_tilt
        return self._reported_tilt()

    @property
    def is_closed(self) -> bool | None:
        position = self.current_cover_position
        return None if position is None else position == 0

    @property
    def is_closing(self) -> bool | None:
        return self.hub.read(self._state) == 2

    @property
    def is_opening(self) -> bool | None:
        return self.hub.read(self._state) == 1

    async def _drive_position(self, value: int) -> None:
        self._position_baseline = self._reported_position()
        self._set_position.fill(str(value))
        await self._execute(self._set_position, f"set position {value}")
        # Only reflect the target once the CLU has confirmed the command.
        self._optimistic_position = value
        self.async_write_ha_state()

    async def async_open_cover(self, **kwargs: Any) -> None:
        await self._drive_position(100)

    async def async_close_cover(self, **kwargs: Any) -> None:
        await self._drive_position(0)

    async def async_set_cover_position(self, **kwargs: Any) -> None:
        position = kwargs.get(ATTR_POSITION)
        if position is not None:
            await self._drive_position(int(position))

    async def async_stop_cover(self, **kwargs: Any) -> None:
        if self._stop is not None:
            await self._execute(self._stop, "stop")
            # The commanded target no longer holds; show whatever the CLU reports.
            self._optimistic_position = None
            self.async_write_ha_state()

    async def _drive_tilt(self, angle: int, ha_target: int) -> None:
        if self._set_tilt is None:
            return
        self._tilt_baseline = self._reported_tilt()
        self._set_tilt.fill(str(angle))
        await self._execute(self._set_tilt, f"set tilt {angle}")
        self._optimistic_tilt = ha_target
        self.async_write_ha_state()

    async def async_open_cover_tilt(self, **kwargs: Any) -> None:
        # CLU angle 0 == fully open == HA tilt 100.
        await self._drive_tilt(0, 100)

    async def async_close_cover_tilt(self, **kwargs: Any) -> None:
        # CLU angle 90 == fully closed == HA tilt 0.
        await self._drive_tilt(90, 0)

    async def async_set_cover_tilt_position(self, **kwargs: Any) -> None:
        position = kwargs.get(ATTR_TILT_POSITION)
        if position is None:
            return
        angle = rescale(int(position), _HA_TILT, _CLU_TILT)
        await self._drive_tilt(int(90 - angle), int(position))

    async def async_stop_cover_tilt(self, **kwargs: Any) -> None:
        if self._stop is not None:
            await self._execute(self._stop, "stop tilt")
            self._optimistic_tilt = None
            self.async_write_ha_state()

    @callback
    def _handle_coordinator_update(self) -> None:
        # A genuinely new reading (different from the pre-command baseline, or
        # already at the commanded target) supersedes the optimistic override.
        if self._optimistic_position is not None:
            reported = self._reported_position()
            if reported is not None and (
                reported == self._optimistic_position
                or reported != self._position_baseline
            ):
                self._optimistic_position = None
        if self._optimistic_tilt is not None:
            reported = self._reported_tilt()
            if reported is not None and (
                reported == self._optimistic_tilt
                or reported != self._tilt_baseline
            ):
                self._optimistic_tilt = None
        super()._handle_coordinator_update()
