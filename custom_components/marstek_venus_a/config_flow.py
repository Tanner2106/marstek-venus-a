"""Config flow for Marstek Venus integration."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.core import HomeAssistant, callback
from homeassistant.data_entry_flow import FlowResult

from .const import (
    DOMAIN,
    DEFAULT_BAT_INTERVAL,
    DEFAULT_GRID_INTERVAL,
    DEFAULT_PV_INTERVAL,
    INTERVAL_OPTIONS,
    CONF_GRID_INTERVAL,
    CONF_PV_INTERVAL,
)
from .coordinator import MarstekCoordinator

_LOGGER = logging.getLogger(__name__)

DEFAULT_PORT = 30000

_INTERVAL_SELECTOR = vol.In(INTERVAL_OPTIONS)


def _interval_schema(grid_default: int, pv_default: int) -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(CONF_GRID_INTERVAL, default=grid_default): _INTERVAL_SELECTOR,
            vol.Required(CONF_PV_INTERVAL,   default=pv_default):   _INTERVAL_SELECTOR,
        }
    )


class MarstekConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle the initial setup wizard."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            host = user_input[CONF_HOST].strip()
            port = user_input.get(CONF_PORT, DEFAULT_PORT)

            await self.async_set_unique_id(f"{host}:{port}")
            self._abort_if_unique_id_configured()

            # Test connectivity
            coordinator = MarstekCoordinator(
                self.hass, host, port,
                DEFAULT_BAT_INTERVAL,
                DEFAULT_GRID_INTERVAL,
                DEFAULT_PV_INTERVAL,
            )
            ok = await coordinator.async_test_connection()
            if not ok:
                errors["base"] = "cannot_connect"
            else:
                return self.async_create_entry(
                    title=f"Marstek Venus ({host})",
                    data={
                        CONF_HOST:          host,
                        CONF_PORT:          port,
                        CONF_GRID_INTERVAL: user_input.get(CONF_GRID_INTERVAL,
                                                           DEFAULT_GRID_INTERVAL),
                        CONF_PV_INTERVAL:   user_input.get(CONF_PV_INTERVAL,
                                                           DEFAULT_PV_INTERVAL),
                    },
                )

        schema = vol.Schema(
            {
                vol.Required(CONF_HOST, default="192.168.1.100"): str,
                vol.Required(CONF_PORT, default=DEFAULT_PORT): vol.All(
                    int, vol.Range(min=1024, max=65535)
                ),
                vol.Required(CONF_GRID_INTERVAL,
                             default=DEFAULT_GRID_INTERVAL): _INTERVAL_SELECTOR,
                vol.Required(CONF_PV_INTERVAL,
                             default=DEFAULT_PV_INTERVAL):   _INTERVAL_SELECTOR,
            }
        )
        return self.async_show_form(
            step_id="user", data_schema=schema, errors=errors
        )

    @staticmethod
    @callback
    def async_get_options_flow(entry: config_entries.ConfigEntry):
        return MarstekOptionsFlow(entry)


class MarstekOptionsFlow(config_entries.OptionsFlow):
    """Allow changing poll intervals after setup."""

    def __init__(self, entry: config_entries.ConfigEntry) -> None:
        self._entry = entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        current = {**self._entry.data, **self._entry.options}
        schema = _interval_schema(
            grid_default=current.get(CONF_GRID_INTERVAL, DEFAULT_GRID_INTERVAL),
            pv_default=current.get(CONF_PV_INTERVAL,   DEFAULT_PV_INTERVAL),
        )
        return self.async_show_form(step_id="init", data_schema=schema)
