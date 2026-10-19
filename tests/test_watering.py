"""The Last Detected Watering and Watering Confidence sensors."""

from datetime import timedelta

from aiogeodrops import DeviceReading
from freezegun.api import FrozenDateTimeFactory
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
    mock_restore_cache_with_extra_data,
)

from custom_components.geodrops import const
from custom_components.geodrops.sensor import Watering
from homeassistant.core import HomeAssistant, State
from homeassistant.util import dt as dt_util
from tests.common import patch_client

LAST = "sensor.front_last_detected_watering"
CONFIDENCE = "sensor.front_watering_confidence"


def _reading(confidence=None, at=None):
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
        read_at=dt_util.utcnow(),
        last_irrigation_confidence=confidence,
        last_irrigation_at=at,
    )


async def _setup(hass: HomeAssistant, reading: DeviceReading) -> MockConfigEntry:
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
    with patch_client("fetch_latest", return_value={1001: reading}):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    return entry


async def _poll(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, reading: DeviceReading
) -> None:
    with patch_client("fetch_latest", return_value={1001: reading}):
        freezer.tick(timedelta(minutes=const.DEFAULT_SCAN_INTERVAL))
        async_fire_time_changed(hass)
        await hass.async_block_till_done()


async def test_unknown_until_a_watering_is_seen(hass: HomeAssistant) -> None:
    await _setup(hass, _reading())
    assert hass.states.get(LAST).state == "unknown"
    assert hass.states.get(CONFIDENCE).state == "unknown"


async def test_shows_the_last_watering_as_a_timestamp_and_percentage(
    hass: HomeAssistant,
) -> None:
    at = dt_util.utcnow() - timedelta(hours=3)
    await _setup(hass, _reading(0.24, at))
    last = hass.states.get(LAST)
    assert last.state == at.isoformat(timespec="seconds")
    assert last.attributes["device_class"] == "timestamp"
    assert last.attributes["friendly_name"] == "Front Last Detected Watering"
    confidence = hass.states.get(CONFIDENCE)
    assert float(confidence.state) == 24.0
    assert confidence.attributes["unit_of_measurement"] == "%"


async def test_last_watering_is_never_in_the_future(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    # GeoDrops labels a reading with the end of its half-hour slot, so a
    # watering uploaded mid-slot is dated up to 30 minutes ahead.
    now = dt_util.utcnow()
    await _setup(hass, _reading(0.5, now + timedelta(minutes=25)))
    assert hass.states.get(LAST).state == now.isoformat(timespec="seconds")


async def test_holds_the_watering_after_it_leaves_the_window(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    at = dt_util.utcnow() - timedelta(hours=3)
    await _setup(hass, _reading(0.66, at))
    await _poll(hass, freezer, _reading())
    assert hass.states.get(LAST).state == at.isoformat(timespec="seconds")
    assert float(hass.states.get(CONFIDENCE).state) == 66.0


async def test_newer_watering_replaces_and_older_one_is_ignored(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    first = dt_util.utcnow() - timedelta(hours=3)
    await _setup(hass, _reading(0.66, first))
    second = first + timedelta(hours=2)
    await _poll(hass, freezer, _reading(0.24, second))
    assert hass.states.get(LAST).state == second.isoformat(timespec="seconds")
    assert float(hass.states.get(CONFIDENCE).state) == 24.0
    await _poll(hass, freezer, _reading(0.9, first))
    assert hass.states.get(LAST).state == second.isoformat(timespec="seconds")
    assert float(hass.states.get(CONFIDENCE).state) == 24.0


async def test_stays_available_while_the_probe_is_offline(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    at = dt_util.utcnow() - timedelta(hours=3)
    reading = _reading(0.66, at)
    await _setup(hass, reading)
    freezer.tick(timedelta(days=2))  # the probe goes quiet
    await _poll(hass, freezer, reading)
    assert hass.states.get("sensor.front_dominant_moisture").state == "unavailable"
    assert hass.states.get(LAST).state == at.isoformat(timespec="seconds")


async def test_restores_the_last_watering_after_a_restart(hass: HomeAssistant) -> None:
    at = dt_util.utcnow() - timedelta(days=4)
    stored = Watering(0.24, at).as_dict()
    mock_restore_cache_with_extra_data(
        hass,
        [
            (State(LAST, at.isoformat()), stored),
            (State(CONFIDENCE, "24.0"), stored),
        ],
    )
    await _setup(hass, _reading())
    assert hass.states.get(LAST).state == at.isoformat(timespec="seconds")
    assert float(hass.states.get(CONFIDENCE).state) == 24.0


async def test_newer_watering_wins_over_the_restored_one(hass: HomeAssistant) -> None:
    old = dt_util.utcnow() - timedelta(days=4)
    mock_restore_cache_with_extra_data(
        hass, [(State(LAST, old.isoformat()), Watering(0.24, old).as_dict())]
    )
    new = dt_util.utcnow() - timedelta(hours=1)
    await _setup(hass, _reading(0.5, new))
    assert hass.states.get(LAST).state == new.isoformat(timespec="seconds")


async def test_unreadable_stored_watering_is_ignored(hass: HomeAssistant) -> None:
    mock_restore_cache_with_extra_data(
        hass, [(State(LAST, "x"), {"confidence": "x", "detected_at": "y"})]
    )
    await _setup(hass, _reading())
    assert hass.states.get(LAST).state == "unknown"


def test_stored_watering_round_trips() -> None:
    watering = Watering(0.24, dt_util.utcnow())
    assert Watering.from_dict(watering.as_dict()) == watering
    assert Watering.from_dict({}) is None
    assert Watering.from_dict({"confidence": 0.2, "detected_at": "not a date"}) is None
