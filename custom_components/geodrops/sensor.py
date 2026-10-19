"""GeoDrops sensors: 23 per probe."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Self

from aiogeodrops import DeviceReading

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    PERCENTAGE,
    SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
    EntityCategory,
    UnitOfElectricPotential,
    UnitOfTemperature,
    UnitOfTime,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.restore_state import ExtraStoredData, RestoreEntity
from homeassistant.helpers.typing import StateType
from homeassistant.util import dt as dt_util

from .const import DeviceConfig
from .coordinator import GeoDropsConfigEntry, GeoDropsCoordinator
from .entity import GeoDropsEntity
from .transform import (
    MOISTURE_STATE_OPTIONS,
    QCN_OPTIONS,
    STATUS_OPTIONS,
    moisture_index_to_state,
    next_action_to_status,
    qcn_to_state,
    sync_delay_hours,
)

# The coordinator does all fetching, so entity updates need no limit.
PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class GeoDropsSensorEntityDescription(SensorEntityDescription):
    """A GeoDrops sensor.

    `key` is the unique-id suffix: never change it (entities would be
    re-created). `translation_key` names the sensor (and its enum state labels)
    in strings.json and its icons in icons.json.
    """

    value_fn: Callable[[DeviceReading], StateType | datetime]
    # Report None while every depth is still training.
    moisture_gated: bool = False


def _moisture(
    key: str,
    value_fn: Callable[[DeviceReading], float | None],
    depth: int | None = None,
) -> GeoDropsSensorEntityDescription:
    """Describe a moisture sensor: overall, or at one depth."""
    return GeoDropsSensorEntityDescription(
        key=key,
        translation_key="moisture" if depth is None else "moisture_depth",
        translation_placeholders=None if depth is None else {"depth": str(depth)},
        value_fn=value_fn,
        moisture_gated=True,
        device_class=SensorDeviceClass.MOISTURE,
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
    )


def _temperature(
    key: str,
    value_fn: Callable[[DeviceReading], float | None],
    depth: int | None = None,
) -> GeoDropsSensorEntityDescription:
    """Describe a temperature sensor: at the surface, or at one depth."""
    return GeoDropsSensorEntityDescription(
        key=key,
        translation_key="surface_temperature" if depth is None else "temperature_depth",
        translation_placeholders=None if depth is None else {"depth": str(depth)},
        value_fn=value_fn,
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
    )


def _quality(
    key: str, value_fn: Callable[[DeviceReading], int], depth: int
) -> GeoDropsSensorEntityDescription:
    """Describe a per-depth reading-quality sensor."""
    # Per-depth reading quality: diagnostic, but enabled by default because
    # other integrations (e.g. irrigation schedulers) read these states to
    # decide whether a probe's moisture reading can be trusted. A disabled
    # entity has no state at all, which they would treat as an untrustworthy
    # probe.
    return GeoDropsSensorEntityDescription(
        key=key,
        translation_key="qcn_depth",
        translation_placeholders={"depth": str(depth)},
        value_fn=lambda r: qcn_to_state(value_fn(r)),
        device_class=SensorDeviceClass.ENUM,
        options=QCN_OPTIONS,
        entity_category=EntityCategory.DIAGNOSTIC,
    )


SENSOR_DESCRIPTIONS: tuple[GeoDropsSensorEntityDescription, ...] = (
    _moisture("moisture", lambda r: r.moisture_pct),
    GeoDropsSensorEntityDescription(
        key="moisture_state",
        translation_key="moisture_state",
        value_fn=lambda r: moisture_index_to_state(r.moisture_index),
        moisture_gated=True,
        device_class=SensorDeviceClass.ENUM,
        options=MOISTURE_STATE_OPTIONS,
    ),
    _moisture("moisture_d1", lambda r: r.moisture_d1, depth=1),
    _moisture("moisture_d2", lambda r: r.moisture_d2, depth=2),
    _moisture("moisture_d3", lambda r: r.moisture_d3, depth=3),
    _quality("qcn_d1", lambda r: r.qcn_d1, depth=1),
    _quality("qcn_d2", lambda r: r.qcn_d2, depth=2),
    _quality("qcn_d3", lambda r: r.qcn_d3, depth=3),
    GeoDropsSensorEntityDescription(
        key="qcn",
        translation_key="qcn",
        value_fn=lambda r: qcn_to_state(r.qcn),
        device_class=SensorDeviceClass.ENUM,
        options=QCN_OPTIONS,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    GeoDropsSensorEntityDescription(
        key="status",
        translation_key="status",
        value_fn=lambda r: next_action_to_status(r.next_action),
        device_class=SensorDeviceClass.ENUM,
        options=STATUS_OPTIONS,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    # GeoDrops' raw nextAction codes, including ones Probe Health doesn't map.
    GeoDropsSensorEntityDescription(
        key="next_action",
        translation_key="next_action",
        value_fn=lambda r: (
            None
            if r.next_action is None
            else ", ".join(sorted(r.next_action)) or "none"
        ),
        entity_category=EntityCategory.DIAGNOSTIC,
        # Only applies when a probe is first added.
        entity_registry_enabled_default=False,
    ),
    GeoDropsSensorEntityDescription(
        key="battery",
        translation_key="battery",
        value_fn=lambda r: None if r.battery_pct is None else round(r.battery_pct),
        device_class=SensorDeviceClass.BATTERY,
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    GeoDropsSensorEntityDescription(
        key="battery_voltage",
        translation_key="battery_voltage",
        value_fn=lambda r: r.battery_mv,
        device_class=SensorDeviceClass.VOLTAGE,
        native_unit_of_measurement=UnitOfElectricPotential.MILLIVOLT,
        suggested_display_precision=0,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        # Only applies when a probe is first added.
        entity_registry_enabled_default=False,
    ),
    GeoDropsSensorEntityDescription(
        key="signal_strength",
        translation_key="signal_strength",
        value_fn=lambda r: r.rssi_dbm,
        device_class=SensorDeviceClass.SIGNAL_STRENGTH,
        native_unit_of_measurement=SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
        suggested_display_precision=0,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        # Only applies when a probe is first added.
        entity_registry_enabled_default=False,
    ),
    GeoDropsSensorEntityDescription(
        key="sync_delay",
        translation_key="sync_delay",
        value_fn=lambda r: sync_delay_hours(r, dt_util.utcnow()),
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.HOURS,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        # Only applies when a probe is first added.
        entity_registry_enabled_default=False,
    ),
    _temperature("temp_surface", lambda r: r.temp_surface),
    _temperature("temp_d1", lambda r: r.temp_d1, depth=1),
    _temperature("temp_d2", lambda r: r.temp_d2, depth=2),
    _temperature("temp_d3", lambda r: r.temp_d3, depth=3),
    # Hours of sun per day is a rate, so it has no duration device class.
    GeoDropsSensorEntityDescription(
        key="sun_7d",
        translation_key="sun_7d",
        value_fn=lambda r: r.sun_7d,
        native_unit_of_measurement=UnitOfTime.HOURS,
        state_class=SensorStateClass.MEASUREMENT,
        # Only applies when a probe is first added.
        entity_registry_enabled_default=False,
    ),
    GeoDropsSensorEntityDescription(
        key="last_reading",
        translation_key="last_reading",
        # GeoDrops labels a reading with the end of its half-hour slot, so a
        # mid-slot upload is up to 30 minutes ahead; never show a future time.
        value_fn=lambda r: (
            r.read_at if r.read_at is None else min(r.read_at, dt_util.utcnow())
        ),
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
)


@dataclass
class Watering(ExtraStoredData):
    """The last watering GeoDrops detected on a probe."""

    confidence: float  # GeoDrops' irrigation confidence, 0 to 1
    detected_at: datetime  # when the reading that showed it was taken

    def as_dict(self) -> dict[str, Any]:
        """Return the watering as restorable state data."""
        return {
            "confidence": self.confidence,
            "detected_at": self.detected_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Self | None:
        """Read a stored watering; None if the data isn't one."""
        try:
            detected_at = dt_util.parse_datetime(data["detected_at"])
            confidence = float(data["confidence"])
        except KeyError, TypeError, ValueError:
            return None
        if detected_at is None:
            return None
        return cls(confidence, detected_at)


@dataclass(frozen=True, kw_only=True)
class GeoDropsWateringSensorEntityDescription(SensorEntityDescription):
    """A sensor for the last watering GeoDrops detected on a probe."""

    value_fn: Callable[[Watering], StateType | datetime]


# GeoDrops marks only the odd reading as showing a watering, so these hold the
# last one seen, across restarts, rather than following the latest reading.
WATERING_DESCRIPTIONS: tuple[GeoDropsWateringSensorEntityDescription, ...] = (
    GeoDropsWateringSensorEntityDescription(
        key="last_watering",
        translation_key="last_watering",
        value_fn=lambda w: w.detected_at,
        device_class=SensorDeviceClass.TIMESTAMP,
    ),
    GeoDropsWateringSensorEntityDescription(
        key="watering_confidence",
        translation_key="watering_confidence",
        value_fn=lambda w: round(w.confidence * 100, 1),
        native_unit_of_measurement=PERCENTAGE,
        suggested_display_precision=0,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
)


class GeoDropsSensor(GeoDropsEntity, SensorEntity):
    """One value from a probe's latest reading."""

    entity_description: GeoDropsSensorEntityDescription

    @property
    def native_value(self) -> StateType | datetime:
        """Return the sensor's value from the latest reading."""
        r = self._reading
        if r is None:
            return None
        if self.entity_description.moisture_gated and r.all_training:
            return None
        return self.entity_description.value_fn(r)


class GeoDropsWateringSensor(GeoDropsEntity, RestoreEntity, SensorEntity):
    """One value of the last watering GeoDrops detected on a probe."""

    entity_description: GeoDropsWateringSensorEntityDescription
    _watering: Watering | None = None

    async def async_added_to_hass(self) -> None:
        """Restore the last watering, then catch up with the latest poll."""
        await super().async_added_to_hass()
        if (data := await self.async_get_last_extra_data()) is not None:
            self._watering = Watering.from_dict(data.as_dict())
        self._update_watering()

    @callback
    def _handle_coordinator_update(self) -> None:
        self._update_watering()
        super()._handle_coordinator_update()

    def _update_watering(self) -> None:
        """Take the poll's last watering if it is at least as new as the held one."""
        r = self._reading
        if (
            r is None
            or r.last_irrigation_at is None
            or r.last_irrigation_confidence is None
        ):
            return
        held = self._watering
        if held is None or r.last_irrigation_at >= held.detected_at:
            self._watering = Watering(
                r.last_irrigation_confidence, r.last_irrigation_at
            )

    @property
    def extra_restore_state_data(self) -> Watering | None:
        """Keep the last watering across restarts."""
        return self._watering

    @property
    def available(self) -> bool:
        """A watering already seen stays true while the probe is offline."""
        return self._watering is not None or super().available

    @property
    def native_value(self) -> StateType | datetime:
        """Return the value from the last watering seen."""
        if self._watering is None:
            return None
        return self.entity_description.value_fn(self._watering)


def build_sensors(
    coordinator: GeoDropsCoordinator, device: DeviceConfig
) -> list[GeoDropsSensor | GeoDropsWateringSensor]:
    """Create every sensor for one probe."""
    sensors: list[GeoDropsSensor | GeoDropsWateringSensor] = [
        GeoDropsSensor(coordinator, device, desc) for desc in SENSOR_DESCRIPTIONS
    ]
    sensors.extend(
        GeoDropsWateringSensor(coordinator, device, desc)
        for desc in WATERING_DESCRIPTIONS
    )
    return sensors


async def async_setup_entry(
    hass: HomeAssistant,
    entry: GeoDropsConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add the sensors for every configured probe."""
    coordinator = entry.runtime_data
    entities: list[GeoDropsSensor | GeoDropsWateringSensor] = []
    for device in coordinator.devices:
        entities.extend(build_sensors(coordinator, device))
    async_add_entities(entities)
