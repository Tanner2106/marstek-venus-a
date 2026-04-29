"""
Marstek Venus – Coordinator
Three independent async polling loops, serialised through a single UDP lock
so queries never overlap even when timers fire simultaneously.

Loop schedule (staggered at startup):
  t = 0 s   → battery loop   (ES.GetMode for SOC)      every BAT_INTERVAL
  t = 2 s   → grid loop      (ES.GetMode for power)    every grid_interval
  t = 4 s   → PV loop        (PV.GetStatus id=0)       every pv_interval
"""

from __future__ import annotations

import asyncio
import json
import logging
import socket
import time
from typing import Any, Callable

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.event import async_call_later

from .const import (
    UDP_TIMEOUT,
    STAGGER_OFFSET,
    KEY_SOC, KEY_MODE,
    KEY_ONGRID, KEY_OFFGRID,
    KEY_BAT_POWER, KEY_PV_TOTAL, KEY_PV,
    KEY_E_SOLAR, KEY_E_HOME,
    KEY_E_BAT_CHARGE, KEY_E_BAT_DISCHARGE,
)

_LOGGER = logging.getLogger(__name__)


# ── Low-level sync UDP (runs in executor) ─────────────────────────────────────

def _sync_udp(ip: str, port: int, payload: dict) -> dict | None:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(UDP_TIMEOUT)
        s.sendto(json.dumps(payload).encode(), (ip, port))
        data, _ = s.recvfrom(4096)
        return json.loads(data.decode())
    except Exception:
        return None
    finally:
        s.close()


# ── Coordinator ───────────────────────────────────────────────────────────────

class MarstekCoordinator:
    """
    Manages three independent polling loops for battery, grid and PV data.
    All UDP calls are serialised through self._lock so they never overlap.
    Listeners (sensor entities) are notified after every successful update.
    """

    def __init__(
        self,
        hass: HomeAssistant,
        ip: str,
        port: int,
        bat_interval: int,
        grid_interval: int,
        pv_interval: int,
    ) -> None:
        self.hass          = hass
        self.ip            = ip
        self.port          = port
        self.bat_interval  = bat_interval
        self.grid_interval = grid_interval
        self.pv_interval   = pv_interval

        # Shared data dict – read by sensor entities
        self.data: dict[str, Any] = {
            KEY_SOC:             None,
            KEY_MODE:            None,
            KEY_ONGRID:          None,
            KEY_OFFGRID:         None,
            KEY_BAT_POWER:       None,
            KEY_PV_TOTAL:        None,
            KEY_PV:              [{"power": None, "voltage": None,
                                   "current": None, "state": None}] * 4,
            KEY_E_SOLAR:         0.0,
            KEY_E_HOME:          0.0,
            KEY_E_BAT_CHARGE:    0.0,
            KEY_E_BAT_DISCHARGE: 0.0,
        }

        # Listeners registered by sensor entities
        self._listeners: list[Callable[[], None]] = []

        # Serialise all UDP calls
        self._lock = asyncio.Lock()

        # Energy integration timestamps
        self._ts_pv:   float | None = None
        self._ts_grid: float | None = None

        # Async task handles
        self._tasks: list[asyncio.Task] = []
        self._running = False

    # ── Public API ───────────────────────────────────────────────────────────

    @callback
    def async_add_listener(self, update_cb: Callable[[], None]) -> Callable[[], None]:
        """Register a listener. Returns an unsubscribe callable."""
        self._listeners.append(update_cb)

        @callback
        def _remove():
            self._listeners.remove(update_cb)

        return _remove

    def update_intervals(self, grid_interval: int, pv_interval: int) -> None:
        """Called when options change; loops pick up new values on next iteration."""
        self.grid_interval = grid_interval
        self.pv_interval   = pv_interval
        _LOGGER.debug("Marstek intervals updated: grid=%ds pv=%ds",
                      grid_interval, pv_interval)

    async def async_start(self) -> None:
        """Start the three polling loops with staggered start times."""
        if self._running:
            return
        self._running = True

        # Stagger: battery first, then grid, then PV
        self._tasks.append(
            asyncio.ensure_future(self._loop_battery())
        )
        await asyncio.sleep(STAGGER_OFFSET)
        self._tasks.append(
            asyncio.ensure_future(self._loop_grid())
        )
        await asyncio.sleep(STAGGER_OFFSET)
        self._tasks.append(
            asyncio.ensure_future(self._loop_pv())
        )

    async def async_stop(self) -> None:
        """Cancel all running tasks."""
        self._running = False
        for task in self._tasks:
            task.cancel()
        self._tasks.clear()

    async def async_test_connection(self) -> bool:
        """Quick reachability check used by config flow."""
        resp = await self._udp({"id": 0, "method": "Marstek.GetDevice",
                                "params": {"ble_mac": "0"}})
        return resp is not None and "result" in resp

    # ── UDP wrapper (serialised) ──────────────────────────────────────────────

    async def _udp(self, payload: dict) -> dict | None:
        async with self._lock:
            return await self.hass.async_add_executor_job(
                _sync_udp, self.ip, self.port, payload
            )

    # ── Polling loops ─────────────────────────────────────────────────────────

    async def _loop_battery(self) -> None:
        while self._running:
            await self._fetch_battery()
            await asyncio.sleep(self.bat_interval)

    async def _loop_grid(self) -> None:
        while self._running:
            await self._fetch_grid()
            await asyncio.sleep(self.grid_interval)

    async def _loop_pv(self) -> None:
        while self._running:
            await self._fetch_pv()
            await asyncio.sleep(self.pv_interval)

    # ── Fetch functions ───────────────────────────────────────────────────────

    async def _fetch_battery(self) -> None:
        """ES.GetMode – read SOC and operating mode."""
        resp = await self._udp({"id": 1, "method": "ES.GetMode",
                                "params": {"id": 0}})
        if resp and "result" in resp:
            r = resp["result"]
            self.data[KEY_SOC]  = r.get("bat_soc")
            self.data[KEY_MODE] = r.get("mode")
            _LOGGER.debug("Battery SOC=%s", self.data[KEY_SOC])
            self._notify()
        else:
            _LOGGER.debug("No response from ES.GetMode (battery)")

    async def _fetch_grid(self) -> None:
        """ES.GetMode – read ongrid / offgrid power, compute battery power."""
        resp = await self._udp({"id": 2, "method": "ES.GetMode",
                                "params": {"id": 0}})
        if resp and "result" in resp:
            r = resp["result"]
            ongrid  = r.get("ongrid_power")
            offgrid = r.get("offgrid_power")
            self.data[KEY_ONGRID]  = ongrid
            self.data[KEY_OFFGRID] = offgrid

            # Derived: battery power = solar - home load
            pv_total = self.data.get(KEY_PV_TOTAL)
            if pv_total is not None and ongrid is not None:
                self.data[KEY_BAT_POWER] = round(pv_total - ongrid, 1)
            else:
                self.data[KEY_BAT_POWER] = None

            # Energy integration for home delivery and battery flows
            now = time.monotonic()
            if self._ts_grid is not None:
                dt_h = (now - self._ts_grid) / 3600.0

                if ongrid is not None:
                    self.data[KEY_E_HOME] += max(ongrid, 0) * dt_h

                bat_w = self.data.get(KEY_BAT_POWER)
                if bat_w is not None:
                    if bat_w >= 0:
                        self.data[KEY_E_BAT_CHARGE]    += bat_w * dt_h
                    else:
                        self.data[KEY_E_BAT_DISCHARGE] += abs(bat_w) * dt_h

            self._ts_grid = now
            _LOGGER.debug("Grid ongrid=%s bat_power=%s",
                          ongrid, self.data[KEY_BAT_POWER])
            self._notify()
        else:
            _LOGGER.debug("No response from ES.GetMode (grid)")

    async def _fetch_pv(self) -> None:
        """PV.GetStatus id=0 – read all 4 MPPT strings."""
        resp = await self._udp({"id": 3, "method": "PV.GetStatus",
                                "params": {"id": 0}})
        if resp and "result" in resp:
            res   = resp["result"]
            total = 0.0
            pv    = []
            for i in range(1, 5):
                raw_p = res.get(f"pv{i}_power")
                v     = res.get(f"pv{i}_voltage")
                a     = res.get(f"pv{i}_current")
                state = res.get(f"pv{i}_state")
                # ⚠ only pv1_power is reported ×10 by Venus A firmware
                if i == 1:
                    p = round(raw_p / 10, 1) if raw_p is not None else None
                else:
                    p = float(raw_p) if raw_p is not None else None
                pv.append({"power": p, "voltage": v, "current": a, "state": state})
                if p is not None:
                    total += p

            self.data[KEY_PV]       = pv
            self.data[KEY_PV_TOTAL] = round(total, 1)

            # Refresh derived battery power if grid data is available
            ongrid = self.data.get(KEY_ONGRID)
            if ongrid is not None:
                self.data[KEY_BAT_POWER] = round(total - ongrid, 1)

            # Energy integration for solar production
            now = time.monotonic()
            if self._ts_pv is not None:
                dt_h = (now - self._ts_pv) / 3600.0
                self.data[KEY_E_SOLAR] += total * dt_h
            self._ts_pv = now

            _LOGGER.debug("PV total=%s W", self.data[KEY_PV_TOTAL])
            self._notify()
        else:
            _LOGGER.debug("No response from PV.GetStatus")

    # ── Notify listeners ─────────────────────────────────────────────────────

    @callback
    def _notify(self) -> None:
        for cb in self._listeners:
            cb()
