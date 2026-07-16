"""Diagnostics download: a redacted health snapshot of one config entry.

Dumps the integration version, per-CLU connection health from the hub, how many
entities each platform carries, and the per-entity options. Secrets and
addresses (token, AES key/IV, IPs) are redacted before anything leaves the
installation.
"""

from __future__ import annotations

from typing import Any

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.components.button import ButtonEntity
from homeassistant.components.camera import Camera
from homeassistant.components.cover import CoverEntity
from homeassistant.components.diagnostics import async_redact_data
from homeassistant.components.light import LightEntity
from homeassistant.components.number import NumberEntity
from homeassistant.components.sensor import SensorEntity
from homeassistant.components.switch import SwitchEntity
from homeassistant.core import HomeAssistant
from homeassistant.loader import async_get_integration

from .const import CONF_IP_ADDRESS, CONF_TOKEN, DOMAIN
from .runtime.config_entry import OshConfigEntry

# Keys whose values never leave the install in a diagnostics dump. "pin" is the
# pre-v2 key name for the token; kept so an un-migrated entry stays redacted.
_REDACT = {CONF_TOKEN, "pin", CONF_IP_ADDRESS, "ip", "key", "iv"}

# Platform label -> the entity base class that marks membership.
_PLATFORM_CLASSES: list[tuple[str, type]] = [
    ("binary_sensor", BinarySensorEntity),
    ("button", ButtonEntity),
    ("camera", Camera),
    ("cover", CoverEntity),
    ("light", LightEntity),
    ("number", NumberEntity),
    ("sensor", SensorEntity),
    ("switch", SwitchEntity),
]


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, config_entry: OshConfigEntry
) -> dict[str, Any]:
    """Assemble the diagnostics payload for one config entry."""
    integration = await async_get_integration(hass, DOMAIN)
    runtime = config_entry.runtime_data

    entity_counts = {
        platform: sum(1 for entity in runtime.entities if isinstance(entity, cls))
        for platform, cls in _PLATFORM_CLASSES
    }

    return {
        "version": str(integration.version),
        "interface_id": config_entry.unique_id,
        "clus": async_redact_data(runtime.hub.clu_diagnostics(), _REDACT),
        "entity_counts": entity_counts,
        "options": async_redact_data(dict(config_entry.options), _REDACT),
    }
