from dataclasses import replace
from datetime import timedelta
import json

from aiogeodrops import (
    BatteryPoint,
    DeviceReading,
    GeoDropsAccessDeniedError,
    GeoDropsAuthError,
    GeoDropsCredentialsError,
    GeoDropsQueryError,
)
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.geodrops import (
    async_remove_config_entry_device,
    async_setup_entry,
    const,
)
from homeassistant.config_entries import SOURCE_REAUTH, ConfigEntryState
from homeassistant.const import EntityCategory
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers import (
    device_registry as dr,
    entity_registry as er,
    issue_registry as ir,
)
from homeassistant.util import dt as dt_util
from tests.common import FakeGeoDropsClient, patch_client, patch_client_init


def _reading(device_id=1001):
    return DeviceReading(
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
        battery_mv=5300.0,
        rssi_dbm=-97.0,
        battery_poor=False,
        qcn=2,
        next_action=frozenset({"DW_M_LOW1"}),
    )


def _entry(hass):
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
    return entry


def _patch_client(side_effect=None):
    """`side_effect` makes creating the client fail (an unusable stored key)."""
    return patch_client_init(side_effect)


def _patch_fetch(**kw):
    kw.setdefault("return_value", {1001: _reading()})
    return patch_client("fetch_latest", **kw)


def _reauth_flows(hass):
    return [
        f
        for f in hass.config_entries.flow.async_progress_by_handler(const.DOMAIN)
        if f["context"]["source"] == SOURCE_REAUTH
    ]


async def test_setup_creates_28_entities_then_unloads(hass):
    entry = _entry(hass)
    with _patch_client(), _patch_fetch() as fetch:
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED
    assert FakeGeoDropsClient.created == [("p", '{"type":"x"}')]
    fetch.assert_awaited_once_with([1001], const.DEFAULT_LOOKBACK_HOURS)
    entities = er.async_entries_for_config_entry(er.async_get(hass), entry.entry_id)
    assert len(entities) == 28
    assert hass.states.get("sensor.front_dominant_moisture").state == "42.0"

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.NOT_LOADED


@pytest.mark.usefixtures("entity_registry_enabled_by_default")
async def test_entity_ids_names_and_states(hass):
    # translated names must produce the same entity ids as the old hard-coded ones
    # (except renamed sensors such as Battery Status, Reading Quality and Probe
    # Health; existing entities keep their ids)
    entry = _entry(hass)
    with _patch_client(), _patch_fetch():
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    entity_ids = {
        e.entity_id
        for e in er.async_entries_for_config_entry(er.async_get(hass), entry.entry_id)
    }
    assert entity_ids == {
        f"binary_sensor.front_{s}"
        for s in (
            "battery_status",
            "max_moisture_calibration",
            "max_moisture_recalibration",
            "hardware_status",
        )
    } | {
        f"sensor.front_{s}"
        for s in (
            "dominant_moisture",
            "moisture_state",
            "moisture_depth_1",
            "moisture_depth_2",
            "moisture_depth_3",
            "reading_quality_depth_1",
            "reading_quality_depth_2",
            "reading_quality_depth_3",
            "reading_quality",
            "probe_health",
            "next_action_codes",
            "battery",
            "battery_voltage",
            "signal_strength",
            "cloud_upload_delay",
            "surface_temperature",
            "temperature_depth_1",
            "temperature_depth_2",
            "temperature_depth_3",
            "avg_7_day_sun",
            "last_reading",
            "last_detected_watering",
            "watering_confidence",
        )
    } | {"switch.front_active"}
    quality = hass.states.get("sensor.front_reading_quality_depth_2")
    assert quality.attributes["friendly_name"] == "Front Reading Quality Depth 2"
    assert quality.state == "good"
    assert quality.attributes["options"] == ["bad", "poor", "good", "training"]
    assert hass.states.get("sensor.front_moisture_state").state == "moist"
    assert (
        hass.states.get("sensor.front_avg_7_day_sun").attributes["friendly_name"]
        == "Front Avg. 7-Day Sun"
    )
    assert hass.states.get("sensor.front_probe_health").state == "ok"
    assert hass.states.get("sensor.front_next_action_codes").state == "DW_M_LOW1"
    assert hass.states.get("sensor.front_reading_quality").state == "good"
    battery = hass.states.get("binary_sensor.front_battery_status")
    assert battery.attributes["friendly_name"] == "Front Battery Status"
    # No battery history yet, and the latest voltage is above the floor.
    assert battery.state == "unknown"


async def test_options_change_reloads_entry_once(hass):
    entry = _entry(hass)
    with _patch_client(), _patch_fetch():
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        assert len(FakeGeoDropsClient.created) == 1
        result = await hass.config_entries.options.async_init(entry.entry_id)
        result = await hass.config_entries.options.async_configure(
            result["flow_id"], {"next_step_id": "settings"}
        )
        await hass.config_entries.options.async_configure(
            result["flow_id"],
            {
                const.CONF_SCAN_INTERVAL: 30,
                const.CONF_LOOKBACK_HOURS: 12,
                const.CONF_WARN_HOURS: 6,
                const.CONF_SKIP_HOURS: 12,
                const.CONF_EXPIRE_MINUTES: 80,
            },
        )
        await hass.async_block_till_done()
    assert len(FakeGeoDropsClient.created) == 2  # reloaded exactly once
    assert entry.state is ConfigEntryState.LOADED
    assert entry.runtime_data.update_interval.total_seconds() == 30 * 60


async def test_reauth_reloads_entry_once(hass):
    # the update listener used to reload on the key change too: two reloads,
    # two BigQuery queries
    entry = _entry(hass)
    with _patch_client(), _patch_fetch() as fetch:
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        result = await entry.start_reauth_flow(hass)
        await hass.config_entries.flow.async_configure(
            result["flow_id"], {const.CONF_CREDENTIALS_JSON: '{"type":"new"}'}
        )
        await hass.async_block_till_done()
    # setup, the reauth form's key check, then the one reload
    assert [c[1] for c in FakeGeoDropsClient.created] == [
        '{"type":"x"}',
        '{"type":"new"}',
        '{"type":"new"}',
    ]
    assert fetch.await_count == 2
    assert entry.state is ConfigEntryState.LOADED


async def test_unparseable_stored_key_starts_reauth(hass):
    entry = _entry(hass)
    with _patch_client(side_effect=GeoDropsCredentialsError("bad json")):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.SETUP_ERROR
    assert len(_reauth_flows(hass)) == 1


async def test_rejected_key_on_first_refresh_starts_reauth(hass):
    entry = _entry(hass)
    with _patch_client(), _patch_fetch(side_effect=GeoDropsAuthError("invalid_grant")):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.SETUP_ERROR
    assert len(_reauth_flows(hass)) == 1


async def test_query_error_on_first_refresh_retries_without_reauth(hass):
    entry = _entry(hass)
    with (
        _patch_client(),
        _patch_fetch(side_effect=GeoDropsQueryError("403 access denied")),
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.SETUP_RETRY
    assert _reauth_flows(hass) == []


async def test_key_rejected_after_setup_starts_reauth(hass):
    entry = _entry(hass)
    with _patch_client(), _patch_fetch():
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    coordinator = entry.runtime_data
    with _patch_fetch(side_effect=GeoDropsAuthError("invalid_grant")):
        await coordinator.async_refresh()
        await hass.async_block_till_done()
    assert not coordinator.last_update_success
    assert len(_reauth_flows(hass)) == 1


async def test_diagnostic_and_disabled_sensors(hass):
    entry = _entry(hass)
    with _patch_client(), _patch_fetch():
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    registry = er.async_get(hass)
    entries = {
        e.unique_id.removeprefix("AAA111_"): e
        for e in er.async_entries_for_config_entry(registry, entry.entry_id)
    }
    diagnostic = {
        k for k, e in entries.items() if e.entity_category is EntityCategory.DIAGNOSTIC
    }
    assert diagnostic == {
        "battery",
        "battery_poor",
        "battery_voltage",
        "signal_strength",
        "sync_delay",
        "last_reading",
        "qcn_d1",
        "qcn_d2",
        "qcn_d3",
        "qcn",
        "status",
        "next_action",
        "max_moisture_required",
        "wick_renewal",
        "hardware_problem",
        "watering_confidence",
    }
    disabled = {
        k
        for k, e in entries.items()
        if e.disabled_by is er.RegistryEntryDisabler.INTEGRATION
    }
    assert disabled == {
        "sync_delay",
        "sun_7d",
        "battery_voltage",
        "signal_strength",
        "next_action",
        "wick_renewal",
        "hardware_problem",
    }
    assert hass.states.get("sensor.front_cloud_upload_delay") is None
    assert hass.states.get("binary_sensor.front_max_moisture_recalibration") is None
    assert hass.states.get("sensor.front_avg_7_day_sun") is None
    assert (
        hass.states.get("binary_sensor.front_max_moisture_calibration").state == "off"
    )
    # other integrations read the quality states, so they must exist
    assert hass.states.get("sensor.front_reading_quality_depth_1").state == "good"
    assert hass.states.get("sensor.front_dominant_moisture").state == "42.0"


async def test_battery_status_and_repair_from_the_battery_trend(hass):
    entry = _entry(hass)
    now = dt_util.utcnow()
    collapsed = [5300 - 4 * d for d in range(11)] + [5000, 4700, 4500]
    history = {
        1001: [
            BatteryPoint(now - timedelta(days=13 - d), mv)
            for d, mv in enumerate(collapsed)
        ]
    }
    with (
        _patch_client(),
        _patch_fetch(),
        patch_client("fetch_battery_history", return_value=history),
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    state = hass.states.get("binary_sensor.front_battery_status")
    assert state.state == "on"
    assert state.attributes["device_class"] == "battery"
    assert ir.async_get(hass).async_get_issue(
        const.DOMAIN, f"battery_replace_{entry.entry_id}_AAA111"
    )


async def test_upgrade_enables_battery_status_unless_the_user_disabled_it(hass):
    entry = MockConfigEntry(
        domain=const.DOMAIN,
        unique_id="p",
        version=1,
        minor_version=1,
        data={const.CONF_PROJECT_ID: "p", const.CONF_CREDENTIALS_JSON: '{"type":"x"}'},
        options={
            const.CONF_DEVICES: [
                {"serial": "AAA111", "device_id": 1001, "name": "Front"},
                {"serial": "BBB222", "device_id": 1002, "name": "Back"},
            ]
        },
    )
    entry.add_to_hass(hass)
    registry = er.async_get(hass)

    def _old_entity(unique_id, disabled_by):
        return registry.async_get_or_create(
            "binary_sensor",
            const.DOMAIN,
            unique_id,
            config_entry=entry,
            disabled_by=disabled_by,
        ).entity_id

    ours = _old_entity("AAA111_battery_poor", er.RegistryEntryDisabler.INTEGRATION)
    users = _old_entity("BBB222_battery_poor", er.RegistryEntryDisabler.USER)
    other = _old_entity("AAA111_wick_renewal", er.RegistryEntryDisabler.INTEGRATION)

    with _patch_client(), _patch_fetch():
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert registry.async_get(ours).disabled_by is None
    assert registry.async_get(users).disabled_by is er.RegistryEntryDisabler.USER
    assert registry.async_get(other).disabled_by is er.RegistryEntryDisabler.INTEGRATION
    assert (entry.version, entry.minor_version) == (1, 2)


async def test_entry_from_a_newer_version_is_not_loaded(hass):
    entry = MockConfigEntry(
        domain=const.DOMAIN,
        unique_id="p",
        version=2,
        data={const.CONF_PROJECT_ID: "p", const.CONF_CREDENTIALS_JSON: '{"type":"x"}'},
        options={const.CONF_DEVICES: []},
    )
    entry.add_to_hass(hass)
    with _patch_client(), _patch_fetch():
        await hass.config_entries.async_setup(entry.entry_id)
    assert entry.state is ConfigEntryState.MIGRATION_ERROR


def _issues(hass):
    return [key for key in ir.async_get(hass).issues if key[0] == const.DOMAIN]


async def test_access_denied_raises_a_repair_issue_until_a_query_succeeds(hass):
    entry = _entry(hass)
    with (
        _patch_client(),
        _patch_fetch(side_effect=GeoDropsAccessDeniedError("403 Access Denied")),
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.SETUP_RETRY  # keeps retrying, no reauth
    assert _reauth_flows(hass) == []
    issue = ir.async_get(hass).async_get_issue(
        const.DOMAIN, f"access_denied_{entry.entry_id}"
    )
    assert issue.translation_key == "access_denied"
    assert issue.translation_placeholders == {
        "project_id": "p",
        "error": "403 Access Denied",
    }
    assert not issue.is_fixable

    with _patch_client(), _patch_fetch():
        await hass.config_entries.async_reload(entry.entry_id)
        await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED
    assert _issues(hass) == []


async def test_other_query_errors_raise_no_repair_issue(hass):
    entry = _entry(hass)
    with _patch_client(), _patch_fetch(side_effect=GeoDropsQueryError("503")):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.SETUP_RETRY
    assert _issues(hass) == []


async def test_removing_the_entry_removes_its_repair_issue(hass):
    entry = _entry(hass)
    with _patch_client(), _patch_fetch(side_effect=GeoDropsAccessDeniedError("403")):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    assert len(_issues(hass)) == 1
    await hass.config_entries.async_remove(entry.entry_id)
    await hass.async_block_till_done()
    assert _issues(hass) == []


def _max_moisture_reading(device_id=1001):
    return replace(_reading(device_id), next_action=frozenset({"ATT_DW_NEW"}))


async def _setup_with(hass, entry, readings):
    with _patch_client(), _patch_fetch(return_value=readings):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()


async def _poll(entry, readings):
    with _patch_fetch(return_value=readings):
        await entry.runtime_data.async_refresh()


async def test_max_moisture_code_raises_a_repair_until_it_clears(hass):
    entry = _entry(hass)
    await _setup_with(hass, entry, {1001: _max_moisture_reading()})
    issue = ir.async_get(hass).async_get_issue(
        const.DOMAIN, f"max_moisture_required_{entry.entry_id}_AAA111"
    )
    assert issue.translation_key == "max_moisture_required"
    assert issue.translation_placeholders == {"name": "Front", "serial": "AAA111"}
    assert issue.severity is ir.IssueSeverity.WARNING
    assert not issue.is_fixable

    await _poll(entry, {1001: _reading()})
    assert _issues(hass) == []


async def test_expired_calibration_raises_its_own_repair(hass):
    entry = _entry(hass)
    reading = replace(_reading(), next_action=frozenset({"DW_RENEW", "DW_M_LOW1"}))
    await _setup_with(hass, entry, {1001: reading})
    assert _issues(hass) == [
        (const.DOMAIN, f"max_moisture_recalibration_{entry.entry_id}_AAA111")
    ]
    issue = ir.async_get(hass).async_get_issue(*_issues(hass)[0])
    assert issue.translation_key == "max_moisture_recalibration"
    assert issue.translation_placeholders == {"name": "Front", "serial": "AAA111"}

    await _poll(entry, {1001: _reading()})
    assert _issues(hass) == []


async def test_max_moisture_repair_survives_a_poll_without_the_probe(hass):
    entry = _entry(hass)
    await _setup_with(hass, entry, {1001: _max_moisture_reading()})
    await _poll(entry, {})  # GeoDrops' table is briefly empty
    assert len(_issues(hass)) == 1
    await _poll(entry, {1001: replace(_reading(), next_action=None)})
    assert len(_issues(hass)) == 1  # no nextAction column: unknown, not fixed


async def test_no_repair_without_the_max_moisture_code(hass):
    entry = _entry(hass)
    await _setup_with(hass, entry, {1001: _reading()})
    assert _issues(hass) == []


async def test_removed_probe_takes_its_max_moisture_repair(hass):
    entry = _entry(hass)
    await _setup_with(hass, entry, {1001: _max_moisture_reading()})
    assert len(_issues(hass)) == 1
    with _patch_client(), _patch_fetch(return_value={}):
        hass.config_entries.async_update_entry(
            entry, options={**entry.options, const.CONF_DEVICES: []}
        )
        await hass.config_entries.async_reload(entry.entry_id)
        await hass.async_block_till_done()
    assert _issues(hass) == []


async def test_removing_the_entry_removes_its_max_moisture_repairs(hass):
    entry = _entry(hass)
    await _setup_with(hass, entry, {1001: _max_moisture_reading()})
    assert len(_issues(hass)) == 1
    await hass.config_entries.async_remove(entry.entry_id)
    await hass.async_block_till_done()
    assert _issues(hass) == []


async def test_errors_are_translated(hass):
    entry = _entry(hass)
    with _patch_client(), _patch_fetch():
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    coordinator = entry.runtime_data
    for exc, key in (
        (GeoDropsQueryError("503"), "query_failed"),
        (GeoDropsAccessDeniedError("403"), "access_denied"),
        (GeoDropsAuthError("invalid_grant"), "auth_failed"),
    ):
        with _patch_fetch(side_effect=exc):
            await coordinator.async_refresh()
        err = coordinator.last_exception
        assert (err.translation_domain, err.translation_key) == (const.DOMAIN, key)
        assert err.translation_placeholders == {"error": str(exc)}


async def test_errors_hide_the_gcp_account_from_the_log(hass, caplog):
    # Home Assistant logs these errors, and logs get pasted into public issues.
    entry = _entry(hass)
    key = json.dumps(
        {
            "type": "x",
            "client_email": "ha@key-project.iam.gserviceaccount.com",
            "project_id": "key-project",
        }
    )
    hass.config_entries.async_update_entry(
        entry,
        data={const.CONF_PROJECT_ID: "my-project", const.CONF_CREDENTIALS_JSON: key},
    )
    with _patch_client(), _patch_fetch():
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    coordinator = entry.runtime_data
    error = (
        "403 Access Denied: ha@key-project.iam.gserviceaccount.com cannot "
        "use key-project in my-project"
    )
    redacted = "403 Access Denied: **REDACTED** cannot use **REDACTED** in **REDACTED**"
    for exc_type in (GeoDropsQueryError, GeoDropsAccessDeniedError, GeoDropsAuthError):
        with _patch_fetch(side_effect=exc_type(error)):
            await coordinator.async_refresh()
            await hass.async_block_till_done()
        placeholders = coordinator.last_exception.translation_placeholders
        assert placeholders == {"error": redacted}
    assert redacted in caplog.text
    assert "key-project" not in caplog.text
    assert "my-project" not in caplog.text
    # The repair stays in the user's own UI and names the project anyway, so it
    # keeps Google's full text.
    (issue_key,) = _issues(hass)
    issue = ir.async_get(hass).issues[issue_key]
    assert issue.translation_placeholders["error"] == error


async def test_unparseable_key_error_is_translated(hass):
    entry = _entry(hass)
    with (
        _patch_client(side_effect=GeoDropsCredentialsError("bad json")),
        pytest.raises(ConfigEntryAuthFailed) as info,
    ):
        await async_setup_entry(hass, entry)
    assert info.value.translation_key == "invalid_credentials"


async def test_deleting_a_probe_from_its_device_page(hass):
    entry = _entry(hass)
    hass.config_entries.async_update_entry(
        entry,
        options={
            const.CONF_DEVICES: [
                {"serial": "AAA111", "device_id": 1001, "name": "Front"},
                {"serial": "BBB222", "device_id": 1002, "name": "Back"},
            ]
        },
    )
    with _patch_client(), _patch_fetch():
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    (device,) = [
        d
        for d in dr.async_entries_for_config_entry(dr.async_get(hass), entry.entry_id)
        if (const.DOMAIN, "AAA111") in d.identifiers
    ]

    assert await async_remove_config_entry_device(hass, entry, device)
    assert [d["serial"] for d in entry.options[const.CONF_DEVICES]] == ["BBB222"]
    assert entry.runtime_data.device_ids == [1002]  # no longer polled


async def test_deleting_an_unknown_device_leaves_probes_alone(hass):
    entry = _entry(hass)
    with _patch_client(), _patch_fetch():
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    orphan = dr.async_get(hass).async_get_or_create(
        config_entry_id=entry.entry_id, identifiers={(const.DOMAIN, "ZZZ999")}
    )

    assert await async_remove_config_entry_device(hass, entry, orphan)
    assert [d["serial"] for d in entry.options[const.CONF_DEVICES]] == ["AAA111"]
