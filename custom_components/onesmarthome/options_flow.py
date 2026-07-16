"""Options flow: re-tune a single configurable entity after setup.

Two stages. The user first chooses an entity from a picker; that entity then
walks its own ordered list of option screens (see
:class:`.entities.configurable.EntityConfigurator`). Every screen reuses the
same HA step id ``configure`` -- the cursor in this driver, not the step id,
decides which screen is on show, so an entity can expose any number of screens
without this module knowing their names.

A screen may decline to ask anything for the current settings (its builder
returns ``None``); the driver simply skips it and moves to the next.
"""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigFlowResult, OptionsFlow
from homeassistant.helpers import selector

from .entities.configurable import EntityConfigurator, FormContext


class OshOptionsFlow(OptionsFlow):
    """Drives the per-entity option screens."""

    _target_uid: str | None = None
    _collected: dict[str, Any]
    _cursor: int

    def __init__(self) -> None:
        self._collected = {}
        self._cursor = 0

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        candidates = self._candidates()
        choices = sorted(e.entity_id for e in candidates if e.entity_id)
        if not choices:
            return self.async_abort(reason="nothing_to_configure")

        if user_input is not None:
            picked = user_input["entity"]
            target = next((e for e in candidates if e.entity_id == picked), None)
            if target is None:
                return self.async_abort(reason="entity_missing")
            self._target_uid = target.unique_id
            self._collected = {}
            self._cursor = 0
            return await self.async_step_configure()

        picker = selector.EntitySelector(
            selector.EntitySelectorConfig(include_entities=choices, multiple=False)
        )
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema({vol.Required("entity"): picker}),
        )

    async def async_step_configure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        entity = self._target()
        if entity is None:
            return self.async_abort(reason="entity_missing")

        forms = entity.option_forms()
        if not forms:
            return self.async_abort(reason="nothing_to_configure")

        if user_input is not None:
            self._collected.update(user_input)
            self._cursor += 1

        context = FormContext(
            stored=entity.current_settings(), gathered=dict(self._collected)
        )

        # Walk forward over screens with nothing to ask until one wants input.
        while self._cursor < len(forms):
            schema = forms[self._cursor].build(context)
            if schema is not None:
                return self.async_show_form(
                    step_id="configure",
                    data_schema=schema,
                    description_placeholders={
                        "entity_name": entity.name,
                        "position": str(self._cursor + 1),
                        "count": str(len(forms)),
                    },
                )
            self._cursor += 1

        options = entity.store_settings(self._collected)
        return self.async_create_entry(title="", data=options)

    def _target(self) -> Any | None:
        return next(
            (e for e in self._candidates() if e.unique_id == self._target_uid),
            None,
        )

    def _candidates(self) -> list[Any]:
        entities = self.config_entry.runtime_data.entities  # type: ignore[attr-defined]
        return [e for e in entities if isinstance(e, EntityConfigurator)]
