"""GeoDrops binary sensors: 4 per probe.

Battery Status comes from the coordinator's battery outlook; the rest are flags
from the probe's latest reading.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from aiogeodrops import DeviceReading

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import const
from .const import DeviceConfig
from .coordinator import GeoDropsConfigEntry, GeoDropsCoordinator
from .entity import GeoDropsEntity
from .transform import (
    ERROR_CODES,
    HARDWARE_CODES,
    MAX_MOISTURE_CODES,
    RECALIBRATION_CODES,
    has_code,
)

# The coordinator does all fetching, so entity updates need no limit.
PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class GeoDropsBinarySensorEntityDescription(BinarySensorEntityDescription):
    """A GeoDrops binary sensor.

    `key` is the unique-id suffix: never change it (entities would be
    re-created). `translation_key` names it in strings.json.
    """

    value_fn: Callable[[DeviceReading], bool | None] | None = None
    """The flag from the latest reading."""
    coordinator_fn: Callable[[GeoDropsCoordinator, int], bool | None] | None = None
    """The flag from the coordinator, given the device id; set instead of value_fn."""


def _battery_low(coordinator: GeoDropsCoordinator, device_id: int) -> bool | None:
    """Return whether the batteries need replacing soon, or None if unknown."""
    outlook = coordinator.battery_outlook(device_id)
    return None if outlook is None else outlook != "ok"


BINARY_SENSOR_DESCRIPTIONS: tuple[GeoDropsBinarySensorEntityDescription, ...] = (
    GeoDropsBinarySensorEntityDescription(
        key="battery_poor",
        translation_key="battery_status",
        # The key predates the battery trend; it keeps the unique id.
        coordinator_fn=_battery_low,
        device_class=BinarySensorDeviceClass.BATTERY,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    # From GeoDrops' nextAction codes; see transform.py.
    GeoDropsBinarySensorEntityDescription(
        key="max_moisture_required",
        translation_key="max_moisture_required",
        value_fn=lambda r: has_code(r.next_action, MAX_MOISTURE_CODES),
        device_class=BinarySensorDeviceClass.PROBLEM,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    GeoDropsBinarySensorEntityDescription(
        # The key predates knowing what DW_RENEW means; it keeps the unique id.
        key="wick_renewal",
        translation_key="max_moisture_recalibration",
        value_fn=lambda r: has_code(r.next_action, RECALIBRATION_CODES),
        device_class=BinarySensorDeviceClass.PROBLEM,
        entity_category=EntityCategory.DIAGNOSTIC,
        # Only applies when a probe is first added; Probe Health covers it.
        entity_registry_enabled_default=False,
    ),
    GeoDropsBinarySensorEntityDescription(
        key="hardware_problem",
        translation_key="hardware_problem",
        value_fn=lambda r: has_code(r.next_action, HARDWARE_CODES | ERROR_CODES),
        device_class=BinarySensorDeviceClass.PROBLEM,
        entity_category=EntityCategory.DIAGNOSTIC,
        # Only applies when a probe is first added; Probe Health covers it.
        entity_registry_enabled_default=False,
    ),
)


class GeoDropsBinarySensor(GeoDropsEntity, BinarySensorEntity):
    """One flag from a probe's latest reading."""

    entity_description: GeoDropsBinarySensorEntityDescription

    @property
    def is_on(self) -> bool | None:
        """Return the flag, unknown while there is no reading."""
        r = self._reading
        if r is None:
            return None
        desc = self.entity_description
        if desc.coordinator_fn is not None:
            return desc.coordinator_fn(self.coordinator, self._device[const.DEV_ID])
        assert desc.value_fn is not None
        return desc.value_fn(r)


def build_binary_sensors(
    coordinator: GeoDropsCoordinator, device: DeviceConfig
) -> list[GeoDropsBinarySensor]:
    """Create every binary sensor for one probe."""
    return [
        GeoDropsBinarySensor(coordinator, device, desc)
        for desc in BINARY_SENSOR_DESCRIPTIONS
    ]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: GeoDropsConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add the binary sensors for every configured probe."""
    coordinator = entry.runtime_data
    entities: list[GeoDropsBinarySensor] = []
    for device in coordinator.devices:
        entities.extend(build_binary_sensors(coordinator, device))
    async_add_entities(entities)
