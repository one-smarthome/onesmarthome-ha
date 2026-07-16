"""Sensor platform shim.

Devices and their entities are built once in async_setup_entry (top-level
__init__). This file just hands HA the subset of already-built entities that
are SensorEntity instances.
"""
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.components.sensor import SensorEntity

from .runtime.config_entry import OshConfigEntry
from .runtime.platform_setup import add_platform_entities

async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: OshConfigEntry,
    async_add_entities: AddEntitiesCallback,
):
    # Filter the shared entity pool down to sensors and register them.
    add_platform_entities(config_entry, async_add_entities, SensorEntity)
