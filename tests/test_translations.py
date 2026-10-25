import json
from pathlib import Path
import re

from custom_components.geodrops.binary_sensor import BINARY_SENSOR_DESCRIPTIONS
from custom_components.geodrops.sensor import (
    LAST_READING_DESCRIPTION,
    SENSOR_DESCRIPTIONS,
    WATERING_DESCRIPTIONS,
)

ALL_SENSORS = (*SENSOR_DESCRIPTIONS, LAST_READING_DESCRIPTION, *WATERING_DESCRIPTIONS)
ROOT = Path(__file__).parent.parent / "custom_components" / "geodrops"
# hassfest's translation_key_validator: translation keys, state keys and
# icons.json state keys must all look like this
KEY = re.compile(r"^[a-z0-9_-]+$")


def _load(name):
    return json.loads((ROOT / name).read_text(encoding="utf-8"))


def _sensor_strings():
    return _load("strings.json")["entity"]["sensor"]


def _enum_specs():
    return [s for s in SENSOR_DESCRIPTIONS if s.options]


def test_en_json_matches_strings_json():
    # custom integrations ship translations/en.json as-is (no build step)
    assert _load("translations/en.json") == _load("strings.json")


def test_every_sensor_has_a_translated_name_with_its_placeholders():
    strings = _sensor_strings()
    for spec in ALL_SENSORS:
        name = strings[spec.translation_key]["name"]
        assert set(re.findall(r"{(\w+)}", name)) == set(
            spec.translation_placeholders or {}
        ), spec.key


def test_no_unused_sensor_translations():
    assert set(_sensor_strings()) == {s.translation_key for s in ALL_SENSORS}


def test_every_enum_state_has_a_label_and_an_icon():
    strings, icons = _sensor_strings(), _load("icons.json")["entity"]["sensor"]
    for spec in _enum_specs():
        assert set(strings[spec.translation_key]["state"]) == set(spec.options or []), (
            spec.key
        )
        assert set(icons[spec.translation_key]["state"]) == set(spec.options or []), (
            spec.key
        )


def test_icons_only_reference_real_sensors():
    icons = _load("icons.json")["entity"]["sensor"]
    assert set(icons) <= {s.translation_key for s in ALL_SENSORS}


def test_keys_pass_hassfest_validation():
    keys = []
    for key, entry in _sensor_strings().items():
        keys += [key, *entry.get("state", {})]
    for key, entry in _load("icons.json")["entity"]["sensor"].items():
        keys += [key, *entry.get("state", {})]
    for spec in _enum_specs():
        keys += spec.options
    assert [k for k in keys if not KEY.match(k)] == []


def test_binary_sensor_translations_match_descriptions():
    strings = _load("strings.json")["entity"]["binary_sensor"]
    keys = {d.translation_key for d in BINARY_SENSOR_DESCRIPTIONS}
    assert set(strings) == keys
    assert all(strings[k]["name"] for k in keys)
    assert [k for k in strings if not KEY.match(k)] == []


def test_binary_sensor_icons_only_reference_real_binary_sensors():
    icons = _load("icons.json")["entity"]["binary_sensor"]
    assert set(icons) <= {d.translation_key for d in BINARY_SENSOR_DESCRIPTIONS}
