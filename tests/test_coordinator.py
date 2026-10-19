from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock

from aiogeodrops import DeviceReading, GeoDropsAuthError, GeoDropsQueryError
import pytest

from custom_components.geodrops import const
from custom_components.geodrops.coordinator import (
    GeoDropsCoordinator,
    delete_entry_issues,
)
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.update_coordinator import UpdateFailed
from homeassistant.util import dt as dt_util


def _client(fetch):
    """A client whose fetch_latest(ids, lookback) returns (or raises from) `fetch`."""
    client = MagicMock()
    client.fetch_latest = AsyncMock(side_effect=fetch)
    return client


def _reading(device_id, pct):
    return DeviceReading(
        device_id=device_id,
        sync_delay_hours=1.0,
        moisture_index=2,
        moisture_pct=pct,
        moisture_d1=pct,
        moisture_d2=pct,
        moisture_d3=pct,
        temp_surface=20.0,
        temp_d1=20.0,
        temp_d2=20.0,
        temp_d3=20.0,
        battery_pct=90.0,
        sun_7d=5.0,
        qcn_d1=2,
        qcn_d2=2,
        qcn_d3=2,
    )


async def test_coordinator_fetches_and_maps(hass, monkeypatch):
    entry = MagicMock()
    entry.options = {
        const.CONF_DEVICES: [{"serial": "AAA111", "device_id": 1001, "name": "Front"}],
        const.CONF_SCAN_INTERVAL: 20,
        const.CONF_LOOKBACK_HOURS: 12,
    }
    client = _client(lambda ids, lb: {1001: _reading(1001, 42.0)})
    coord = GeoDropsCoordinator(hass, entry, client)
    assert coord.reading_time(1001) is None
    data = await coord._async_update_data()
    assert data[1001].moisture_pct == 42.0
    assert coord.device_ids == [1001]
    assert coord.reading_time(1001) is not None  # FIX 8: a returned row stamps the time


async def test_coordinator_does_not_stamp_success_on_failure(hass, monkeypatch):
    entry = MagicMock()
    entry.options = {
        const.CONF_DEVICES: [{"serial": "AAA111", "device_id": 1001, "name": "Front"}],
        const.CONF_SCAN_INTERVAL: 20,
        const.CONF_LOOKBACK_HOURS: 12,
    }

    def _raise(ids, lb):
        raise GeoDropsQueryError("boom")

    client = _client(_raise)
    coord = GeoDropsCoordinator(hass, entry, client)
    with pytest.raises(UpdateFailed):
        await coord._async_update_data()
    assert coord.reading_time(1001) is None


async def test_coordinator_raises_auth_failed_when_key_rejected(hass, monkeypatch):
    entry = MagicMock()
    entry.options = {
        const.CONF_DEVICES: [{"serial": "AAA111", "device_id": 1001, "name": "Front"}]
    }

    def _raise(ids, lb):
        raise GeoDropsAuthError("invalid_grant")

    client = _client(_raise)
    coord = GeoDropsCoordinator(hass, entry, client)
    with pytest.raises(ConfigEntryAuthFailed):
        await coord._async_update_data()
    assert coord.reading_time(1001) is None


def _two_device_entry():
    entry = MagicMock()
    entry.options = {
        const.CONF_DEVICES: [
            {"serial": "AAA111", "device_id": 1001, "name": "Front"},
            {"serial": "BBB222", "device_id": 1002, "name": "Back"},
        ]
    }
    return entry


async def test_poll_without_a_device_row_keeps_its_last_reading(hass, monkeypatch):
    # GeoDrops' table briefly holds no recent rows twice a day: the query succeeds
    # but returns nothing. That must not wipe the readings the last poll had.
    polls = iter(
        [
            {1001: _reading(1001, 42.0), 1002: _reading(1002, 30.0)},
            {1002: _reading(1002, 31.0)},
        ]
    )
    client = _client(lambda ids, lb: next(polls))
    coord = GeoDropsCoordinator(hass, _two_device_entry(), client)
    coord.data = await coord._async_update_data()
    first_seen = coord.reading_time(1001)
    coord.data = await coord._async_update_data()
    assert coord.reading(1001).moisture_pct == 42.0
    assert coord.reading(1002).moisture_pct == 31.0
    assert coord.reading_time(1001) == first_seen  # not refreshed by the empty poll
    assert coord.reading_time(1002) > first_seen


async def test_reading_time_is_none_until_a_row_arrives(hass, monkeypatch):
    client = _client(lambda ids, lb: {1001: _reading(1001, 42.0)})
    coord = GeoDropsCoordinator(hass, _two_device_entry(), client)
    coord.data = await coord._async_update_data()
    assert coord.reading_time(1001) is not None
    assert coord.reading_time(1002) is None
    assert coord.reading(1002) is None


async def test_removed_device_is_dropped(hass, monkeypatch):
    client = _client(lambda ids, lb: {i: _reading(i, 40.0) for i in ids})
    entry = _two_device_entry()
    coord = GeoDropsCoordinator(hass, entry, client)
    coord.data = await coord._async_update_data()
    entry.options = {
        const.CONF_DEVICES: [{"serial": "BBB222", "device_id": 1002, "name": "Back"}]
    }
    coord.data = await coord._async_update_data()
    assert coord.reading(1001) is None
    assert coord.reading_time(1001) is None


async def test_no_probes_skips_the_query(hass, monkeypatch):
    def _fail(ids, lb):
        raise AssertionError("an empty deviceId IN () query is invalid SQL")

    client = _client(_fail)
    entry = MagicMock()
    entry.options = {const.CONF_DEVICES: []}
    coord = GeoDropsCoordinator(hass, entry, client)
    assert await coord._async_update_data() == {}


def _aged_reading(device_id, hours_old):
    return DeviceReading(
        **{
            **_reading(device_id, 40.0).__dict__,
            "read_at": dt_util.utcnow() - timedelta(hours=hours_old),
        }
    )


def _stale_warnings(caplog):
    return [
        r
        for r in caplog.records
        if r.levelname == "WARNING" and "has not reported" in r.getMessage()
    ]


async def _poll(coord, monkeypatch, rows):
    coord.client.fetch_latest = AsyncMock(return_value=rows)
    coord.data = await coord._async_update_data()


async def test_fresh_probe_logs_no_staleness_warning(hass, monkeypatch, caplog):
    coord = GeoDropsCoordinator(hass, _two_device_entry(), MagicMock())
    await _poll(coord, monkeypatch, {1001: _aged_reading(1001, 2)})
    assert _stale_warnings(caplog) == []


async def test_probe_past_warn_after_is_logged_once(hass, monkeypatch, caplog):
    coord = GeoDropsCoordinator(
        hass, _two_device_entry(), MagicMock()
    )  # warn after 12 h
    await _poll(coord, monkeypatch, {1001: _aged_reading(1001, 13)})
    await _poll(coord, monkeypatch, {1001: _aged_reading(1001, 13.3)})
    (warning,) = _stale_warnings(caplog)
    assert "Front" in warning.getMessage() and "AAA111" in warning.getMessage()


async def test_probe_past_skip_is_also_logged(hass, monkeypatch, caplog):
    coord = GeoDropsCoordinator(hass, _two_device_entry(), MagicMock())
    await _poll(coord, monkeypatch, {1002: _aged_reading(1002, 20)})
    (warning,) = _stale_warnings(caplog)
    assert "Back" in warning.getMessage()


async def test_warn_after_setting_is_honoured(hass, monkeypatch, caplog):
    entry = _two_device_entry()
    entry.options[const.CONF_WARN_HOURS] = 3
    coord = GeoDropsCoordinator(hass, entry, MagicMock())
    await _poll(coord, monkeypatch, {1001: _aged_reading(1001, 4)})
    assert len(_stale_warnings(caplog)) == 1


async def test_recovered_probe_is_logged_and_can_warn_again(
    hass, monkeypatch, caplog, freezer
):
    coord = GeoDropsCoordinator(hass, _two_device_entry(), MagicMock())
    await _poll(coord, monkeypatch, {1001: _aged_reading(1001, 13)})
    caplog.clear()
    fresh = _aged_reading(1001, 0.5)
    await _poll(coord, monkeypatch, {1001: fresh})
    assert any(
        "reporting again" in r.getMessage() and r.levelname == "INFO"
        for r in caplog.records
    )
    freezer.tick(timedelta(hours=14))
    await _poll(coord, monkeypatch, {1001: fresh})
    assert len(_stale_warnings(caplog)) == 1


# --- Offline-probe repairs ---------------------------------------------------


def _offline_entry(*serials, **options):
    entry = MagicMock()
    entry.entry_id = "e1"
    entry.options = {
        const.CONF_DEVICES: [
            {"serial": s, "device_id": 1001 + i, "name": f"Probe {i}"}
            for i, s in enumerate(serials)
        ],
        **options,
    }
    return entry


def _offline_issues(hass):
    return sorted(
        issue_id
        for domain, issue_id in ir.async_get(hass).issues
        if domain == const.DOMAIN
        and issue_id.startswith(("probe_offline_", "data_delayed_"))
    )


async def test_older_reading_does_not_replace_the_held_one(hass, monkeypatch):
    # During a table reload a poll can return an older row; keep the newer one.
    coord = GeoDropsCoordinator(hass, _offline_entry("AAA111"), MagicMock())
    await _poll(coord, monkeypatch, {1001: _aged_reading(1001, 1)})
    held = coord.reading(1001)
    await _poll(coord, monkeypatch, {1001: _aged_reading(1001, 30)})
    assert coord.reading(1001) == held


async def test_probe_offline_past_24_hours_raises_a_repair(hass, monkeypatch, freezer):
    coord = GeoDropsCoordinator(hass, _offline_entry("AAA111", "BBB222"), MagicMock())
    silent = _aged_reading(1001, 23)
    await _poll(coord, monkeypatch, {1001: silent, 1002: _aged_reading(1002, 1)})
    assert _offline_issues(hass) == []
    freezer.tick(timedelta(hours=2))
    await _poll(coord, monkeypatch, {1001: silent, 1002: _aged_reading(1002, 1)})
    assert _offline_issues(hass) == ["probe_offline_e1_AAA111"]
    issue = ir.async_get(hass).async_get_issue(const.DOMAIN, "probe_offline_e1_AAA111")
    assert issue.translation_key == "probe_offline"
    assert issue.translation_placeholders == {
        "name": "Probe 0",
        "serial": "AAA111",
        "hours": "24",
    }
    assert issue.severity is ir.IssueSeverity.WARNING
    assert issue.is_persistent
    assert not issue.is_fixable


async def test_offline_repair_clears_when_the_probe_reports(hass, monkeypatch):
    coord = GeoDropsCoordinator(hass, _offline_entry("AAA111"), MagicMock())
    await _poll(coord, monkeypatch, {1001: _aged_reading(1001, 30)})
    assert _offline_issues(hass) == ["probe_offline_e1_AAA111"]
    await _poll(coord, monkeypatch, {1001: _aged_reading(1001, 1)})
    assert _offline_issues(hass) == []


async def test_offline_alert_setting_is_honoured(hass, monkeypatch):
    entry = _offline_entry("AAA111", **{const.CONF_ALERT_HOURS: 6})
    coord = GeoDropsCoordinator(hass, entry, MagicMock())
    await _poll(coord, monkeypatch, {1001: _aged_reading(1001, 7)})
    assert _offline_issues(hass) == ["probe_offline_e1_AAA111"]
    issue = ir.async_get(hass).async_get_issue(const.DOMAIN, "probe_offline_e1_AAA111")
    assert issue.translation_placeholders["hours"] == "6"


async def test_all_probes_offline_raise_one_data_delayed_repair(
    hass, monkeypatch, freezer
):
    # Every probe silent at once points at GeoDrops' data, not the probes.
    coord = GeoDropsCoordinator(hass, _offline_entry("AAA111", "BBB222"), MagicMock())
    first, second = _aged_reading(1001, 30), _aged_reading(1002, 1)
    await _poll(coord, monkeypatch, {1001: first, 1002: second})
    assert _offline_issues(hass) == ["probe_offline_e1_AAA111"]
    freezer.tick(timedelta(hours=25))
    await _poll(coord, monkeypatch, {})
    assert _offline_issues(hass) == ["data_delayed_e1"]
    issue = ir.async_get(hass).async_get_issue(const.DOMAIN, "data_delayed_e1")
    assert issue.translation_key == "data_delayed"
    assert issue.translation_placeholders == {"hours": "24"}
    assert issue.is_persistent
    await _poll(
        coord,
        monkeypatch,
        {1001: _aged_reading(1001, 30), 1002: _aged_reading(1002, 1)},
    )
    assert _offline_issues(hass) == ["probe_offline_e1_AAA111"]


async def test_probe_with_no_reading_keeps_its_offline_repair(hass, monkeypatch):
    # After a restart a probe silent for longer than the lookback returns no
    # row; its persistent repair must not be cleared for lack of data.
    coord = GeoDropsCoordinator(hass, _offline_entry("AAA111"), MagicMock())
    await _poll(coord, monkeypatch, {1001: _aged_reading(1001, 30)})
    restarted = GeoDropsCoordinator(hass, _offline_entry("AAA111"), MagicMock())
    await _poll(restarted, monkeypatch, {})
    assert _offline_issues(hass) == ["probe_offline_e1_AAA111"]


async def test_data_delayed_repair_survives_a_restart_without_rows(hass, monkeypatch):
    coord = GeoDropsCoordinator(hass, _offline_entry("AAA111", "BBB222"), MagicMock())
    rows = {1001: _aged_reading(1001, 30), 1002: _aged_reading(1002, 30)}
    await _poll(coord, monkeypatch, rows)
    restarted = GeoDropsCoordinator(
        hass, _offline_entry("AAA111", "BBB222"), MagicMock()
    )
    await _poll(restarted, monkeypatch, {1001: _aged_reading(1001, 31)})
    assert _offline_issues(hass) == ["data_delayed_e1"]


async def test_removed_probe_takes_its_offline_repair_with_it(hass, monkeypatch):
    entry = _offline_entry("AAA111", "BBB222")
    coord = GeoDropsCoordinator(hass, entry, MagicMock())
    await _poll(
        coord,
        monkeypatch,
        {1001: _aged_reading(1001, 30), 1002: _aged_reading(1002, 1)},
    )
    entry.options = {const.CONF_DEVICES: entry.options[const.CONF_DEVICES][1:]}
    await _poll(coord, monkeypatch, {1002: _aged_reading(1002, 1)})
    assert _offline_issues(hass) == []


async def test_removing_the_entry_removes_its_offline_repairs(hass, monkeypatch):
    coord = GeoDropsCoordinator(hass, _offline_entry("AAA111", "BBB222"), MagicMock())
    await _poll(
        coord,
        monkeypatch,
        {1001: _aged_reading(1001, 30), 1002: _aged_reading(1002, 30)},
    )
    ir.async_create_issue(
        hass,
        const.DOMAIN,
        "probe_offline_e1_AAA111",
        is_fixable=False,
        severity=ir.IssueSeverity.WARNING,
        translation_key="probe_offline",
    )
    delete_entry_issues(hass, "e1")
    assert _offline_issues(hass) == []
