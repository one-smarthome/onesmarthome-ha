"""Shared glue for the per-platform setup modules.

Every HA platform file (switch, sensor, cover, ...) works the same way: take the
one shared entity pool the hub built, keep the entities whose class matches that
platform, and hand them to HA. This factors out that pattern so each platform
file stays a two-line shim.
"""

from __future__ import annotations

from typing import TypeVar

from homeassistant.helpers.entity import Entity
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .config_entry import OshConfigEntry

# Bound to Entity so callers can only ask for real HA entity types.
EntityT = TypeVar("EntityT", bound=Entity)


def add_platform_entities(
    config_entry: OshConfigEntry,
    async_add_entities: AddEntitiesCallback,
    entity_type: type[EntityT],
) -> None:
    """Register every entity of ``entity_type`` from the shared pool."""
    matching = [
        entity
        for entity in config_entry.runtime_data.entities
        if isinstance(entity, entity_type)
    ]
    if matching:
        async_add_entities(matching)
