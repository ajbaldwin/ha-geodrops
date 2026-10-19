from dataclasses import replace
from datetime import timedelta
from unittest.mock import MagicMock

from aiogeodrops import DeviceReading

from custom_components.geodrops import const
from custom_components.geodrops.sensor import SENSOR_DESCRIPTIONS, build_sensors
from homeassistant.components.sensor import SensorDeviceClass
from homeassistant.const import EntityCategory
from homeassistant.helpers import area_registry as ar
from homeassistant.util import dt as dt_util


def _reading(all_training=False):
    q = -1 if all_training else 2
    return DeviceReading(
        device_id=1001,
        sync_delay_hours=2.0,
        moisture_index=3,
        moisture_pct=42.5,
        moisture_d1=40.0,
        moisture_d2=41.0,
        moisture_d3=42.0,
        temp_surface=19.0,
        temp_d1=18.0,
        temp_d2=17.0,
        temp_d3=16.0,
        battery_pct=88.0,
        sun_7d=6.0,
        qcn_d1=q,
        qcn_d2=q,
        qcn_d3=q,
        battery_mv=3010.0,
        rssi_dbm=-97.0,
    )


def _coord(reading, skip_hours=12, seen=None):
    c = MagicMock()
    c.reading.return_value = reading
    c.config_entry.options = {const.CONF_SKIP_HOURS: skip_hours}
    # default: the device's row just arrived, so tests that don't care about
    # FIX 8's expire_after_minutes wiring stay within the window
    c.reading_time.return_value = seen if seen is not None else dt_util.utcnow()
    return c


def test_21_sensors_per_device():
    assert len(SENSOR_DESCRIPTIONS) == 21


def test_moisture_value_and_state():
    coord = _coord(_reading())
    sensors = build_sensors(
        coord, {"serial": "AAA111", "device_id": 1001, "name": "Front"}
    )
    by_suffix = {s.entity_description.key: s for s in sensors}
    assert by_suffix["moisture"].native_value == 42.5
    assert by_suffix["moisture_state"].native_value == "moist_plus"
    assert by_suffix["battery"].native_value == 88  # rounded int
    assert by_suffix["qcn_d1"].native_value == "good"


def test_moisture_unknown_when_all_training():
    coord = _coord(_reading(all_training=True))
    sensors = build_sensors(
        coord, {"serial": "AAA111", "device_id": 1001, "name": "Front"}
    )
    by_suffix = {s.entity_description.key: s for s in sensors}
    assert by_suffix["moisture"].native_value is None  # omitted when all-training
    assert by_suffix["battery"].native_value == 88  # telemetry still reported


def test_sync_delay_does_not_make_the_probe_unavailable():
    # a 13 h delay passes the plausibility check on an 11 h-old reading, but
    # only the reading's own age (11 h, under skip) decides availability
    coord = _coord(_reading())
    coord.reading.return_value = DeviceReading(
        **{
            **_reading().__dict__,
            "sync_delay_hours": 13.0,
            "read_at": dt_util.utcnow() - timedelta(hours=11),
        }
    )
    sensors = build_sensors(
        coord, {"serial": "AAA111", "device_id": 1001, "name": "Front"}
    )
    assert sensors[0].available is True


def test_unavailable_when_feed_is_stale_even_if_reading_is_fresh():
    # FIX 8 "both signals": expire_after_minutes (default 80) must also gate
    # availability -- a device whose row has not come back from any poll recently
    # (failed polls, or polls that return no row for it) goes unavailable even
    # though the last reading's own sync delay is fresh.
    coord = _coord(_reading(), seen=dt_util.utcnow() - timedelta(hours=2))
    sensors = build_sensors(
        coord, {"serial": "AAA111", "device_id": 1001, "name": "Front"}
    )
    assert sensors[0].available is False


def test_default_expire_rides_out_three_missed_polls():
    # default 80 min at the default 20 min poll: 3 consecutive polls without the
    # device's row (failed or empty) keep sensors up; the 4th makes them unavailable
    assert const.DEFAULT_EXPIRE_MINUTES == 80
    device = {"serial": "AAA111", "device_id": 1001, "name": "Front"}
    recent = _coord(_reading(), seen=dt_util.utcnow() - timedelta(minutes=75))
    assert build_sensors(recent, device)[0].available is True
    old = _coord(_reading(), seen=dt_util.utcnow() - timedelta(minutes=85))
    assert build_sensors(old, device)[0].available is False


def test_unavailable_when_never_successfully_updated():
    coord = _coord(_reading())
    coord.reading_time.return_value = None  # no poll has ever returned this device
    sensors = build_sensors(
        coord, {"serial": "AAA111", "device_id": 1001, "name": "Front"}
    )
    assert sensors[0].available is False


async def test_device_info_area_and_model(hass):
    area = ar.async_get(hass).async_create("Backyard")
    coord = _coord(_reading())
    coord.hass = hass
    device = {
        "serial": "AAA111",
        "device_id": 1001,
        "name": "Front",
        "area_id": area.id,
    }
    sensors = build_sensors(coord, device)
    info = sensors[0].device_info
    assert info["suggested_area"] == "Backyard"
    assert info["model"] == "GeoDrops Droplet"
    assert info["name"] == "Front"
    assert info["serial_number"] == "AAA111"
    assert "sw_version" not in info  # was hard-coded; GeoDrops doesn't report firmware


DEVICE = {"serial": "AAA111", "device_id": 1001, "name": "Front"}


def _sensor(coord, suffix):
    return {s.entity_description.key: s for s in build_sensors(coord, DEVICE)}[suffix]


def _with(**changes):
    return DeviceReading(**{**_reading().__dict__, **changes})


def test_missing_values_read_unknown_not_zero():
    coord = _coord(_with(battery_pct=None, temp_d1=None, moisture_pct=None))
    assert _sensor(coord, "battery").native_value is None
    assert _sensor(coord, "temp_d1").native_value is None
    assert _sensor(coord, "moisture").native_value is None


def test_unknown_sync_delay_does_not_make_the_probe_unavailable():
    coord = _coord(_with(sync_delay_hours=None))
    assert _sensor(coord, "moisture").available is True


def test_impossible_sync_delay_is_unknown_and_keeps_the_probe_available():
    coord = _coord(
        _with(sync_delay_hours=2053.1, read_at=dt_util.utcnow() - timedelta(hours=1))
    )
    assert _sensor(coord, "moisture").available is True
    assert _sensor(coord, "sync_delay").native_value is None


def test_unavailable_when_reading_timestamp_is_older_than_skip():
    # the row's sync delay is frozen at 2 h, but the reading itself is 13 h old
    old = dt_util.utcnow() - timedelta(hours=13)
    coord = _coord(_with(read_at=old), skip_hours=12)
    assert _sensor(coord, "moisture").available is False


def test_available_when_reading_timestamp_is_recent():
    recent = dt_util.utcnow() - timedelta(hours=3)
    coord = _coord(_with(read_at=recent), skip_hours=12)
    assert _sensor(coord, "moisture").available is True


def test_last_reading_sensor_reports_the_reading_timestamp():
    when = dt_util.utcnow() - timedelta(minutes=30)
    sensor = _sensor(_coord(_with(read_at=when)), "last_reading")
    assert sensor.device_class == SensorDeviceClass.TIMESTAMP
    assert sensor.native_value == when
    assert sensor.unique_id == "AAA111_last_reading"


def test_last_reading_is_never_in_the_future():
    # GeoDrops labels a reading with the end of its half-hour slot, so a batch
    # uploaded mid-slot carries a `date` up to 30 minutes ahead.
    ahead = dt_util.utcnow() + timedelta(minutes=28)
    sensor = _sensor(_coord(_with(read_at=ahead)), "last_reading")
    before = dt_util.utcnow()
    value = sensor.native_value
    assert before <= value <= dt_util.utcnow()


def test_last_reading_is_reported_even_while_training():
    when = dt_util.utcnow()
    sensor = _sensor(
        _coord(
            DeviceReading(**{**_reading(all_training=True).__dict__, "read_at": when})
        ),
        "last_reading",
    )
    assert sensor.native_value == when


def test_no_reading_yet_is_unavailable_and_unknown():
    coord = _coord(None)
    sensor = _sensor(coord, "moisture_state")
    assert sensor.available is False
    assert sensor.native_value is None


def test_depth_sensors_share_a_translation_with_a_depth_placeholder():
    coord = _coord(_reading())
    sensor = _sensor(coord, "qcn_d2")
    assert sensor.translation_key == "qcn_depth"
    assert sensor.translation_placeholders == {"depth": "2"}
    assert sensor.unique_id == "AAA111_qcn_d2"  # unchanged, so entities carry over


def test_sync_delay_is_a_duration_in_hours():
    sensor = _sensor(_coord(_reading()), "sync_delay")
    assert sensor.device_class == SensorDeviceClass.DURATION
    assert sensor.native_unit_of_measurement == "h"
    assert sensor.native_value == 2.0


def test_battery_voltage_and_signal_strength():
    coord = _coord(_reading())
    assert _sensor(coord, "battery_voltage").native_value == 3010.0
    assert _sensor(coord, "signal_strength").native_value == -97.0
    unknown = _coord(replace(_reading(), battery_mv=None, rssi_dbm=None))
    assert _sensor(unknown, "battery_voltage").native_value is None
    assert _sensor(unknown, "signal_strength").native_value is None


def test_overall_quality_is_a_diagnostic_enum():
    sensor = _sensor(_coord(replace(_reading(), qcn=1)), "qcn")
    assert sensor.native_value == "poor"
    assert sensor.device_class == SensorDeviceClass.ENUM
    assert sensor.entity_category is EntityCategory.DIAGNOSTIC
    assert sensor.entity_registry_enabled_default
    assert (
        _sensor(_coord(replace(_reading(), qcn=-1)), "qcn").native_value == "training"
    )


def test_status_from_next_action_codes():
    reading = replace(_reading(), next_action=frozenset({"ATT_DW_NEW", "DW_M_LOW1"}))
    sensor = _sensor(_coord(reading), "status")
    assert sensor.native_value == "max_moisture_required"
    assert sensor.device_class == SensorDeviceClass.ENUM
    assert sensor.entity_category is EntityCategory.DIAGNOSTIC
    assert sensor.entity_registry_enabled_default
    no_column = _coord(replace(_reading(), next_action=None))
    assert _sensor(no_column, "status").native_value is None


def test_next_action_codes_sensor_lists_the_raw_codes():
    reading = replace(_reading(), next_action=frozenset({"DW_M_LOW12", "CHK_M_HWR"}))
    sensor = _sensor(_coord(reading), "next_action")
    assert sensor.native_value == "CHK_M_HWR, DW_M_LOW12"
    assert sensor.entity_category is EntityCategory.DIAGNOSTIC
    assert not sensor.entity_registry_enabled_default
    none = _coord(replace(_reading(), next_action=frozenset()))
    assert _sensor(none, "next_action").native_value == "none"
    no_column = _coord(replace(_reading(), next_action=None))
    assert _sensor(no_column, "next_action").native_value is None
