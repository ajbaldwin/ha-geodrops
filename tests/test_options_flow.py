from aiogeodrops import (
    DeviceReading,
    GeoDropsAuthError,
    GeoDropsConnectionError,
    GeoDropsCredentialsError,
)
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.geodrops import const
from homeassistant.config_entries import ConfigEntryState
from homeassistant.data_entry_flow import FlowResultType, InvalidData
from homeassistant.helpers import device_registry as dr
from tests.common import FakeGeoDropsClient, patch_client, patch_client_init


@pytest.fixture(autouse=True)
async def _unload_reloaded_entries(hass):
    """Saving options reloads the entry; unload it so no coordinator timer lingers."""
    yield
    await hass.async_block_till_done()
    for entry in hass.config_entries.async_entries(const.DOMAIN):
        if entry.state is ConfigEntryState.LOADED:
            await hass.config_entries.async_unload(entry.entry_id)


def _reading(device_id=1002):
    return DeviceReading(
        device_id=device_id,
        sync_delay_hours=1.0,
        moisture_index=2,
        moisture_pct=30.0,
        moisture_d1=30.0,
        moisture_d2=30.0,
        moisture_d3=30.0,
        temp_surface=20.0,
        temp_d1=20.0,
        temp_d2=20.0,
        temp_d3=20.0,
        battery_pct=80.0,
        sun_7d=5.0,
        qcn_d1=2,
        qcn_d2=2,
        qcn_d3=2,
    )


def _entry():
    return MockConfigEntry(
        domain=const.DOMAIN,
        data={const.CONF_PROJECT_ID: "p", const.CONF_CREDENTIALS_JSON: '{"type":"x"}'},
        options={
            const.CONF_DEVICES: [
                {"serial": "AAA111", "device_id": 1001, "name": "Front"}
            ]
        },
    )


async def test_settings_updates_interval(hass):
    entry = _entry()
    entry.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "settings"}
    )
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            const.CONF_SCAN_INTERVAL: 30,
            const.CONF_LOOKBACK_HOURS: 12,
            const.CONF_WARN_HOURS: 6,
            const.CONF_SKIP_HOURS: 12,
            const.CONF_EXPIRE_MINUTES: 45,
        },
    )
    assert entry.options[const.CONF_SCAN_INTERVAL] == 30
    # a form without the offline alert (an older frontend) still saves its default
    assert entry.options[const.CONF_ALERT_HOURS] == const.DEFAULT_ALERT_HOURS == 24
    assert len(entry.options[const.CONF_DEVICES]) == 1  # devices preserved


async def test_add_second_device(hass):
    entry = _entry()
    entry.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "add_device"}
    )
    with patch_client("lookup_serial", return_value=_reading()):
        result = await hass.config_entries.options.async_configure(
            result["flow_id"], {const.DEV_SERIAL: "aaa222", const.DEV_NAME: "Back"}
        )
    serials = [d[const.DEV_SERIAL] for d in entry.options[const.CONF_DEVICES]]
    assert serials == ["AAA111", "AAA222"]


async def test_remove_device(hass, caplog):
    entry = _entry()
    entry.add_to_hass(hass)
    registry = dr.async_get(hass)
    device = registry.async_get_or_create(
        config_entry_id=entry.entry_id, identifiers={(const.DOMAIN, "AAA111")}
    )

    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "remove_device"}
    )
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"device": "AAA111"}
    )
    assert entry.options[const.CONF_DEVICES] == []
    # the device (and its 15 entities) must be purged from the registry, not orphaned
    assert registry.async_get(device.id) is None
    # the device lookup must not use HA's deprecated async_get_device
    assert "deprecated" not in caplog.text


_GOOD_SETTINGS = {
    const.CONF_SCAN_INTERVAL: 20,
    const.CONF_LOOKBACK_HOURS: 12,
    const.CONF_WARN_HOURS: 6,
    const.CONF_SKIP_HOURS: 12,
    const.CONF_EXPIRE_MINUTES: 80,
    const.CONF_ALERT_HOURS: 24,
}


async def _open(hass, step, options=None):
    entry = _entry()
    if options is not None:
        entry = MockConfigEntry(domain=const.DOMAIN, data=entry.data, options=options)
    entry.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": step}
    )
    return entry, result


@pytest.mark.parametrize(
    ("key", "value"),
    [
        (const.CONF_SCAN_INTERVAL, 0),  # would query BigQuery back-to-back
        (const.CONF_SCAN_INTERVAL, 4),
        (const.CONF_LOOKBACK_HOURS, -5),
        (const.CONF_LOOKBACK_HOURS, 0),
        (const.CONF_WARN_HOURS, 0),
        (const.CONF_SKIP_HOURS, 0),
        (const.CONF_EXPIRE_MINUTES, 0),
        (const.CONF_ALERT_HOURS, 0),
        (const.CONF_ALERT_HOURS, 169),
    ],
)
async def test_settings_reject_out_of_range_values(hass, key, value):
    entry, result = await _open(hass, "settings")
    with pytest.raises(InvalidData):
        await hass.config_entries.options.async_configure(
            result["flow_id"], {**_GOOD_SETTINGS, key: value}
        )
    assert key not in entry.options


async def _assert_settings_recover(hass, entry, result):
    """After a rejected save, valid settings are accepted and stored."""
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], _GOOD_SETTINGS
    )
    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert {k: entry.options[k] for k in _GOOD_SETTINGS} == _GOOD_SETTINGS


async def _assert_add_device_recovers(hass, entry, result):
    """After an add-probe error, a known serial is still added."""
    with patch_client("lookup_serial", return_value=_reading()):
        result = await hass.config_entries.options.async_configure(
            result["flow_id"], {const.DEV_SERIAL: "CCC333", const.DEV_NAME: "Side"}
        )
    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert [d[const.DEV_SERIAL] for d in entry.options[const.CONF_DEVICES]] == [
        "AAA111",
        "CCC333",
    ]


async def test_settings_reject_warn_above_skip(hass):
    entry, result = await _open(hass, "settings")
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {**_GOOD_SETTINGS, const.CONF_WARN_HOURS: 13}
    )
    assert result["errors"] == {const.CONF_WARN_HOURS: "warn_above_skip"}
    assert const.CONF_WARN_HOURS not in entry.options
    await _assert_settings_recover(hass, entry, result)


async def test_settings_reject_expire_not_longer_than_poll(hass):
    # sensors would go unavailable between every pair of polls
    entry, result = await _open(hass, "settings")
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {**_GOOD_SETTINGS, const.CONF_SCAN_INTERVAL: 30, const.CONF_EXPIRE_MINUTES: 30},
    )
    assert result["errors"] == {const.CONF_EXPIRE_MINUTES: "expire_below_interval"}
    assert const.CONF_EXPIRE_MINUTES not in entry.options
    await _assert_settings_recover(hass, entry, result)


async def test_settings_rejected_form_keeps_what_was_typed(hass):
    _, result = await _open(hass, "settings")
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {**_GOOD_SETTINGS, const.CONF_WARN_HOURS: 13}
    )
    defaults = {str(k): k.default() for k in result["data_schema"].schema}
    assert defaults[const.CONF_WARN_HOURS] == 13


async def test_add_duplicate_serial_is_rejected_without_a_query(hass):
    entry, result = await _open(hass, "add_device")
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {const.DEV_SERIAL: " aaa111", const.DEV_NAME: "Again"}
    )
    assert result["errors"] == {"base": "duplicate_device"}
    assert FakeGeoDropsClient.created == []
    await _assert_add_device_recovers(hass, entry, result)


@pytest.mark.parametrize(
    ("exc", "error"),
    [
        (GeoDropsConnectionError("503"), "cannot_connect"),
        (GeoDropsAuthError("invalid_grant"), "invalid_auth"),
        (RuntimeError("bug"), "unknown"),
    ],
)
async def test_add_device_errors(hass, exc, error):
    entry, result = await _open(hass, "add_device")
    with patch_client("lookup_serial", side_effect=exc):
        result = await hass.config_entries.options.async_configure(
            result["flow_id"], {const.DEV_SERIAL: "BBB222", const.DEV_NAME: "Back"}
        )
    assert result["step_id"] == "add_device"
    assert result["errors"] == {"base": error}
    assert len(entry.options[const.CONF_DEVICES]) == 1
    await _assert_add_device_recovers(hass, entry, result)


async def test_add_unknown_serial(hass):
    entry, result = await _open(hass, "add_device")
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {const.DEV_SERIAL: "BBB222", const.DEV_NAME: "Back"}
    )
    assert result["errors"] == {"base": "device_not_found"}
    await _assert_add_device_recovers(hass, entry, result)


async def test_add_device_with_unparseable_stored_key(hass):
    _entry, result = await _open(hass, "add_device")
    with patch_client_init(GeoDropsCredentialsError("bad")):
        result = await hass.config_entries.options.async_configure(
            result["flow_id"], {const.DEV_SERIAL: "BBB222", const.DEV_NAME: "Back"}
        )
    assert result["errors"] == {"base": "invalid_credentials"}


async def test_add_device_saves_id_and_area(hass):
    entry, result = await _open(hass, "add_device")
    with patch_client("lookup_serial", return_value=_reading()) as lookup:
        await hass.config_entries.options.async_configure(
            result["flow_id"],
            {
                const.DEV_SERIAL: "BBB222",
                const.DEV_NAME: "Back",
                const.DEV_AREA: "garden",
            },
        )
    lookup.assert_awaited_once_with("BBB222", const.DEFAULT_LOOKBACK_HOURS)
    assert FakeGeoDropsClient.created[0] == ("p", '{"type":"x"}')  # the stored key
    assert entry.options[const.CONF_DEVICES][1] == {
        "serial": "BBB222",
        "device_id": 1002,
        "name": "Back",
        "area_id": "garden",
    }


async def test_add_device_searches_the_configured_lookback(hass):
    options = {**_entry().options, const.CONF_LOOKBACK_HOURS: 72}
    _, result = await _open(hass, "add_device", options=options)
    with patch_client("lookup_serial", return_value=_reading()) as lookup:
        await hass.config_entries.options.async_configure(
            result["flow_id"], {const.DEV_SERIAL: "BBB222", const.DEV_NAME: "Back"}
        )
    lookup.assert_awaited_once_with("BBB222", 72)


async def test_remove_with_no_probes_aborts(hass):
    _, result = await _open(hass, "remove_device", options={const.CONF_DEVICES: []})
    assert result["type"] == FlowResultType.ABORT
    assert result["reason"] == "no_devices"
