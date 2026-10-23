"""Diagnostics for GeoDrops."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from aiogeodrops import DeviceReading

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant

from . import const
from .coordinator import GeoDropsConfigEntry
from .redact import redact_account

# The key is a credential; the project id identifies the user's GCP account.
TO_REDACT = {const.CONF_CREDENTIALS_JSON, const.CONF_PROJECT_ID}


def _reading_dict(reading: DeviceReading) -> dict[str, Any]:
    """Return a reading as JSON-ready data (Home Assistant can't encode a frozenset)."""
    data = asdict(reading)
    if reading.next_action is not None:
        data["next_action"] = sorted(reading.next_action)
    return data


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: GeoDropsConfigEntry
) -> dict[str, Any]:
    """Return settings, poll status and each probe's last reading."""
    coordinator = entry.runtime_data
    last_exception: str | None = None
    if (err := coordinator.last_exception) is not None:
        last_exception = redact_account(f"{type(err).__name__}: {err}", entry.data)
    probes: dict[str, dict[str, Any]] = {}
    for device in coordinator.devices:
        device_id = device[const.DEV_ID]
        reading = coordinator.reading(device_id)
        seen = coordinator.reading_time(device_id)
        trend = coordinator.battery_trend(device_id)
        probes[device[const.DEV_SERIAL]] = {
            "device_id": device_id,
            "last_seen_in_poll": seen.isoformat() if seen else None,
            "reading": _reading_dict(reading) if reading else None,
            "battery": {
                "outlook": coordinator.battery_outlook(device_id),
                "slope_mv_per_day": trend.slope if trend else None,
                "daily_mv": [[day.isoformat(), mv] for day, mv in trend.daily]
                if trend
                else [],
            },
        }
    interval = coordinator.update_interval
    return {
        "entry": {
            "data": async_redact_data(entry.data, TO_REDACT),
            "options": dict(entry.options),
        },
        "coordinator": {
            "last_update_success": coordinator.last_update_success,
            "last_exception": last_exception,
            "update_interval_seconds": interval.total_seconds() if interval else None,
            # Columns GeoDrops' table lacked at the last check: the readings'
            # fields they feed are None, so their sensors show unknown.
            "missing_columns": sorted(coordinator.client.missing_columns),
        },
        "probes": probes,
    }
