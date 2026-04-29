"""Marstek Venus – Home Assistant Integration v2."""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PORT, Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady

from .const import (
    DOMAIN,
    DEFAULT_BAT_INTERVAL,
    DEFAULT_GRID_INTERVAL,
    DEFAULT_PV_INTERVAL,
    CONF_GRID_INTERVAL,
    CONF_PV_INTERVAL,
)
from .coordinator import MarstekCoordinator

_LOGGER = logging.getLogger(__name__)
PLATFORMS: list[Platform] = [Platform.SENSOR]
DEFAULT_PORT = 30000


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Marstek Venus from a config entry."""

    host = entry.data[CONF_HOST]
    port = entry.data.get(CONF_PORT, DEFAULT_PORT)

    # Merge data + options (options take precedence after first save)
    merged = {**entry.data, **entry.options}
    grid_interval = int(merged.get(CONF_GRID_INTERVAL, DEFAULT_GRID_INTERVAL))
    pv_interval   = int(merged.get(CONF_PV_INTERVAL,   DEFAULT_PV_INTERVAL))

    coordinator = MarstekCoordinator(
        hass,
        ip=host,
        port=port,
        bat_interval=DEFAULT_BAT_INTERVAL,
        grid_interval=grid_interval,
        pv_interval=pv_interval,
    )

    # Quick connectivity check before registering
    ok = await coordinator.async_test_connection()
    if not ok:
        raise ConfigEntryNotReady(
            f"Marstek Venus at {host}:{port} is not reachable"
        )

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator

    # Forward to sensor platform before starting loops so entities
    # are registered before the first data arrives
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Start three staggered polling loops
    await coordinator.async_start()

    # Reload when user changes options
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry and stop polling loops."""
    coordinator: MarstekCoordinator = hass.data[DOMAIN][entry.entry_id]
    await coordinator.async_stop()

    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)
    return unload_ok


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload the integration when options are changed."""
    await hass.config_entries.async_reload(entry.entry_id)
