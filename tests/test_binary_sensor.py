from dataclasses import replace

import pytest

from custom_components.geodrops.binary_sensor import build_binary_sensors
from homeassistant.components.binary_sensor import BinarySensorDeviceClass
from homeassistant.const import EntityCategory

from .test_sensor import _coord, _reading

DEVICE = {"serial": "AAA111", "device_id": 1001, "name": "Front"}


def _binary_sensor(reading, key, outlook=None):
    coord = _coord(reading)
    coord.battery_outlook.return_value = outlook
    sensors = build_binary_sensors(coord, DEVICE)
    return {s.entity_description.key: s for s in sensors}[key]


def _battery_status(reading=None, outlook=None):
    return _binary_sensor(reading or _reading(), "battery_poor", outlook)


def test_four_binary_sensors_per_device():
    assert len(build_binary_sensors(_coord(_reading()), DEVICE)) == 4


def test_binary_sensors_are_diagnostic_problems_except_battery():
    for sensor in build_binary_sensors(_coord(_reading()), DEVICE):
        expected = (
            BinarySensorDeviceClass.BATTERY
            if sensor.entity_description.key == "battery_poor"
            else BinarySensorDeviceClass.PROBLEM
        )
        assert sensor.device_class is expected
        assert sensor.entity_category is EntityCategory.DIAGNOSTIC


def test_enabled_by_default():
    enabled = {
        s.entity_description.key
        for s in build_binary_sensors(_coord(_reading()), DEVICE)
        if s.entity_registry_enabled_default
    }
    assert enabled == {"max_moisture_required", "battery_poor"}


@pytest.mark.parametrize(
    ("outlook", "on"),
    [("ok", False), ("soon", True), ("now", True), (None, None)],
)
def test_battery_status_follows_the_battery_outlook(outlook, on):
    sensor = _battery_status(outlook=outlook)
    assert sensor.is_on is on
    sensor.coordinator.battery_outlook.assert_called_with(1001)


def test_battery_status_ignores_geodrops_flag():
    sensor = _battery_status(replace(_reading(), battery_poor=True), outlook="ok")
    assert sensor.is_on is False
    assert sensor.unique_id == "AAA111_battery_poor"  # kept from the old meaning
    assert sensor.translation_key == "battery_status"


def test_battery_status_is_unknown_without_a_reading():
    sensor = build_binary_sensors(_coord(None), DEVICE)[0]
    sensor.coordinator.battery_outlook.return_value = "now"
    assert sensor.entity_description.key == "battery_poor"
    assert sensor.is_on is None


@pytest.mark.parametrize(
    ("codes", "on"),
    [
        ({"ATT_DW_NEW"}, {"max_moisture_required"}),
        ({"DW_RENEW", "DW_M_LOW12"}, {"wick_renewal"}),
        ({"CHK_M_HWR"}, {"hardware_problem"}),
        ({"ERR_LOSS"}, {"hardware_problem"}),
        ({"ATT_DW_NEW", "NULL_HWR"}, {"max_moisture_required", "hardware_problem"}),
        ({"DW_M_LOW3", "LAX_M_EVA12", "ATT_SS_NEW"}, set()),
        (set(), set()),
    ],
)
def test_next_action_problems(codes, on):
    reading = replace(_reading(), next_action=frozenset(codes))
    for key in ("max_moisture_required", "wick_renewal", "hardware_problem"):
        assert _binary_sensor(reading, key).is_on is (key in on)


def test_next_action_problems_are_unknown_without_the_column():
    reading = replace(_reading(), next_action=None)
    for key in ("max_moisture_required", "wick_renewal", "hardware_problem"):
        assert _binary_sensor(reading, key).is_on is None
