"""Taking probes out of service: the Active switch and disabled devices."""

from dataclasses import replace
from datetime import timedelta

from aiogeodrops import DeviceReading
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.geodrops import const
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import STATE_UNAVAILABLE, EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers import (
    device_registry as dr,
    entity_registry as er,
    issue_registry as ir,
)
from homeassistant.util import dt as dt_util
from tests.common import FakeGeoDropsClient, patch_client

SWITCH = "switch.front_active"


def _reading(device_id=1001, hours_old=0.5, **changes):
    reading = DeviceReading(
        device_id=device_id,
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
        read_at=dt_util.utcnow() - timedelta(hours=hours_old),
        last_irrigation_confidence=0.9,
        last_irrigation_at=dt_util.utcnow() - timedelta(hours=2),
        next_action=frozenset({"DW_M_LOW1"}),
    )
    return replace(reading, **changes)


def _max_moisture(device_id=1001):
    return _reading(device_id, next_action=frozenset({"ATT_DW_NEW"}))


def _entry(hass: HomeAssistant, *devices) -> MockConfigEntry:
    devices = devices or ({"serial": "AAA111", "device_id": 1001, "name": "Front"},)
    entry = MockConfigEntry(
        domain=const.DOMAIN,
        unique_id="p",
        data={const.CONF_PROJECT_ID: "p", const.CONF_CREDENTIALS_JSON: '{"type":"x"}'},
        options={const.CONF_DEVICES: [dict(d) for d in devices]},
    )
    entry.add_to_hass(hass)
    return entry


def _two_probes(hass):
    return _entry(
        hass,
        {"serial": "AAA111", "device_id": 1001, "name": "Front"},
        {"serial": "BBB222", "device_id": 1002, "name": "Back"},
    )


async def _setup(hass, entry, readings):
    with patch_client("fetch_latest", return_value=readings):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()


async def _poll(hass, entry, readings):
    with patch_client("fetch_latest", return_value=readings) as fetch:
        await entry.runtime_data.async_refresh()
        await hass.async_block_till_done()
    return fetch


async def _switch(hass, service):
    await hass.services.async_call(
        "switch", service, {"entity_id": SWITCH}, blocking=True
    )
    await hass.async_block_till_done()


def _issues(hass):
    return sorted(
        issue_id
        for domain, issue_id in ir.async_get(hass).issues
        if domain == const.DOMAIN
    )


def _state(hass, entity_id):
    return hass.states.get(entity_id).state


# --- The switch ----------------------------------------------------------------


async def test_each_probe_has_an_active_switch_that_starts_on(hass):
    entry = _entry(hass)
    await _setup(hass, entry, {1001: _reading()})
    state = hass.states.get(SWITCH)
    assert state.state == "on"
    assert state.attributes["friendly_name"] == "Front Active"
    entity = er.async_get(hass).async_get(SWITCH)
    assert entity.unique_id == "AAA111_active"
    assert entity.entity_category is EntityCategory.CONFIG
    assert entity.disabled_by is None


async def test_turning_the_switch_off_is_stored_without_a_reload(hass):
    entry = _entry(hass)
    await _setup(hass, entry, {1001: _reading()})
    await _switch(hass, "turn_off")
    assert _state(hass, SWITCH) == "off"
    assert entry.options[const.CONF_DEVICES][0][const.DEV_ACTIVE] is False
    assert entry.state is ConfigEntryState.LOADED
    assert len(FakeGeoDropsClient.created) == 1  # not reloaded


async def test_inactive_survives_a_reload(hass):
    entry = _entry(hass)
    await _setup(hass, entry, {1001: _reading()})
    await _switch(hass, "turn_off")
    with patch_client("fetch_latest", return_value={1001: _reading()}):
        assert await hass.config_entries.async_reload(entry.entry_id)
        await hass.async_block_till_done()
    assert _state(hass, SWITCH) == "off"
    assert _state(hass, "sensor.front_dominant_moisture") == STATE_UNAVAILABLE


async def test_switch_stays_available_when_the_probe_has_no_data(hass):
    entry = _entry(hass)
    await _setup(hass, entry, {})
    assert _state(hass, "sensor.front_dominant_moisture") == STATE_UNAVAILABLE
    assert _state(hass, SWITCH) == "on"


async def test_turning_the_switch_back_on_restores_the_probe(hass):
    entry = _entry(hass)
    await _setup(hass, entry, {1001: _reading()})
    await _switch(hass, "turn_off")
    await _switch(hass, "turn_on")
    assert _state(hass, SWITCH) == "on"
    assert entry.options[const.CONF_DEVICES][0].get(const.DEV_ACTIVE, True) is True
    assert _state(hass, "sensor.front_dominant_moisture") == "42.0"


# --- What an inactive probe shows ------------------------------------------------


async def test_inactive_probe_shows_only_its_last_reading(hass):
    entry = _entry(hass)
    await _setup(hass, entry, {1001: _reading()})
    await _switch(hass, "turn_off")
    for entity_id in (
        "sensor.front_dominant_moisture",
        "sensor.front_battery",
        "sensor.front_probe_health",
        "binary_sensor.front_max_moisture_calibration",
        # These two otherwise stay available while a probe is offline.
        "sensor.front_last_detected_watering",
        "sensor.front_watering_confidence",
    ):
        assert _state(hass, entity_id) == STATE_UNAVAILABLE, entity_id
    # Last Reading keeps updating, so a probe back in the ground shows up.
    assert _state(hass, "sensor.front_last_reading") not in (
        STATE_UNAVAILABLE,
        "unknown",
    )


async def test_inactive_probe_is_still_polled(hass):
    entry = _entry(hass)
    await _setup(hass, entry, {1001: _reading()})
    await _switch(hass, "turn_off")
    fetch = await _poll(hass, entry, {1001: _reading(hours_old=0.1)})
    fetch.assert_awaited_once_with([1001], const.DEFAULT_LOOKBACK_HOURS)


# --- Repairs ---------------------------------------------------------------------


async def test_turning_a_probe_inactive_clears_its_repairs_at_once(hass):
    entry = _entry(hass)
    await _setup(hass, entry, {1001: _max_moisture()})
    assert _issues(hass) == [f"max_moisture_required_{entry.entry_id}_AAA111"]
    await _switch(hass, "turn_off")
    assert _issues(hass) == []
    await _poll(hass, entry, {1001: _max_moisture()})
    assert _issues(hass) == []


async def test_turning_a_probe_back_on_brings_its_repairs_back(hass):
    entry = _entry(hass)
    await _setup(hass, entry, {1001: _max_moisture()})
    await _switch(hass, "turn_off")
    await _switch(hass, "turn_on")
    assert _issues(hass) == [f"max_moisture_required_{entry.entry_id}_AAA111"]


async def test_inactive_probe_raises_no_offline_repair(hass):
    entry = _entry(hass)
    await _setup(hass, entry, {1001: _reading(hours_old=30)})
    assert _issues(hass) == [f"probe_offline_{entry.entry_id}_AAA111"]
    await _switch(hass, "turn_off")
    assert _issues(hass) == []
    await _poll(hass, entry, {1001: _reading(hours_old=31)})
    assert _issues(hass) == []


async def test_every_probe_inactive_and_silent_raises_nothing(hass):
    # The winter case: every probe pulled from the ground.
    entry = _two_probes(hass)
    for device in entry.options[const.CONF_DEVICES]:
        device[const.DEV_ACTIVE] = False
    await _setup(hass, entry, {1001: _reading(1001, 30), 1002: _reading(1002, 30)})
    assert _issues(hass) == []


async def test_inactive_probe_reporting_counts_as_data_arriving(hass):
    # A reporting probe shows GeoDrops' data is flowing, even if it is inactive,
    # so the silent active probes get their own repairs, not "data delayed".
    entry = _entry(
        hass,
        {"serial": "AAA111", "device_id": 1001, "name": "Front"},
        {"serial": "BBB222", "device_id": 1002, "name": "Back"},
        {"serial": "CCC333", "device_id": 1003, "name": "Side", "active": False},
    )
    await _setup(
        hass,
        entry,
        {1001: _reading(1001, 30), 1002: _reading(1002, 30), 1003: _reading(1003)},
    )
    eid = entry.entry_id
    assert _issues(hass) == [
        f"probe_offline_{eid}_AAA111",
        f"probe_offline_{eid}_BBB222",
    ]


async def test_data_delayed_needs_two_active_probes(hass):
    entry = _entry(
        hass,
        {"serial": "AAA111", "device_id": 1001, "name": "Front"},
        {"serial": "BBB222", "device_id": 1002, "name": "Back", "active": False},
    )
    await _setup(hass, entry, {1001: _reading(1001, 30), 1002: _reading(1002, 30)})
    assert _issues(hass) == [f"probe_offline_{entry.entry_id}_AAA111"]


async def test_inactive_probe_logs_no_staleness_warning(hass, caplog):
    entry = _entry(
        hass, {"serial": "AAA111", "device_id": 1001, "name": "Front", "active": False}
    )
    await _setup(hass, entry, {1001: _reading(hours_old=13)})
    assert not any("has not reported" in r.getMessage() for r in caplog.records)


async def test_reactivated_stale_probe_warns_again(hass, caplog):
    entry = _entry(hass)
    await _setup(hass, entry, {1001: _reading(hours_old=13)})
    await _switch(hass, "turn_off")
    await _poll(hass, entry, {1001: _reading(hours_old=14)})
    caplog.clear()
    await _switch(hass, "turn_on")
    await _poll(hass, entry, {1001: _reading(hours_old=14)})
    assert any("has not reported" in r.getMessage() for r in caplog.records)
    assert not any("reporting again" in r.getMessage() for r in caplog.records)


# --- Disabled devices ------------------------------------------------------------


def _disable(hass, entry, serial):
    registry = dr.async_get(hass)
    (device,) = [
        d
        for d in dr.async_entries_for_config_entry(registry, entry.entry_id)
        if (const.DOMAIN, serial) in d.identifiers
    ]
    registry.async_update_device(device.id, disabled_by=dr.DeviceEntryDisabler.USER)


async def test_disabled_probe_is_not_polled_and_drops_its_repairs(hass):
    entry = _two_probes(hass)
    await _setup(hass, entry, {1001: _reading(1001, 30), 1002: _reading(1002)})
    assert _issues(hass) == [f"probe_offline_{entry.entry_id}_AAA111"]
    _disable(hass, entry, "AAA111")
    await hass.async_block_till_done()
    assert _issues(hass) == []  # at once, not at the next poll
    fetch = await _poll(hass, entry, {1002: _reading(1002)})
    fetch.assert_awaited_once_with([1002], const.DEFAULT_LOOKBACK_HOURS)
    assert entry.runtime_data.device_ids == [1002]
    assert _issues(hass) == []


async def test_disabled_probe_does_not_count_toward_data_delayed(hass):
    entry = _two_probes(hass)
    await _setup(hass, entry, {1001: _reading(1001, 30), 1002: _reading(1002, 30)})
    assert _issues(hass) == [f"data_delayed_{entry.entry_id}"]
    _disable(hass, entry, "AAA111")
    await hass.async_block_till_done()
    await _poll(hass, entry, {1002: _reading(1002, 30)})
    assert _issues(hass) == [f"probe_offline_{entry.entry_id}_BBB222"]
