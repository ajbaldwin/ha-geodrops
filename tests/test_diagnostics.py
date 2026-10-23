from datetime import UTC, datetime
import json
from unittest.mock import MagicMock

from aiogeodrops import BatteryPoint, DeviceReading, GeoDropsQueryError
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.geodrops import const
from custom_components.geodrops.diagnostics import async_get_config_entry_diagnostics
from homeassistant.helpers.json import json_dumps
from tests.common import patch_client

READ_AT = datetime(2026, 9, 29, 6, 0, tzinfo=UTC)


def _reading():
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
        read_at=READ_AT,
        next_action=frozenset({"DW_M_LOW12", "ATT_DW_NEW"}),
    )


async def _setup(hass, credentials='{"private_key":"secret"}', history=None):
    entry = MockConfigEntry(
        domain=const.DOMAIN,
        unique_id="my-project",
        data={
            const.CONF_PROJECT_ID: "my-project",
            const.CONF_CREDENTIALS_JSON: credentials,
        },
        options={
            const.CONF_DEVICES: [
                {"serial": "AAA111", "device_id": 1001, "name": "Front"},
                {"serial": "BBB222", "device_id": 1002, "name": "Back"},
            ]
        },
    )
    entry.add_to_hass(hass)
    with (
        patch_client("fetch_latest", return_value={1001: _reading()}),
        patch_client("fetch_battery_history", return_value=history or {}),
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    return entry


async def test_diagnostics_redact_the_key_and_project(hass):
    entry = await _setup(hass)
    diag = await async_get_config_entry_diagnostics(hass, entry)

    assert diag["entry"]["data"] == {
        const.CONF_PROJECT_ID: "**REDACTED**",
        const.CONF_CREDENTIALS_JSON: "**REDACTED**",
    }
    assert "secret" not in str(diag)
    assert "my-project" not in str(diag)
    assert diag["entry"]["options"] == dict(entry.options)
    assert diag["coordinator"] == {
        "last_update_success": True,
        "last_exception": None,
        "update_interval_seconds": 1200.0,
        "missing_columns": [],
    }


async def test_diagnostics_show_each_probes_last_reading(hass):
    entry = await _setup(hass)
    probes = (await async_get_config_entry_diagnostics(hass, entry))["probes"]

    front = probes["AAA111"]
    assert front["device_id"] == 1001
    assert front["last_seen_in_poll"] is not None
    assert front["reading"]["moisture_pct"] == 42.0
    assert front["reading"]["read_at"] == READ_AT
    # a frozenset would make Home Assistant's JSON encoder fail
    assert front["reading"]["next_action"] == ["ATT_DW_NEW", "DW_M_LOW12"]
    json_dumps(probes)
    # a probe the poll hasn't returned yet
    assert probes["BBB222"] == {
        "device_id": 1002,
        "last_seen_in_poll": None,
        "reading": None,
        "battery": {"outlook": None, "slope_mv_per_day": None, "daily_mv": []},
    }


async def test_diagnostics_show_each_probes_battery_trend(hass):
    days = [datetime(2026, 9, 16 + d, 12, 0, tzinfo=UTC) for d in range(14)]
    history = {1001: [BatteryPoint(t, 5400.0 - 4 * d) for d, t in enumerate(days)]}
    entry = await _setup(hass, history=history)
    probes = (await async_get_config_entry_diagnostics(hass, entry))["probes"]

    battery = probes["AAA111"]["battery"]
    assert battery["outlook"] == "ok"
    assert battery["slope_mv_per_day"] == -4.0
    assert battery["daily_mv"][0] == ["2026-09-16", 5400.0]
    assert battery["daily_mv"][-1] == ["2026-09-29", 5348.0]
    json_dumps(probes)


async def test_diagnostics_redact_the_project_from_the_last_error(hass):
    entry = await _setup(hass)
    coordinator = entry.runtime_data
    with patch_client(
        "fetch_latest",
        side_effect=GeoDropsQueryError("404 Not found: Job my-project:US.job_1"),
    ):
        await coordinator.async_refresh()

    diag = await async_get_config_entry_diagnostics(hass, entry)
    assert diag["coordinator"]["last_update_success"] is False
    assert diag["coordinator"]["last_exception"].startswith("UpdateFailed: ")
    assert "Job **REDACTED**:US.job_1" in diag["coordinator"]["last_exception"]
    assert "my-project" not in str(diag)


async def test_diagnostics_redact_the_service_account_from_the_last_error(hass):
    # The key can come from another project than the one queries are billed to.
    key = json.dumps(
        {
            "private_key": "secret",
            "client_email": "ha@key-project.iam.gserviceaccount.com",
            "project_id": "key-project",
        }
    )
    entry = await _setup(hass, key)
    error = (
        "403 Access Denied: ha@key-project.iam.gserviceaccount.com cannot "
        "use key-project in my-project"
    )
    with patch_client("fetch_latest", side_effect=GeoDropsQueryError(error)):
        await entry.runtime_data.async_refresh()

    diag = await async_get_config_entry_diagnostics(hass, entry)
    last = diag["coordinator"]["last_exception"]
    assert last.endswith(
        "403 Access Denied: **REDACTED** cannot use **REDACTED** in **REDACTED**"
    )
    assert "key-project" not in str(diag)


async def test_diagnostics_with_an_unparseable_stored_key(hass):
    # Setup fails (reauth), but diagnostics must still not crash.
    entry = await _setup(hass, "not json")
    entry.runtime_data = MagicMock(
        last_exception=GeoDropsQueryError("in my-project"),
        devices=[],
        update_interval=None,
    )
    diag = await async_get_config_entry_diagnostics(hass, entry)
    assert diag["coordinator"]["last_exception"].endswith("in **REDACTED**")
    assert diag["coordinator"]["update_interval_seconds"] is None


async def test_diagnostics_list_columns_missing_from_the_table(hass):
    entry = await _setup(hass)
    entry.runtime_data.client.missing_columns = frozenset({"qcn", "deviceBattMV"})

    diag = await async_get_config_entry_diagnostics(hass, entry)

    assert diag["coordinator"]["missing_columns"] == ["deviceBattMV", "qcn"]
