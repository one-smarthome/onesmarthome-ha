"""Per-entity user settings, stored in the config entry's options.

A handful of entities expose knobs a user can tweak after setup -- a sensor's
device class, a number's display mode, and so on. Such an entity mixes in
:class:`EntityConfigurator` and lists the screens it wants the options dialog to
show by overriding :meth:`option_forms`. Each screen builds its own voluptuous
schema from the values gathered so far and may opt out (return ``None``) when it
has nothing to ask, in which case the dialog simply moves on.

Settings are namespaced per entity beneath ``options["entities"][<unique_id>]``
so several entities can keep independent configuration in one entry.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import voluptuous as vol

from ..runtime.hub import GrentonHub

# Top-level options bucket that holds every entity's settings.
_SETTINGS_BUCKET = "entities"


@dataclass
class FormContext:
    """What a screen builder gets to work with.

    ``stored`` is the entity's previously saved settings (used to pre-fill
    defaults); ``gathered`` is everything the user has answered earlier in the
    current dialog, so a later screen can react to an earlier choice.
    """

    stored: dict[str, Any]
    gathered: dict[str, Any]


# A screen builder turns the running context into a schema, or None to skip.
ScreenBuilder = Callable[[FormContext], "vol.Schema | None"]


@dataclass(frozen=True)
class OptionForm:
    """One screen of an entity's options dialog."""

    name: str
    build: ScreenBuilder


class EntityConfigurator:
    """Mixin granting an entity a settings dialog and persistence.

    Concrete entities override :meth:`option_forms`. The persistence helpers
    here read the saved blob on construction and write it back when the dialog
    finishes; the dialog driver itself lives in ``options_flow``.
    """

    coordinator: GrentonHub
    unique_id: str

    def __init__(self) -> None:
        self._settings: dict[str, Any] = self._load()

    def option_forms(self) -> list[OptionForm]:
        """The ordered screens this entity wants the dialog to present."""
        return []

    def current_settings(self) -> dict[str, Any]:
        """A copy of the entity's persisted settings."""
        return dict(self._settings)

    def store_settings(self, answers: dict[str, Any]) -> dict[str, Any]:
        """Adopt ``answers`` and return the full options dict to hand back to HA."""
        self._settings = dict(answers)
        options = self._entry_options()
        bucket = dict(options.get(_SETTINGS_BUCKET, {}))
        bucket[self.unique_id] = self._settings
        options[_SETTINGS_BUCKET] = bucket
        return options

    def _entry_options(self) -> dict[str, Any]:
        entry = self.coordinator.config_entry
        return dict(entry.options) if entry else {}

    def _load(self) -> dict[str, Any]:
        bucket = self._entry_options().get(_SETTINGS_BUCKET, {})
        if not isinstance(bucket, dict):
            return {}
        mine = bucket.get(self.unique_id)
        return dict(mine) if isinstance(mine, dict) else {}
