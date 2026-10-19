"""Constants for the GeoDrops integration."""

from __future__ import annotations

from typing import Final, NotRequired, TypedDict

DOMAIN: Final = "geodrops"

# Keys in entry.data.
CONF_CREDENTIALS_JSON: Final = "credentials_json"
CONF_PROJECT_ID: Final = "project_id"

# Keys in entry.options.
CONF_ALERT_HOURS: Final = "offline_alert_hours"
CONF_DEVICES: Final = "devices"  # A list of DeviceConfig.
CONF_EXPIRE_MINUTES: Final = "expire_after_minutes"
CONF_LOOKBACK_HOURS: Final = "lookback_hours"
CONF_SCAN_INTERVAL: Final = "scan_interval_minutes"
CONF_SKIP_HOURS: Final = "staleness_skip_hours"
CONF_WARN_HOURS: Final = "staleness_warn_hours"

# Keys in each DeviceConfig.
DEV_AREA: Final = "area_id"  # Optional: the HA area chosen when the probe was added.
DEV_ID: Final = "device_id"
DEV_NAME: Final = "name"
DEV_SERIAL: Final = "serial"

# Defaults, carried over from the standalone service.
# 24 h: over 60 days of history, 12 h would also have flagged a gap that
# recovered on its own.
DEFAULT_ALERT_HOURS: Final = 24
DEFAULT_EXPIRE_MINUTES: Final = 80
DEFAULT_LOOKBACK_HOURS: Final = 12
DEFAULT_SCAN_INTERVAL: Final = 20
DEFAULT_SKIP_HOURS: Final = 12
DEFAULT_WARN_HOURS: Final = 12

# The longest lookback the options allow.
MAX_LOOKBACK_HOURS: Final = 168


class DeviceConfig(TypedDict):
    """A probe as stored in entry.options[CONF_DEVICES]."""

    serial: str
    device_id: int
    name: str
    area_id: NotRequired[str]
