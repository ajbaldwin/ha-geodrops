"""Polling coordinator for GeoDrops probe readings."""

from __future__ import annotations

from datetime import datetime, timedelta
import logging

from aiogeodrops import (
    DeviceReading,
    GeoDropsAccessDeniedError,
    GeoDropsAuthError,
    GeoDropsClient,
    GeoDropsError,
)

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers import device_registry as dr, issue_registry as ir
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from . import battery, const
from .battery import HISTORY_DAYS, BatteryOutlook, BatteryTrend
from .const import DeviceConfig
from .redact import redact_account
from .transform import (
    MAX_MOISTURE_CODES,
    RECALIBRATION_CODES,
    classify_staleness,
    data_age_hours,
    has_code,
)

_LOGGER = logging.getLogger(__name__)

TROUBLESHOOTING_URL = "https://github.com/ajbaldwin/ha-geodrops-hacs#troubleshooting"

# Per-probe repairs: the issue's translation key, and the nextAction codes
# that raise it. Each one's issue id is "<key>_<entry id>_<serial>".
PROBE_ISSUES = (
    # Moisture stays unknown until the test is first run.
    ("max_moisture_required", MAX_MOISTURE_CODES),
    # The calibration is 75 days old; moisture keeps reporting, degraded.
    ("max_moisture_recalibration", RECALIBRATION_CODES),
)

# The battery history is fetched twice a day (it only moves slowly), and again
# after an hour if the fetch fails.
BATTERY_REFRESH = timedelta(hours=12)
BATTERY_RETRY = timedelta(hours=1)

type GeoDropsConfigEntry = ConfigEntry[GeoDropsCoordinator]


def device_active(device: DeviceConfig) -> bool:
    """Return whether the user has the probe in service (the default)."""
    return device.get(const.DEV_ACTIVE, True)


def _newer(
    polled: DeviceReading | None, held: DeviceReading | None
) -> DeviceReading | None:
    """Return the newer reading; a table reload can serve an older row."""
    if polled is None or held is None:
        return polled or held
    if (
        polled.read_at is not None
        and held.read_at is not None
        and polled.read_at < held.read_at
    ):
        return held
    return polled


# Raised when a probe's latest reading is older than "Offline alert after",
# or, when every probe is, once for the whole entry.
PROBE_OFFLINE = "probe_offline"
DATA_DELAYED = "data_delayed"
# Raised when a probe's battery voltage says it is about to run out.
BATTERY_REPLACE = "battery_replace"


def data_delayed_issue_id(entry_id: str) -> str:
    """Return the id of the entry's "GeoDrops data delayed" repair issue."""
    return f"{DATA_DELAYED}_{entry_id}"


def offline_issue_id(entry_id: str, serial: str) -> str:
    """Return the id of a probe's offline repair issue."""
    return f"{PROBE_OFFLINE}_{entry_id}_{serial}"


def battery_issue_id(entry_id: str, serial: str) -> str:
    """Return the id of a probe's "replace the batteries" repair issue."""
    return f"{BATTERY_REPLACE}_{entry_id}_{serial}"


def access_denied_issue_id(entry_id: str) -> str:
    """Return the id of the entry's "access denied" repair issue."""
    return f"access_denied_{entry_id}"


def probe_issue_prefixes(entry_id: str) -> tuple[str, ...]:
    """Return the id prefixes of the entry's per-probe repair issues."""
    return tuple(f"{key}_{entry_id}_" for key, _ in PROBE_ISSUES)


def delete_entry_issues(hass: HomeAssistant, entry_id: str) -> None:
    """Remove every repair issue the entry raised."""
    ir.async_delete_issue(hass, const.DOMAIN, access_denied_issue_id(entry_id))
    ir.async_delete_issue(hass, const.DOMAIN, data_delayed_issue_id(entry_id))
    prefixes = (
        *probe_issue_prefixes(entry_id),
        offline_issue_id(entry_id, ""),
        battery_issue_id(entry_id, ""),
    )
    for domain, issue_id in list(ir.async_get(hass).issues):
        if domain == const.DOMAIN and issue_id.startswith(prefixes):
            ir.async_delete_issue(hass, const.DOMAIN, issue_id)


class GeoDropsCoordinator(DataUpdateCoordinator[dict[int, DeviceReading]]):
    """Polls every configured probe's latest reading in one query."""

    config_entry: GeoDropsConfigEntry

    def __init__(
        self, hass: HomeAssistant, entry: GeoDropsConfigEntry, client: GeoDropsClient
    ) -> None:
        """Poll with `client` at the entry's interval."""
        self.client = client
        # When each device's row last came back from a poll. A poll can succeed
        # yet return no row for a device (GeoDrops' table is briefly empty twice
        # a day), so availability is judged per device, not per poll.
        self._seen: dict[int, datetime] = {}
        # Probes already logged as stale, so "warn after" logs once per episode.
        self._stale: set[int] = set()
        # Each probe's battery trend, and when the history is next fetched (None:
        # at the next poll). A failed fetch keeps the trends it had.
        self._battery: dict[int, BatteryTrend] = {}
        self._battery_due: datetime | None = None
        # The probes the history was last fetched for: a new one fetches again.
        self._battery_ids: set[int] = set()
        # Each probe's voltage in the reading before its latest one. The floor
        # check needs both below it, so one bad row can't raise a repair.
        self._previous_mv: dict[int, float | None] = {}
        interval: int = entry.options.get(
            const.CONF_SCAN_INTERVAL, const.DEFAULT_SCAN_INTERVAL
        )
        super().__init__(
            hass,
            _LOGGER,
            name="GeoDrops",
            config_entry=entry,
            update_interval=timedelta(minutes=interval),
        )

    @property
    def devices(self) -> list[DeviceConfig]:
        """The probes configured in the entry's options."""
        devices: list[DeviceConfig] = self.config_entry.options.get(
            const.CONF_DEVICES, []
        )
        return devices

    @property
    def enabled_devices(self) -> list[DeviceConfig]:
        """The configured probes whose device isn't disabled in Home Assistant."""
        disabled = {
            serial
            for device in dr.async_entries_for_config_entry(
                dr.async_get(self.hass), self.config_entry.entry_id
            )
            if device.disabled_by is not None
            for domain, serial in device.identifiers
            if domain == const.DOMAIN
        }
        return [d for d in self.devices if d[const.DEV_SERIAL] not in disabled]

    @property
    def device_ids(self) -> list[int]:
        """GeoDrops device ids of the probes to poll: every enabled one."""
        return [d[const.DEV_ID] for d in self.enabled_devices]

    def is_active(self, serial: str) -> bool:
        """Return whether the probe is in service, per the entry's current options."""
        return any(
            device_active(d) for d in self.devices if d[const.DEV_SERIAL] == serial
        )

    @callback
    def set_active(self, serial: str, active: bool) -> None:
        """Take a probe out of service, or put it back, without a reload.

        The flag is stored in the options (absent means active, so they look as
        they did before), then the repairs are re-synced and the entities told
        at once rather than at the next poll.
        """
        entry = self.config_entry
        devices: list[DeviceConfig] = []
        for device in self.devices:
            if device[const.DEV_SERIAL] == serial:
                device = device.copy()
                device.pop(const.DEV_ACTIVE, None)
                if not active:
                    device[const.DEV_ACTIVE] = False
            devices.append(device)
        self.hass.config_entries.async_update_entry(
            entry, options={**entry.options, const.CONF_DEVICES: devices}
        )
        self._sync_issues(self.data or {}, dt_util.utcnow(), self.enabled_devices)
        self.async_update_listeners()

    @callback
    def async_device_updated(
        self, event: Event[dr.EventDeviceRegistryUpdatedData]
    ) -> None:
        """Re-sync the repairs at once when one of the probes is disabled or enabled."""
        data = event.data
        if data["action"] != "update" or "disabled_by" not in data["changes"]:
            return
        device = dr.async_get(self.hass).async_get(data["device_id"])
        if device is None or self.config_entry.entry_id not in device.config_entries:
            return
        self._sync_issues(self.data or {}, dt_util.utcnow(), self.enabled_devices)

    @property
    def lookback_hours(self) -> int:
        """How far back a poll looks for each probe's latest reading."""
        hours: int = self.config_entry.options.get(
            const.CONF_LOOKBACK_HOURS, const.DEFAULT_LOOKBACK_HOURS
        )
        return hours

    def reading(self, device_id: int) -> DeviceReading | None:
        """Return a probe's latest reading, or None if none has arrived yet."""
        return (self.data or {}).get(device_id)

    def battery_trend(self, device_id: int) -> BatteryTrend | None:
        """Return a probe's battery trend, or None until its history has loaded."""
        return self._battery.get(device_id)

    def battery_outlook(self, device_id: int) -> BatteryOutlook | None:
        """Return whether a probe's batteries need replacing, if known."""
        return self._outlook(device_id, self.reading(device_id))

    def _outlook(
        self, device_id: int, reading: DeviceReading | None
    ) -> BatteryOutlook | None:
        """Combine a probe's battery trend with its last two readings."""
        latest = reading.battery_mv if reading else None
        previous = self._previous_mv.get(device_id)
        both = None if latest is None or previous is None else max(latest, previous)
        return battery.battery_outlook(self._battery.get(device_id), both)

    def reading_time(self, device_id: int) -> datetime | None:
        """Return when a poll last returned a row for this probe."""
        return self._seen.get(device_id)

    async def _async_update_data(self) -> dict[int, DeviceReading]:
        # Read once per poll: it scans the device registry.
        enabled = self.enabled_devices
        ids = [d[const.DEV_ID] for d in enabled]
        if not ids:
            self._seen = {}
            self._clear_access_denied()
            self._sync_issues({}, dt_util.utcnow(), enabled)
            return {}
        # Home Assistant logs these errors, and logs get pasted into public
        # issues, so Google's text loses the project and service account. The
        # access-denied repair, shown only in the user's own UI, keeps it.
        try:
            data = await self.client.fetch_latest(ids, self.lookback_hours)
        except GeoDropsAuthError as err:
            raise ConfigEntryAuthFailed(
                translation_domain=const.DOMAIN,
                translation_key="auth_failed",
                translation_placeholders={"error": self._redact(err)},
            ) from err
        except GeoDropsAccessDeniedError as err:
            self._raise_access_denied(err)
            raise UpdateFailed(
                translation_domain=const.DOMAIN,
                translation_key="access_denied",
                translation_placeholders={"error": self._redact(err)},
            ) from err
        except GeoDropsError as err:
            raise UpdateFailed(
                translation_domain=const.DOMAIN,
                translation_key="query_failed",
                translation_placeholders={"error": self._redact(err)},
            ) from err
        self._clear_access_denied()
        now = dt_util.utcnow()
        for device_id in data:
            self._seen[device_id] = now
        # A device missing from this poll keeps its last reading; the sensors'
        # expire window decides when that is too old to show.
        previous = self.data or {}
        merged: dict[int, DeviceReading] = {}
        for device_id in ids:
            held = previous.get(device_id)
            reading = _newer(data.get(device_id), held)
            if reading is not None:
                merged[device_id] = reading
                if held is not None and reading.read_at != held.read_at:
                    self._previous_mv[device_id] = held.battery_mv
        self._seen = {d: t for d, t in self._seen.items() if d in ids}
        self._previous_mv = {d: v for d, v in self._previous_mv.items() if d in ids}
        await self._refresh_battery(ids, now)
        self._sync_issues(merged, now, enabled)
        return merged

    async def _refresh_battery(self, ids: list[int], now: datetime) -> None:
        """Fetch the battery history when it is due.

        It is a second query, and the trend only matters to the battery
        sensor and repair, so a failure must not fail the poll.
        """
        if set(ids) != self._battery_ids:
            # A probe re-enabled in Home Assistant shouldn't wait half a day.
            self._battery_due = None
        if self._battery_due is not None and now < self._battery_due:
            return
        self._battery_ids = set(ids)
        try:
            history = await self.client.fetch_battery_history(ids, HISTORY_DAYS)
        except GeoDropsError as err:
            self._battery_due = now + BATTERY_RETRY
            _LOGGER.debug("Battery history query failed: %s", self._redact(err))
            return
        except (TypeError, ValueError) as err:
            # A row aiogeodrops can't parse (e.g. after GeoDrops changes a
            # column's type) mustn't take the readings down with it.
            self._battery_due = now + BATTERY_RETRY
            _LOGGER.debug("Battery history couldn't be read: %s", err)
            return
        self._battery_due = now + BATTERY_REFRESH
        trends: dict[int, BatteryTrend] = {}
        for device_id in ids:
            trend = battery.battery_trend(history.get(device_id, []))
            held = self._battery.get(device_id)
            # A table reload can serve only older rows: keep what we had.
            if (
                held is not None
                and held.daily
                and (not trend.daily or trend.daily[-1][0] < held.daily[-1][0])
            ):
                trend = held
            trends[device_id] = trend
        self._battery = trends

    def _sync_issues(
        self,
        readings: dict[int, DeviceReading],
        now: datetime,
        enabled: list[DeviceConfig],
    ) -> None:
        """Bring the staleness log and every repair up to date."""
        self._log_staleness(readings, now, enabled)
        self._sync_probe_issues(readings, enabled)
        self._sync_offline_issues(readings, now, enabled)
        self._sync_battery_issues(readings, enabled)

    def _redact(self, err: GeoDropsError) -> str:
        """Strip the user's GCP account from the error, and return its text.

        The error itself is rewritten too: it is chained to the one raised, and
        Home Assistant's debug log prints the whole chain.
        """
        err.args = (redact_account(str(err), self.config_entry.data),)
        return str(err)

    def _raise_access_denied(self, err: GeoDropsAccessDeniedError) -> None:
        """Only a change in GCP fixes a 403, so tell the user in Repairs."""
        ir.async_create_issue(
            self.hass,
            const.DOMAIN,
            access_denied_issue_id(self.config_entry.entry_id),
            is_fixable=False,
            severity=ir.IssueSeverity.ERROR,
            translation_key="access_denied",
            translation_placeholders={
                "project_id": self.config_entry.data[const.CONF_PROJECT_ID],
                "error": str(err),
            },
            learn_more_url=TROUBLESHOOTING_URL,
        )

    def _clear_access_denied(self) -> None:
        """Remove the repair issue once a poll succeeds."""
        ir.async_delete_issue(
            self.hass, const.DOMAIN, access_denied_issue_id(self.config_entry.entry_id)
        )

    def _sync_probe_issues(
        self, readings: dict[int, DeviceReading], enabled: list[DeviceConfig]
    ) -> None:
        """Raise a repair for each probe GeoDrops wants max-moisture calibrated.

        Only the user can run the test, in GeoDrops' app, so it is worth a
        repair. Each issue clears once its code goes away. A probe with no
        reading or no nextAction column keeps its issues as they are. An
        inactive or disabled probe has none: they drop with the sweep below.
        """
        entry_id = self.config_entry.entry_id
        wanted: set[str] = set()
        for device in enabled:
            if not device_active(device):
                continue
            serial = device[const.DEV_SERIAL]
            reading = readings.get(device[const.DEV_ID])
            for key, codes in PROBE_ISSUES:
                issue_id = f"{key}_{entry_id}_{serial}"
                wanted.add(issue_id)
                needed = (
                    None if reading is None else has_code(reading.next_action, codes)
                )
                if needed:
                    ir.async_create_issue(
                        self.hass,
                        const.DOMAIN,
                        issue_id,
                        is_fixable=False,
                        severity=ir.IssueSeverity.WARNING,
                        translation_key=key,
                        translation_placeholders={
                            "name": device[const.DEV_NAME],
                            "serial": serial,
                        },
                        learn_more_url=TROUBLESHOOTING_URL,
                    )
                elif needed is False:
                    ir.async_delete_issue(self.hass, const.DOMAIN, issue_id)
        # Probes removed from the options, or out of service, take their issues
        # with them.
        prefixes = probe_issue_prefixes(entry_id)
        for domain, issue_id in list(ir.async_get(self.hass).issues):
            if (
                domain == const.DOMAIN
                and issue_id.startswith(prefixes)
                and issue_id not in wanted
            ):
                ir.async_delete_issue(self.hass, const.DOMAIN, issue_id)

    def _sync_battery_issues(
        self, readings: dict[int, DeviceReading], enabled: list[DeviceConfig]
    ) -> None:
        """Raise a repair for each probe whose batteries need replacing now.

        Each clears once the outlook is better. A probe whose outlook is unknown
        (its history hasn't loaded yet) keeps its issue as it is. An inactive or
        disabled probe has none: they drop with the sweep below.
        """
        entry_id = self.config_entry.entry_id
        wanted: set[str] = set()
        for device in enabled:
            if not device_active(device):
                continue
            serial = device[const.DEV_SERIAL]
            issue_id = battery_issue_id(entry_id, serial)
            wanted.add(issue_id)
            # From `readings`, not self.data: that isn't updated until the poll ends.
            outlook = self._outlook(
                device[const.DEV_ID], readings.get(device[const.DEV_ID])
            )
            if outlook == "now":
                ir.async_create_issue(
                    self.hass,
                    const.DOMAIN,
                    issue_id,
                    is_fixable=False,
                    severity=ir.IssueSeverity.ERROR,
                    translation_key=BATTERY_REPLACE,
                    translation_placeholders={
                        "name": device[const.DEV_NAME],
                        "serial": serial,
                    },
                    learn_more_url=TROUBLESHOOTING_URL,
                )
            elif outlook is not None:
                ir.async_delete_issue(self.hass, const.DOMAIN, issue_id)
        # Removed, disabled and inactive probes take their issues with them.
        prefix = battery_issue_id(entry_id, "")
        for domain, issue_id in list(ir.async_get(self.hass).issues):
            if (
                domain == const.DOMAIN
                and issue_id.startswith(prefix)
                and issue_id not in wanted
            ):
                ir.async_delete_issue(self.hass, const.DOMAIN, issue_id)

    def _sync_offline_issues(
        self,
        readings: dict[int, DeviceReading],
        now: datetime,
        enabled: list[DeviceConfig],
    ) -> None:
        """Raise a repair for each probe silent past "Offline alert after".

        When two or more probes are silent and none is reporting, the cause is
        GeoDrops' data rather than the probes, so one entry-wide issue replaces
        the per-probe ones. A probe with no reading (after a restart, silent for
        longer than the lookback) keeps its issues as they are: they persist.

        Inactive and disabled probes raise none and never count as silent. An
        inactive probe that is reporting still shows the data is flowing.
        """
        options = self.config_entry.options
        hours: int = options.get(const.CONF_ALERT_HOURS, const.DEFAULT_ALERT_HOURS)
        entry_id = self.config_entry.entry_id
        active = [d for d in enabled if device_active(d)]
        offline: list[DeviceConfig] = []
        fresh: list[DeviceConfig] = []
        for device in enabled:
            reading = readings.get(device[const.DEV_ID])
            age = None if reading is None else data_age_hours(reading, now)
            if age is None:
                continue
            if age <= hours:
                fresh.append(device)
            elif device_active(device):
                offline.append(device)
        delayed_id = data_delayed_issue_id(entry_id)
        registry = ir.async_get(self.hass)
        if len(active) >= 2 and len(offline) >= 2 and not fresh:
            ir.async_create_issue(
                self.hass,
                const.DOMAIN,
                delayed_id,
                is_fixable=False,
                is_persistent=True,
                severity=ir.IssueSeverity.WARNING,
                translation_key=DATA_DELAYED,
                translation_placeholders={"hours": str(hours)},
                learn_more_url=TROUBLESHOOTING_URL,
            )
            wanted: set[str] = set()
        else:
            # Fewer than two probes in service can't be "every probe" silent.
            if fresh or len(active) < 2:
                ir.async_delete_issue(self.hass, const.DOMAIN, delayed_id)
            delayed = registry.async_get_issue(const.DOMAIN, delayed_id) is not None
            wanted = {
                offline_issue_id(entry_id, d[const.DEV_SERIAL])
                for d in active
                if d not in fresh
            }
            for device in [] if delayed else offline:
                ir.async_create_issue(
                    self.hass,
                    const.DOMAIN,
                    offline_issue_id(entry_id, device[const.DEV_SERIAL]),
                    is_fixable=False,
                    is_persistent=True,
                    severity=ir.IssueSeverity.WARNING,
                    translation_key=PROBE_OFFLINE,
                    translation_placeholders={
                        "name": device[const.DEV_NAME],
                        "serial": device[const.DEV_SERIAL],
                        "hours": str(hours),
                    },
                    learn_more_url=TROUBLESHOOTING_URL,
                )
        # Reporting, inactive, disabled and removed probes and, under the
        # entry-wide issue, every probe drop their offline issues.
        prefix = offline_issue_id(entry_id, "")
        for domain, issue_id in list(registry.issues):
            if (
                domain == const.DOMAIN
                and issue_id.startswith(prefix)
                and issue_id not in wanted
            ):
                ir.async_delete_issue(self.hass, const.DOMAIN, issue_id)

    def _log_staleness(
        self,
        readings: dict[int, DeviceReading],
        now: datetime,
        enabled: list[DeviceConfig],
    ) -> None:
        """Warn once when a probe's data passes "warn after"; note when it recovers."""
        options = self.config_entry.options
        warn: int = options.get(const.CONF_WARN_HOURS, const.DEFAULT_WARN_HOURS)
        skip: int = options.get(const.CONF_SKIP_HOURS, const.DEFAULT_SKIP_HOURS)
        active = [d for d in enabled if device_active(d)]
        # Out of service ends an episode: back in service, it can warn again.
        self._stale &= {d[const.DEV_ID] for d in active}
        for device in active:
            device_id = device[const.DEV_ID]
            reading = readings.get(device_id)
            age = None if reading is None else data_age_hours(reading, now)
            stale = age is not None and classify_staleness(age, warn, skip) != "ok"
            if stale and device_id not in self._stale:
                self._stale.add(device_id)
                _LOGGER.warning(
                    "Probe %s (%s) has not reported for %.1f hours "
                    "(warn after %s hours)",
                    device[const.DEV_NAME],
                    device[const.DEV_SERIAL],
                    age,
                    warn,
                )
            elif not stale and device_id in self._stale and age is not None:
                self._stale.discard(device_id)
                _LOGGER.info(
                    "Probe %s (%s) is reporting again",
                    device[const.DEV_NAME],
                    device[const.DEV_SERIAL],
                )
