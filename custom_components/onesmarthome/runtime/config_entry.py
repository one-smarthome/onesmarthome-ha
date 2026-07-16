"""Typed config-entry data and the runtime objects attached to a loaded entry."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, TypedDict

from homeassistant.config_entries import ConfigEntry

if TYPE_CHECKING:
    from ..entities.base import GrentonEntity
    from .hub import GrentonHub


class OshConfigEntryData(TypedDict):
    """Persisted setup data: how to reach the CLU plus its raw interface JSON."""

    ip_address: str
    port: int
    token: str
    interface: dict[str, Any]


@dataclass
class RuntimeData:
    """Live objects held only while the entry is loaded (not persisted)."""

    hub: "GrentonHub"
    entities: list["GrentonEntity"]


# A config entry whose .runtime_data is our RuntimeData.
type OshConfigEntry = ConfigEntry[RuntimeData]
