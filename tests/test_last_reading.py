"""Last Reading keeps showing when a probe last reported, however long ago."""

from datetime import timedelta

from aiogeodrops import DeviceReading
from freezegun.api import FrozenDateTimeFactory
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
    mock_restore_cache_with_extra_data,
)

from custom_components.geodrops import const
from homeassistant.components.sensor import SensorExtraStoredData
from homeassistant.const import STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant, State
from homeassistant.util import dt as dt_util
from tests.common import patch_client

LAST = "sensor.front_last_reading"
MOISTURE = "sensor.front_dominant_moisture"


def _reading(read_at):
    return DeviceReading(
        device_id=1001,
        sync_delay_hours=1.0,
        moisture_index=2,
        moisture_pct=42.0,
        moisture_d1=42.0,
        moisture_d2=42.0,
        moisture_d3=42.0,
        temp_surface=20.0,
        temp_d1=20.0,
        temp_d2=20.0,
        temp_d3=20.0,
        battery_pct=90.0,
        sun_7d=5.0,
        qcn_d1=2,
        qcn_d2=2,
        qcn_d3=2,
        read_at=read_at,
    )


async def _setup(hass: HomeAssistant, data: dict[int, DeviceReading]) -> None:
    entry = MockConfigEntry(
        domain=const.DOMAIN,
        unique_id="p",
        data={const.CONF_PROJECT_ID: "p", const.CONF_CREDENTIALS_JSON: '{"type":"x"}'},
        options={
            const.CONF_DEVICES: [
                {"serial": "AAA111", "device_id": 1001, "name": "Front"}
            ]
        },
    )
    entry.add_to_hass(hass)
    with patch_client("fetch_latest", return_value=data):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()


async def _poll(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    data: dict[int, DeviceReading],
    wait: timedelta = timedelta(minutes=const.DEFAULT_SCAN_INTERVAL),
) -> None:
    with patch_client("fetch_latest", return_value=data):
        freezer.tick(wait)
        async_fire_time_changed(hass)
        await hass.async_block_till_done()


def _restore(hass: HomeAssistant, when) -> None:
    stored = SensorExtraStoredData(when, None).as_dict()
    mock_restore_cache_with_extra_data(hass, [(State(LAST, when.isoformat()), stored)])


def _shown(when) -> str:
    return when.isoformat(timespec="seconds")


async def test_shows_a_reading_too_old_for_the_other_sensors(
    hass: HomeAssistant,
) -> None:
    at = dt_util.utcnow() - timedelta(days=3)
    await _setup(hass, {1001: _reading(at)})
    assert hass.states.get(MOISTURE).state == STATE_UNAVAILABLE
    assert hass.states.get(LAST).state == _shown(at)


async def test_keeps_its_time_once_the_probe_drops_out_of_the_poll(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    at = dt_util.utcnow() - timedelta(minutes=10)
    await _setup(hass, {1001: _reading(at)})
    # The batteries die: GeoDrops stops returning a row for the probe.
    await _poll(hass, freezer, {}, wait=timedelta(days=2))
    assert hass.states.get(MOISTURE).state == STATE_UNAVAILABLE
    assert hass.states.get(LAST).state == _shown(at)


async def test_restores_its_time_after_a_restart(hass: HomeAssistant) -> None:
    # Silent for longer than the lookback, so the first poll has no row.
    at = dt_util.utcnow() - timedelta(days=4)
    _restore(hass, at)
    await _setup(hass, {})
    assert hass.states.get(LAST).state == _shown(at)


async def test_a_new_reading_replaces_the_restored_time(hass: HomeAssistant) -> None:
    _restore(hass, dt_util.utcnow() - timedelta(days=4))
    new = dt_util.utcnow() - timedelta(minutes=10)
    await _setup(hass, {1001: _reading(new)})
    assert hass.states.get(LAST).state == _shown(new)


async def test_an_older_reading_does_not_replace_the_restored_time(
    hass: HomeAssistant,
) -> None:
    held = dt_util.utcnow() - timedelta(hours=1)
    _restore(hass, held)
    await _setup(hass, {1001: _reading(held - timedelta(hours=5))})
    assert hass.states.get(LAST).state == _shown(held)


async def test_a_restored_time_is_never_in_the_future(hass: HomeAssistant) -> None:
    before = dt_util.utcnow().replace(microsecond=0)
    _restore(hass, before + timedelta(minutes=20))
    await _setup(hass, {})
    shown = dt_util.parse_datetime(hass.states.get(LAST).state)
    assert shown is not None
    assert before <= shown <= dt_util.utcnow()


async def test_an_unreadable_stored_time_is_ignored(hass: HomeAssistant) -> None:
    mock_restore_cache_with_extra_data(
        hass,
        [(State(LAST, "x"), {"native_value": "x", "native_unit_of_measurement": None})],
    )
    await _setup(hass, {})
    assert hass.states.get(LAST).state == STATE_UNAVAILABLE


async def test_unavailable_until_the_probe_has_ever_reported(
    hass: HomeAssistant,
) -> None:
    await _setup(hass, {})
    assert hass.states.get(LAST).state == STATE_UNAVAILABLE
