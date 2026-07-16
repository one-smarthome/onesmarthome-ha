"""Integration entry point: wire a config entry into a live runtime.

Setup is a one-shot pipeline: parse the persisted interface JSON, stand up the
hub (which owns the CLU connections and the state mirror), build every entity
from the widgets, then start the hub's background loops and fan out to the
platforms. The hub and the flat entity list live on ``runtime_data`` so each
platform shim can pluck out its own entities.
"""

from __future__ import annotations

import logging

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from .const import CONF_TOKEN, PLATFORMS
from .entities.base import GrentonEntity
from .factory import build_entities
from .iface import parse_interface
from .runtime.config_entry import OshConfigEntry, OshConfigEntryData, RuntimeData
from .runtime.hub import GrentonHub

_LOGGER = logging.getLogger(__name__)


def _prune_orphaned_entities(
    hass: HomeAssistant, config_entry: OshConfigEntry, entities: list[GrentonEntity]
) -> None:
    """Drop registry entries whose unique_id vanished from the interface.

    After a reconfigure the stored snapshot may no longer produce some
    previously registered entities; without this sweep their registry entries
    would linger forever as unavailable ghosts.
    """
    registry = er.async_get(hass)
    known = {entity.unique_id for entity in entities}
    for reg_entry in er.async_entries_for_config_entry(registry, config_entry.entry_id):
        if reg_entry.unique_id not in known:
            _LOGGER.debug("Removing orphaned entity %s", reg_entry.entity_id)
            registry.async_remove(reg_entry.entity_id)


async def async_migrate_entry(hass: HomeAssistant, config_entry: OshConfigEntry) -> bool:
    """Migrate an older config entry to the current schema.

    v1 stored the access token under the legacy key ``pin``; v2 renames it to
    ``token``. Nothing else about the entry changes.
    """
    if config_entry.version == 1:
        data = dict(config_entry.data)
        if "pin" in data:
            data[CONF_TOKEN] = data.pop("pin")
        hass.config_entries.async_update_entry(config_entry, data=data, version=2)
    return True


async def async_setup_entry(hass: HomeAssistant, config_entry: OshConfigEntry) -> bool:
    data: OshConfigEntryData = config_entry.data  # type: ignore[assignment]
    interface = parse_interface(data["interface"])

    _LOGGER.debug(
        "Loaded interface %s with %d CLU(s), %d widget(s)",
        interface.interface_id,
        len(interface.clus),
        len(interface.widgets),
    )

    hub = GrentonHub(hass, config_entry, list(interface.clus), interface.encryption)
    entities = build_entities(interface, hub)
    config_entry.runtime_data = RuntimeData(hub=hub, entities=entities)
    _prune_orphaned_entities(hass, config_entry, entities)

    # Subscriptions are registered as entities are built, so connect afterwards.
    await hub.async_setup()

    await hass.config_entries.async_forward_entry_setups(config_entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, config_entry: OshConfigEntry) -> bool:
    await config_entry.runtime_data.hub.async_shutdown()
    return await hass.config_entries.async_unload_platforms(config_entry, PLATFORMS)
