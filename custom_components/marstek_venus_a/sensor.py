"""Sensor platform for Marstek Venus."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    PERCENTAGE,
    UnitOfEnergy,
    UnitOfPower,
    UnitOfElectricPotential,
    UnitOfElectricCurrent,
    EntityCategory,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    DOMAIN,
    KEY_SOC, KEY_MODE,
    KEY_ONGRID, KEY_OFFGRID,
    KEY_BAT_POWER, KEY_PV_TOTAL, KEY_PV,
    KEY_E_SOLAR, KEY_E_HOME,
    KEY_E_BAT_CHARGE, KEY_E_BAT_DISCHARGE,
)
from .coordinator import MarstekCoordinator


# ── Description extension ─────────────────────────────────────────────────────

@dataclass(frozen=True, kw_only=True)
class MarstekSensorDesc(SensorEntityDescription):
    data_key: str = ""
    # For MPPT strings: which index (0-3) and which sub-key
    mppt_index: int | None = None
    mppt_sub:   str | None = None
    # Optional transform
    value_fn: Any = None


# ── Static sensor definitions ─────────────────────────────────────────────────

SENSORS: tuple[MarstekSensorDesc, ...] = (

    # ── Battery ──────────────────────────────────────────────────────────────
    MarstekSensorDesc(
        key="battery_soc",
        name="Battery SOC",
        data_key=KEY_SOC,
        native_unit_of_measurement=PERCENTAGE,
        device_class=SensorDeviceClass.BATTERY,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:battery",
        suggested_display_precision=0,
    ),

    # ── Grid / load ───────────────────────────────────────────────────────────
    MarstekSensorDesc(
        key="ongrid_power",
        name="Home Power (on-grid)",
        data_key=KEY_ONGRID,
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:home-lightning-bolt",
        suggested_display_precision=0,
    ),
    MarstekSensorDesc(
        key="offgrid_power",
        name="Off-Grid Power",
        data_key=KEY_OFFGRID,
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:home-lightning-bolt-outline",
        suggested_display_precision=0,
    ),

    # ── Solar ────────────────────────────────────────────────────────────────
    MarstekSensorDesc(
        key="pv_power_total",
        name="PV Power Total",
        data_key=KEY_PV_TOTAL,
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:solar-power",
        suggested_display_precision=1,
    ),

    # ── Battery power (derived) ───────────────────────────────────────────────
    MarstekSensorDesc(
        key="battery_power",
        name="Battery Power",
        data_key=KEY_BAT_POWER,
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:battery-charging",
        suggested_display_precision=1,
        # Positive = charging, negative = discharging
    ),

    # ── Cumulative energy (daily totals via HA statistics) ────────────────────
    MarstekSensorDesc(
        key="energy_solar_produced",
        name="Energy Solar Produced (today)",
        data_key=KEY_E_SOLAR,
        native_unit_of_measurement=UnitOfEnergy.WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        icon="mdi:solar-power-variant",
        suggested_display_precision=2,
        value_fn=lambda v: round(v, 2),
    ),
    MarstekSensorDesc(
        key="energy_home_delivered",
        name="Energy Delivered to Home (today)",
        data_key=KEY_E_HOME,
        native_unit_of_measurement=UnitOfEnergy.WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        icon="mdi:home-lightning-bolt",
        suggested_display_precision=2,
        value_fn=lambda v: round(v, 2),
    ),
    MarstekSensorDesc(
        key="energy_battery_charged",
        name="Energy Battery Charged (today)",
        data_key=KEY_E_BAT_CHARGE,
        native_unit_of_measurement=UnitOfEnergy.WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        icon="mdi:battery-arrow-up",
        suggested_display_precision=2,
        value_fn=lambda v: round(v, 2),
    ),
    MarstekSensorDesc(
        key="energy_battery_discharged",
        name="Energy Battery Discharged (today)",
        data_key=KEY_E_BAT_DISCHARGE,
        native_unit_of_measurement=UnitOfEnergy.WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        icon="mdi:battery-arrow-down",
        suggested_display_precision=2,
        value_fn=lambda v: round(v, 2),
    ),
)

# MPPT per-string sensors (generated dynamically)
_MPPT_SUB_SENSORS: tuple[tuple[str, str, str, Any, str], ...] = (
    # (sub_key, unit, device_class, icon)
    ("power",   UnitOfPower.WATT,             SensorDeviceClass.POWER,   "mdi:solar-panel"),
    ("voltage", UnitOfElectricPotential.VOLT,  SensorDeviceClass.VOLTAGE, "mdi:sine-wave"),
    ("current", UnitOfElectricCurrent.AMPERE,  SensorDeviceClass.CURRENT, "mdi:current-dc"),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: MarstekCoordinator = hass.data[DOMAIN][entry.entry_id]
    entities: list[SensorEntity] = []

    # Static sensors
    for desc in SENSORS:
        entities.append(MarstekSensor(coordinator, entry, desc))

    # MPPT per-string sensors
    for i in range(4):
        n = i + 1
        for sub_key, unit, dev_class, icon in _MPPT_SUB_SENSORS:
            state_cls = (SensorStateClass.MEASUREMENT if sub_key == "power"
                         else SensorStateClass.MEASUREMENT)
            desc = MarstekSensorDesc(
                key=f"mppt_{n}_{sub_key}",
                name=f"MPPT {n} {sub_key.capitalize()}",
                data_key=KEY_PV,
                mppt_index=i,
                mppt_sub=sub_key,
                native_unit_of_measurement=unit,
                device_class=dev_class,
                state_class=state_cls,
                icon=icon,
                suggested_display_precision=1,
            )
            entities.append(MarstekSensor(coordinator, entry, desc))

    async_add_entities(entities)


# ── Entity base ───────────────────────────────────────────────────────────────

class MarstekSensor(SensorEntity):
    """A sensor entity that subscribes to the Marstek coordinator."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: MarstekCoordinator,
        entry: ConfigEntry,
        description: MarstekSensorDesc,
    ) -> None:
        self.entity_description  = description
        self._coordinator        = coordinator
        self._attr_unique_id     = f"{entry.unique_id}_{description.key}"
        self._attr_device_info   = DeviceInfo(
            identifiers={(DOMAIN, entry.unique_id or entry.entry_id)},
            name=f"Marstek Venus ({coordinator.ip})",
            manufacturer="Marstek",
            model="Venus A",
            configuration_url=f"http://{coordinator.ip}",
        )

    async def async_added_to_hass(self) -> None:
        """Subscribe to coordinator updates."""
        self.async_on_remove(
            self._coordinator.async_add_listener(self._handle_update)
        )

    @callback
    def _handle_update(self) -> None:
        self.async_write_ha_state()

    @property
    def native_value(self) -> Any:
        desc = self.entity_description
        raw  = self._coordinator.data.get(desc.data_key)

        # MPPT sub-key lookup
        if desc.mppt_index is not None and desc.mppt_sub is not None:
            if not isinstance(raw, list) or desc.mppt_index >= len(raw):
                return None
            raw = raw[desc.mppt_index].get(desc.mppt_sub)

        if raw is None:
            return None
        if desc.value_fn is not None:
            return desc.value_fn(raw)
        return raw

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """For battery power sensor, add a human-readable direction label."""
        if self.entity_description.key == "battery_power":
            val = self.native_value
            if val is None:
                return None
            return {"direction": "charging" if val >= 0 else "discharging"}
        return None
