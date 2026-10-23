"""GeoDrops switches: 1 per probe."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity, SwitchEntityDescription
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import const
from .coordinator import GeoDropsConfigEntry
from .entity import GeoDropsEntity

# The coordinator does all fetching, so entity updates need no limit.
PARALLEL_UPDATES = 0

# `key` is the unique-id suffix: never change it (entities would be re-created).
ACTIVE_DESCRIPTION = SwitchEntityDescription(
    key="active",
    translation_key="active",
    entity_category=EntityCategory.CONFIG,
)


class GeoDropsActiveSwitch(GeoDropsEntity, SwitchEntity):
    """Whether the probe is in service.

    Off silences the probe's repairs and blanks its sensors (bar Last Reading),
    for a probe taken out for the season. It is still polled.
    """

    @property
    def available(self) -> bool:
        """Stay available, whatever the probe's data, so it can be switched back on."""
        return True

    @property
    def is_on(self) -> bool:
        """Return whether the probe is active."""
        return self._active

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Put the probe back in service."""
        self.coordinator.set_active(self._device[const.DEV_SERIAL], True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Take the probe out of service."""
        self.coordinator.set_active(self._device[const.DEV_SERIAL], False)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: GeoDropsConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add the Active switch for every configured probe."""
    coordinator = entry.runtime_data
    async_add_entities(
        GeoDropsActiveSwitch(coordinator, device, ACTIVE_DESCRIPTION)
        for device in coordinator.devices
    )
