"""Base entity shared by the GeoDrops platforms."""

from __future__ import annotations

from datetime import timedelta

from aiogeodrops import DeviceReading

from homeassistant.helpers import area_registry as ar
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import EntityDescription
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from . import const
from .const import DeviceConfig
from .coordinator import GeoDropsCoordinator
from .transform import classify_staleness, data_age_hours


class GeoDropsEntity(CoordinatorEntity[GeoDropsCoordinator]):
    """One value from a probe's latest reading."""

    _attr_has_entity_name = True
    # Keep normal availability while the probe is inactive (Last Reading), so
    # a probe put back in the ground shows up as reporting.
    _available_when_inactive = False

    def __init__(
        self,
        coordinator: GeoDropsCoordinator,
        device: DeviceConfig,
        description: EntityDescription,
    ) -> None:
        """Create the entity for `description` on `device`'s probe."""
        super().__init__(coordinator)
        self.entity_description = description
        self._device = device
        serial = device[const.DEV_SERIAL]
        self._attr_unique_id = f"{serial}_{description.key}"
        device_info = DeviceInfo(
            identifiers={(const.DOMAIN, serial)},
            name=device[const.DEV_NAME],
            manufacturer="GeoDrops",
            model="GeoDrops Droplet",
            serial_number=serial,
        )
        area_id = device.get(const.DEV_AREA)
        if area_id:
            area = ar.async_get(coordinator.hass).async_get_area(area_id)
            if area is not None:
                device_info["suggested_area"] = area.name
        self._attr_device_info = device_info

    @property
    def _reading(self) -> DeviceReading | None:
        """The probe's latest reading."""
        return self.coordinator.reading(self._device[const.DEV_ID])

    @property
    def _active(self) -> bool:
        """Whether the probe is in service, per the entry's current options.

        Not read from `self._device`: that copy is stale after a toggle.
        """
        return self.coordinator.is_active(self._device[const.DEV_SERIAL])

    @property
    def available(self) -> bool:
        """Return False when the probe is inactive, or its data is missing or old."""
        if not self._active and not self._available_when_inactive:
            return False
        r = self._reading
        if r is None:
            return False
        options = self.coordinator.config_entry.options
        skip: int = options.get(const.CONF_SKIP_HOURS, const.DEFAULT_SKIP_HOURS)
        warn: int = options.get(const.CONF_WARN_HOURS, const.DEFAULT_WARN_HOURS)
        age = data_age_hours(r, dt_util.utcnow())
        if age is not None and classify_staleness(age, warn, skip) == "skip":
            return False
        expire: int = options.get(
            const.CONF_EXPIRE_MINUTES, const.DEFAULT_EXPIRE_MINUTES
        )
        last = self.coordinator.reading_time(self._device[const.DEV_ID])
        if last is None or dt_util.utcnow() - last > timedelta(minutes=expire):
            return False
        return True
