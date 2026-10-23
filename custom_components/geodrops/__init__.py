"""The GeoDrops integration."""

from __future__ import annotations

from aiogeodrops import GeoDropsClient, GeoDropsCredentialsError

from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from . import const
from .const import DeviceConfig
from .coordinator import GeoDropsConfigEntry, GeoDropsCoordinator, delete_entry_issues

PLATFORMS = [Platform.BINARY_SENSOR, Platform.SENSOR, Platform.SWITCH]


async def async_setup_entry(hass: HomeAssistant, entry: GeoDropsConfigEntry) -> bool:
    """Set up GeoDrops from a config entry."""
    try:
        client = GeoDropsClient(
            async_get_clientsession(hass),
            entry.data[const.CONF_PROJECT_ID],
            entry.data[const.CONF_CREDENTIALS_JSON],
        )
    except GeoDropsCredentialsError as err:
        # The stored key can't even be parsed, so retrying won't fix it.
        raise ConfigEntryAuthFailed(
            translation_domain=const.DOMAIN,
            translation_key="invalid_credentials",
            translation_placeholders={"error": str(err)},
        ) from err

    coordinator = GeoDropsCoordinator(hass, entry, client)
    await coordinator.async_config_entry_first_refresh()

    # Options changes reload through the options flow (OptionsFlowWithReload)
    # and key/project changes through async_update_reload_and_abort, so no
    # update listener: one would reload a second time.
    entry.runtime_data = coordinator
    entry.async_on_unload(
        hass.bus.async_listen(
            dr.EVENT_DEVICE_REGISTRY_UPDATED, coordinator.async_device_updated
        )
    )
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_migrate_entry(hass: HomeAssistant, entry: GeoDropsConfigEntry) -> bool:
    """Migrate an entry from an older version of the integration."""
    if entry.version > 1:
        return False
    if entry.minor_version < 2:
        # Battery Status was disabled by default; now it is the battery warning,
        # so turn it on once for existing installs. One the user disabled stays so.
        # Home Assistant reloads the entry about 30 s later to add the entity.
        registry = er.async_get(hass)
        for entity in er.async_entries_for_config_entry(registry, entry.entry_id):
            if (
                entity.unique_id.endswith("_battery_poor")
                and entity.disabled_by is er.RegistryEntryDisabler.INTEGRATION
            ):
                registry.async_update_entity(entity.entity_id, disabled_by=None)
        hass.config_entries.async_update_entry(entry, minor_version=2)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: GeoDropsConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_remove_entry(hass: HomeAssistant, entry: GeoDropsConfigEntry) -> None:
    """Clear the entry's repair issues when the entry is deleted."""
    delete_entry_issues(hass, entry.entry_id)


async def async_remove_config_entry_device(
    hass: HomeAssistant, entry: GeoDropsConfigEntry, device_entry: dr.DeviceEntry
) -> bool:
    """Let the user delete a probe from its device page.

    Probes are only ever added by the user, so there is no way to tell a dead
    probe from a quiet one; removal is theirs to decide. Dropping it from the
    options keeps it from coming back on the next reload.
    """
    serials = {
        ident for domain, ident in device_entry.identifiers if domain == const.DOMAIN
    }
    devices: list[DeviceConfig] = entry.options.get(const.CONF_DEVICES, [])
    remaining = [d for d in devices if d[const.DEV_SERIAL] not in serials]
    if len(remaining) != len(devices):
        hass.config_entries.async_update_entry(
            entry, options={**entry.options, const.CONF_DEVICES: remaining}
        )
    return True
