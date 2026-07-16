"""Camera entity: a pure passthrough to a CLU-provided stream URL."""

from __future__ import annotations

from homeassistant.components.camera import Camera, CameraEntityFeature
from homeassistant.helpers.device_registry import DeviceInfo

from ..runtime.hub import GrentonHub
from .base import GrentonEntity


class GrentonCamera(GrentonEntity, Camera):
    """HA pulls frames straight from the widget's stream URL."""

    _attr_supported_features = CameraEntityFeature.STREAM
    _attr_is_streaming = True

    def __init__(
        self,
        hub: GrentonHub,
        unique_id: str,
        name: str,
        stream: str,
        device_info: DeviceInfo | None = None,
    ) -> None:
        GrentonEntity.__init__(self, hub, unique_id, name, device_info)
        Camera.__init__(self)
        self._stream = stream

    @property
    def use_stream_for_stills(self) -> bool:
        return True

    async def stream_source(self) -> str:
        return self._stream
