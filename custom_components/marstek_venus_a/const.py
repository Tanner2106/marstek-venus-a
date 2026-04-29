"""Constants for Marstek Venus integration."""

DOMAIN = "marstek_venus"

# ── Default intervals (seconds) ───────────────────────────────────────────────
DEFAULT_BAT_INTERVAL  = 60    # fixed for battery SOC
DEFAULT_GRID_INTERVAL = 5
DEFAULT_PV_INTERVAL   = 10

# Time between loop starts to ensure queries never fire simultaneously
STAGGER_OFFSET = 2.0          # seconds

UDP_TIMEOUT = 4.0

# ── Config keys ───────────────────────────────────────────────────────────────
CONF_GRID_INTERVAL = "grid_interval"
CONF_PV_INTERVAL   = "pv_interval"

# Choices exposed in config/options flow
INTERVAL_OPTIONS = [5, 10, 20, 30, 60]   # seconds

# ── Dispatcher signal ─────────────────────────────────────────────────────────
SIGNAL_UPDATE = f"{DOMAIN}_update"

# ── Data keys (written by coordinator, read by sensors) ───────────────────────
KEY_SOC             = "bat_soc"
KEY_MODE            = "mode"
KEY_ONGRID          = "ongrid_power"
KEY_OFFGRID         = "offgrid_power"
KEY_BAT_POWER       = "bat_power"          # derived: pv_total - ongrid
KEY_PV_TOTAL        = "pv_total"
KEY_PV              = "pv"                 # list[dict]

# Cumulative energy counters (Wh, ever-increasing, reset on HA restart)
KEY_E_SOLAR         = "energy_solar_wh"
KEY_E_HOME          = "energy_home_wh"
KEY_E_BAT_CHARGE    = "energy_bat_charge_wh"
KEY_E_BAT_DISCHARGE = "energy_bat_discharge_wh"
