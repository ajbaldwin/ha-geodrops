from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock

from aiogeodrops import BatteryPoint, DeviceReading, GeoDropsQueryError

from custom_components.geodrops import const
from custom_components.geodrops.battery import HISTORY_DAYS
from custom_components.geodrops.coordinator import (
    GeoDropsCoordinator,
    battery_issue_id,
    delete_entry_issues,
)
from homeassistant.helpers import issue_registry as ir
from homeassistant.util import dt as dt_util


def _entry(*devices):
    entry = MagicMock()
    entry.entry_id = "e1"
    entry.data = {const.CONF_PROJECT_ID: "p", const.CONF_CREDENTIALS_JSON: "{}"}
    entry.options = {
        const.CONF_DEVICES: list(devices)
        or [{"serial": "AAA111", "device_id": 1001, "name": "Front"}]
    }
    return entry


def _reading(device_id=1001, battery_mv=5300.0, hours_old=1.0):
    return DeviceReading(
        device_id=device_id,
        sync_delay_hours=1.0,
        moisture_index=2,
        moisture_pct=40.0,
        moisture_d1=40.0,
        moisture_d2=40.0,
        moisture_d3=40.0,
        temp_surface=20.0,
        temp_d1=20.0,
        temp_d2=20.0,
        temp_d3=20.0,
        battery_pct=50.0,
        sun_7d=5.0,
        qcn_d1=2,
        qcn_d2=2,
        qcn_d3=2,
        read_at=dt_util.utcnow() - timedelta(hours=hours_old),
        battery_mv=battery_mv,
    )


def _history(daily_mv, end=None):
    """One reading a day, the last on `end` (default today)."""
    end = end or dt_util.utcnow()
    return [
        BatteryPoint(end - timedelta(days=len(daily_mv) - 1 - d), mv)
        for d, mv in enumerate(daily_mv)
    ]


HEALTHY = [5400 - 4 * d for d in range(14)]
COLLAPSED = [5300 - 4 * d for d in range(11)] + [5000, 4700, 4500]


def _coordinator(hass, entry=None, history=None, fetch_error=None):
    client = MagicMock()
    client.fetch_latest = AsyncMock(return_value={1001: _reading()})
    client.fetch_battery_history = AsyncMock(
        return_value={1001: _history(HEALTHY)} if history is None else history,
        side_effect=fetch_error,
    )
    return GeoDropsCoordinator(hass, entry or _entry(), client)


async def _poll(coord, readings=None):
    if readings is not None:
        coord.client.fetch_latest = AsyncMock(return_value=readings)
    coord.data = await coord._async_update_data()


def _battery_issues(hass):
    return sorted(
        issue_id
        for domain, issue_id in ir.async_get(hass).issues
        if domain == const.DOMAIN and issue_id.startswith("battery_replace_")
    )


async def test_first_poll_fetches_the_battery_history(hass):
    coord = _coordinator(hass)
    await _poll(coord)
    coord.client.fetch_battery_history.assert_awaited_once_with([1001], HISTORY_DAYS)
    assert coord.battery_outlook(1001) == "ok"
    assert coord.battery_trend(1001).slope is not None


async def test_battery_history_is_fetched_twice_a_day(hass, freezer):
    coord = _coordinator(hass)
    await _poll(coord)
    freezer.tick(timedelta(hours=11, minutes=59))
    await _poll(coord)
    assert coord.client.fetch_battery_history.await_count == 1
    freezer.tick(timedelta(minutes=1))
    await _poll(coord)
    assert coord.client.fetch_battery_history.await_count == 2


async def test_failed_battery_fetch_keeps_the_poll_and_retries_in_an_hour(
    hass, freezer
):
    coord = _coordinator(hass, fetch_error=GeoDropsQueryError("boom"))
    await _poll(coord)
    assert coord.reading(1001) is not None
    assert coord.battery_outlook(1001) is None
    freezer.tick(timedelta(minutes=59))
    await _poll(coord)
    assert coord.client.fetch_battery_history.await_count == 1
    coord.client.fetch_battery_history.side_effect = None
    freezer.tick(timedelta(minutes=1))
    await _poll(coord)
    assert coord.client.fetch_battery_history.await_count == 2
    assert coord.battery_outlook(1001) == "ok"


async def test_failed_battery_fetch_keeps_the_last_trend(hass, freezer):
    coord = _coordinator(hass, history={1001: _history(COLLAPSED)})
    await _poll(coord)
    coord.client.fetch_battery_history.side_effect = GeoDropsQueryError("boom")
    freezer.tick(timedelta(hours=12))
    await _poll(coord)
    assert coord.battery_outlook(1001) == "now"


async def test_older_battery_history_does_not_replace_the_held_one(hass, freezer):
    # During a table reload GeoDrops can serve only older rows.
    coord = _coordinator(hass, history={1001: _history(COLLAPSED)})
    await _poll(coord)
    stale_end = dt_util.utcnow() - timedelta(days=3)
    coord.client.fetch_battery_history.return_value = {
        1001: _history(HEALTHY, end=stale_end)
    }
    freezer.tick(timedelta(hours=12))
    await _poll(coord)
    assert coord.battery_outlook(1001) == "now"


async def test_two_readings_below_the_floor_are_replace_now(hass):
    coord = _coordinator(hass, history={})
    await _poll(coord, {1001: _reading(battery_mv=4390.0, hours_old=2)})
    assert coord.battery_outlook(1001) is None
    await _poll(coord, {1001: _reading(battery_mv=4380.0, hours_old=1)})
    assert coord.battery_trend(1001).outlook is None
    assert coord.battery_outlook(1001) == "now"


async def test_one_low_reading_is_not_enough(hass):
    # GeoDrops occasionally serves a single bad row.
    coord = _coordinator(hass)
    await _poll(coord, {1001: _reading(battery_mv=5300.0, hours_old=2)})
    bad_row = _reading(battery_mv=3500.0, hours_old=1)
    await _poll(coord, {1001: bad_row})
    assert coord.battery_outlook(1001) == "ok"
    assert _battery_issues(hass) == []
    # The same row seen again by the next poll is still one reading.
    await _poll(coord, {1001: bad_row})
    assert coord.battery_outlook(1001) == "ok"


async def test_malformed_battery_history_keeps_the_poll(hass):
    coord = _coordinator(hass, fetch_error=ValueError("could not convert 'x'"))
    await _poll(coord)
    assert coord.reading(1001) is not None
    assert coord.battery_outlook(1001) is None


async def test_a_newly_polled_probe_gets_its_history_at_the_next_poll(hass):
    front = {"serial": "AAA111", "device_id": 1001, "name": "Front"}
    back = {"serial": "BBB222", "device_id": 1002, "name": "Back"}
    coord = _coordinator(hass, _entry(front))
    await _poll(coord)
    coord.config_entry.options = {const.CONF_DEVICES: [front, back]}
    await _poll(coord, {1001: _reading(), 1002: _reading(1002)})
    assert coord.client.fetch_battery_history.await_count == 2
    coord.client.fetch_battery_history.assert_awaited_with([1001, 1002], HISTORY_DAYS)


async def test_replace_now_raises_a_repair_until_it_clears(hass, freezer):
    coord = _coordinator(hass, history={1001: _history(COLLAPSED)})
    await _poll(coord)
    assert _battery_issues(hass) == ["battery_replace_e1_AAA111"]
    issue = ir.async_get(hass).async_get_issue(
        const.DOMAIN, battery_issue_id("e1", "AAA111")
    )
    assert issue.translation_key == "battery_replace"
    assert issue.translation_placeholders == {"name": "Front", "serial": "AAA111"}
    assert issue.severity is ir.IssueSeverity.ERROR
    assert not issue.is_fixable

    fresh = [*COLLAPSED, 5700, 5700, 5700]
    coord.client.fetch_battery_history.return_value = {1001: _history(fresh)}
    freezer.tick(timedelta(hours=12))
    await _poll(coord)
    assert _battery_issues(hass) == []


async def test_replace_soon_raises_no_repair(hass):
    soon = [5300 - 4 * d for d in range(7)] + [5260 - 15 * d for d in range(7)]
    coord = _coordinator(hass, history={1001: _history(soon)})
    await _poll(coord)
    assert coord.battery_outlook(1001) == "soon"
    assert _battery_issues(hass) == []


async def test_unknown_outlook_keeps_the_repair(hass):
    await _poll(_coordinator(hass, history={1001: _history(COLLAPSED)}))
    # After a restart the history may fail to load: the repair stays.
    restarted = _coordinator(hass, fetch_error=GeoDropsQueryError("boom"))
    await _poll(restarted)
    assert restarted.battery_outlook(1001) is None
    assert _battery_issues(hass) == ["battery_replace_e1_AAA111"]


async def test_inactive_probe_raises_no_battery_repair(hass):
    entry = _entry(
        {"serial": "AAA111", "device_id": 1001, "name": "Front", "active": False}
    )
    coord = _coordinator(hass, entry, history={1001: _history(COLLAPSED)})
    await _poll(coord)
    assert _battery_issues(hass) == []


async def test_removed_probe_takes_its_battery_repair_with_it(hass):
    coord = _coordinator(hass, history={1001: _history(COLLAPSED)})
    await _poll(coord)
    coord.config_entry.options = {const.CONF_DEVICES: []}
    await _poll(coord)
    assert _battery_issues(hass) == []


async def test_removing_the_entry_removes_its_battery_repairs(hass):
    coord = _coordinator(hass, history={1001: _history(COLLAPSED)})
    await _poll(coord)
    delete_entry_issues(hass, "e1")
    assert _battery_issues(hass) == []
