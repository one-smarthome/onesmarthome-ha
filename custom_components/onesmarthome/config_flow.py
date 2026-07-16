"""Initial setup flow: collect connection details and pull the interface.

The user gives the controller IP and token; we download the whole interface JSON
over HTTP and persist it in the config entry. Only this step touches the network
-- every later reload reads the stored JSON -- so transport failures are mapped
here to the right form error.

A reconfigure step re-runs the same fetch against an existing entry so the
stored interface snapshot can follow changes made in Object Manager, while a
mismatched interface id aborts rather than silently swapping installations.
"""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult
from homeassistant.core import callback

from .const import (
    CONF_INTERFACE,
    CONF_IP_ADDRESS,
    CONF_PORT,
    CONF_TOKEN,
    DEFAULT_PORT,
    DOMAIN,
)
from .options_flow import OshOptionsFlow
from .protocol.object_manager import (
    ObjectManagerAuthError,
    ObjectManagerClient,
    ObjectManagerConnectionError,
    ObjectManagerDataError,
)

_LOGGER = logging.getLogger(__name__)

_USER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_IP_ADDRESS): str,
        vol.Required(CONF_TOKEN): str,
    }
)

# Object Manager failure -> form error key shown to the user.
_ERROR_BY_EXCEPTION = {
    ObjectManagerAuthError: "invalid_auth",
    ObjectManagerConnectionError: "cannot_connect",
    ObjectManagerDataError: "invalid_data",
}


class OshConfigFlow(ConfigFlow, domain=DOMAIN):
    """Single-step flow that validates the connection and stores the interface."""

    VERSION = 2

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OshOptionsFlow:
        return OshOptionsFlow()

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            try:
                interface = await self._fetch(user_input)
            except tuple(_ERROR_BY_EXCEPTION) as err:
                errors["base"] = _ERROR_BY_EXCEPTION[type(err)]
            except Exception:  # noqa: BLE001 - surface a generic error, log detail
                _LOGGER.exception("Unexpected error fetching interface")
                errors["base"] = "unknown"
            else:
                interface_id = interface.get("id")
                if interface_id is None:
                    errors["base"] = "invalid_data"
                else:
                    await self.async_set_unique_id(str(interface_id))
                    self._abort_if_unique_id_configured()
                    return self.async_create_entry(
                        title=str(interface_id),
                        data=self._entry_data(user_input, interface),
                    )

        return self.async_show_form(
            step_id="user", data_schema=_USER_SCHEMA, errors=errors
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Re-fetch the interface and refresh an existing entry's snapshot."""
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}

        if user_input is not None:
            try:
                interface = await self._fetch(user_input)
            except tuple(_ERROR_BY_EXCEPTION) as err:
                errors["base"] = _ERROR_BY_EXCEPTION[type(err)]
            except Exception:  # noqa: BLE001 - surface a generic error, log detail
                _LOGGER.exception("Unexpected error fetching interface")
                errors["base"] = "unknown"
            else:
                interface_id = interface.get("id")
                if interface_id is None:
                    errors["base"] = "invalid_data"
                elif str(interface_id) != entry.unique_id:
                    # A different installation answered; refuse to graft its
                    # interface onto this entry.
                    return self.async_abort(reason="interface_mismatch")
                else:
                    return self.async_update_reload_and_abort(
                        entry,
                        data=self._entry_data(user_input, interface),
                    )

        schema = self.add_suggested_values_to_schema(
            _USER_SCHEMA,
            {
                CONF_IP_ADDRESS: entry.data.get(CONF_IP_ADDRESS),
                CONF_TOKEN: entry.data.get(CONF_TOKEN),
            },
        )
        return self.async_show_form(
            step_id="reconfigure", data_schema=schema, errors=errors
        )

    @staticmethod
    def _entry_data(
        user_input: dict[str, Any], interface: dict[str, Any]
    ) -> dict[str, Any]:
        """The persisted entry data for validated ``user_input``."""
        return {
            CONF_IP_ADDRESS: user_input[CONF_IP_ADDRESS],
            CONF_TOKEN: user_input[CONF_TOKEN],
            CONF_PORT: user_input.get(CONF_PORT, DEFAULT_PORT),
            CONF_INTERFACE: interface,
        }

    async def _fetch(self, user_input: dict[str, Any]) -> dict[str, Any]:
        port = user_input.get(CONF_PORT, DEFAULT_PORT)
        base_url = f"http://{user_input[CONF_IP_ADDRESS]}:{port}"
        async with ObjectManagerClient(base_url) as client:
            return await client.fetch_interface(user_input[CONF_TOKEN])
