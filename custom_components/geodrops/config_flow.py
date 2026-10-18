"""Config and options flows for GeoDrops."""

from __future__ import annotations

from collections.abc import Mapping
import logging
from typing import Any

from aiogeodrops import (
    GeoDropsAuthError,
    GeoDropsClient,
    GeoDropsCredentialsError,
    GeoDropsError,
)
import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlowWithReload,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    AreaSelector,
    TextSelector,
    TextSelectorConfig,
)

from . import const
from .const import DeviceConfig

_LOGGER = logging.getLogger(__name__)

# Advanced Options: (key, default, min, max). The minimum poll interval keeps
# a typo from querying BigQuery back-to-back.
_SETTINGS: list[tuple[str, int, int, int]] = [
    (const.CONF_SCAN_INTERVAL, const.DEFAULT_SCAN_INTERVAL, 5, 1440),
    (
        const.CONF_LOOKBACK_HOURS,
        const.DEFAULT_LOOKBACK_HOURS,
        1,
        const.MAX_LOOKBACK_HOURS,
    ),
    (const.CONF_WARN_HOURS, const.DEFAULT_WARN_HOURS, 1, 168),
    (const.CONF_SKIP_HOURS, const.DEFAULT_SKIP_HOURS, 1, 168),
    (const.CONF_EXPIRE_MINUTES, const.DEFAULT_EXPIRE_MINUTES, 5, 10080),
]


class _FlowError(Exception):
    """A check failed; `key` is the form's error key."""

    def __init__(self, key: str) -> None:
        super().__init__(key)
        self.key = key


def _credentials_field() -> TextSelector:
    """Return a multi-line field for pasting a JSON key."""
    return TextSelector(TextSelectorConfig(multiline=True))


def _device_schema() -> vol.Schema:
    """Return the add-probe form."""
    return vol.Schema(
        {
            vol.Required(const.DEV_SERIAL): str,
            vol.Required(const.DEV_NAME): str,
            vol.Optional(const.DEV_AREA): AreaSelector(),
        }
    )


def _new_device(
    user_input: dict[str, Any], serial: str, device_id: int
) -> DeviceConfig:
    """Build the stored config for a probe from the add-probe form."""
    device: DeviceConfig = {
        const.DEV_SERIAL: serial,
        const.DEV_ID: device_id,
        const.DEV_NAME: user_input[const.DEV_NAME],
    }
    if user_input.get(const.DEV_AREA):
        device[const.DEV_AREA] = user_input[const.DEV_AREA]
    return device


def _client(
    hass: HomeAssistant, project_id: str, credentials_json: str
) -> GeoDropsClient:
    """Create a client on Home Assistant's shared HTTP session."""
    return GeoDropsClient(async_get_clientsession(hass), project_id, credentials_json)


async def _validate_credentials(
    hass: HomeAssistant, project_id: str, credentials_json: str
) -> None:
    """Build a client and prove it can query. Raises _FlowError."""
    try:
        await _client(hass, project_id, credentials_json).validate_access()
    except GeoDropsCredentialsError as err:
        raise _FlowError("invalid_credentials") from err
    except GeoDropsAuthError as err:
        raise _FlowError("invalid_auth") from err
    except GeoDropsError as err:
        raise _FlowError("cannot_connect") from err
    except Exception as err:
        _LOGGER.exception("Unexpected error checking the service-account key")
        raise _FlowError("unknown") from err


async def _lookup_device_id(
    hass: HomeAssistant,
    project_id: str,
    credentials_json: str,
    serial: str,
    lookback_hours: int = const.DEFAULT_LOOKBACK_HOURS,
) -> int:
    """Find a probe's GeoDrops device id by serial. Raises _FlowError."""
    try:
        reading = await _client(hass, project_id, credentials_json).lookup_serial(
            serial, lookback_hours
        )
    except GeoDropsCredentialsError as err:
        raise _FlowError("invalid_credentials") from err
    except GeoDropsAuthError as err:
        raise _FlowError("invalid_auth") from err
    except GeoDropsError as err:
        raise _FlowError("cannot_connect") from err
    except Exception as err:
        _LOGGER.exception("Unexpected error looking up probe %s", serial)
        raise _FlowError("unknown") from err
    if reading is None:
        raise _FlowError("device_not_found")
    return reading.device_id


class GeoDropsConfigFlow(ConfigFlow, domain=const.DOMAIN):
    """Set up GeoDrops: a GCP project and key, then the first probe."""

    VERSION = 1

    def __init__(self) -> None:
        """Start with no project or key; the user step sets them."""
        self._project_id = ""
        self._credentials_json = ""

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for the GCP project and key, and check they can query."""
        errors: dict[str, str] = {}
        if user_input is not None:
            project_id = user_input[const.CONF_PROJECT_ID].strip()
            await self.async_set_unique_id(project_id)
            self._abort_if_unique_id_configured()
            try:
                await _validate_credentials(
                    self.hass, project_id, user_input[const.CONF_CREDENTIALS_JSON]
                )
            except _FlowError as err:
                errors["base"] = err.key
            else:
                self._project_id = project_id
                self._credentials_json = user_input[const.CONF_CREDENTIALS_JSON]
                return await self.async_step_add_device()
        schema = vol.Schema(
            {
                vol.Required(const.CONF_PROJECT_ID): str,
                vol.Required(const.CONF_CREDENTIALS_JSON): _credentials_field(),
            }
        )
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)

    async def async_step_add_device(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for the first probe and create the entry."""
        errors: dict[str, str] = {}
        if user_input is not None:
            serial = user_input[const.DEV_SERIAL].strip().upper()
            try:
                device_id = await self._lookup_first_device(serial)
            except _FlowError as err:
                errors["base"] = err.key
            else:
                # Another flow may have added this project meanwhile.
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title="GeoDrops",
                    data={
                        const.CONF_PROJECT_ID: self._project_id,
                        const.CONF_CREDENTIALS_JSON: self._credentials_json,
                    },
                    options={
                        const.CONF_DEVICES: [_new_device(user_input, serial, device_id)]
                    },
                )
        return self.async_show_form(
            step_id="add_device", data_schema=_device_schema(), errors=errors
        )

    async def _lookup_first_device(self, serial: str) -> int:
        """Find the first probe's device id. Raises _FlowError.

        There is no lookback setting yet, so search the default window, then
        the longest one the options allow. Most probes report within the
        default, so the wider (costlier) query rarely runs.
        """
        try:
            return await _lookup_device_id(
                self.hass, self._project_id, self._credentials_json, serial
            )
        except _FlowError as err:
            if err.key != "device_not_found":
                raise
        return await _lookup_device_id(
            self.hass,
            self._project_id,
            self._credentials_json,
            serial,
            const.MAX_LOOKBACK_HOURS,
        )

    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> ConfigFlowResult:
        """Start re-authentication after Google rejected the stored key."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Replace a service-account key that Google has stopped accepting."""
        errors: dict[str, str] = {}
        entry = self._get_reauth_entry()
        project_id: str = entry.data[const.CONF_PROJECT_ID]
        if user_input is not None:
            credentials_json = user_input[const.CONF_CREDENTIALS_JSON]
            try:
                await _validate_credentials(self.hass, project_id, credentials_json)
            except _FlowError as err:
                errors["base"] = err.key
            else:
                return self.async_update_reload_and_abort(
                    entry, data_updates={const.CONF_CREDENTIALS_JSON: credentials_json}
                )
        schema = vol.Schema(
            {vol.Required(const.CONF_CREDENTIALS_JSON): _credentials_field()}
        )
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=schema,
            errors=errors,
            description_placeholders={"project_id": project_id},
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Change the GCP project and/or rotate the key without re-adding probes."""
        errors: dict[str, str] = {}
        entry = self._get_reconfigure_entry()
        current_project = entry.data[const.CONF_PROJECT_ID]
        if user_input is not None:
            project_id = user_input[const.CONF_PROJECT_ID].strip()
            # A blank key field keeps the stored key.
            credentials_json: str = (
                user_input.get(const.CONF_CREDENTIALS_JSON) or ""
            ).strip() or entry.data[const.CONF_CREDENTIALS_JSON]
            if project_id != current_project:
                await self.async_set_unique_id(project_id)
                self._abort_if_unique_id_configured()
            try:
                await _validate_credentials(self.hass, project_id, credentials_json)
            except _FlowError as err:
                errors["base"] = err.key
            else:
                return self.async_update_reload_and_abort(
                    entry,
                    unique_id=project_id,
                    data_updates={
                        const.CONF_PROJECT_ID: project_id,
                        const.CONF_CREDENTIALS_JSON: credentials_json,
                    },
                )
        schema = vol.Schema(
            {
                vol.Required(const.CONF_PROJECT_ID, default=current_project): str,
                vol.Optional(const.CONF_CREDENTIALS_JSON): _credentials_field(),
            }
        )
        return self.async_show_form(
            step_id="reconfigure", data_schema=schema, errors=errors
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> GeoDropsOptionsFlow:
        """Return the options flow."""
        return GeoDropsOptionsFlow()


class GeoDropsOptionsFlow(OptionsFlowWithReload):
    """Add or remove probes, and change the Advanced Options."""

    def _devices(self) -> list[DeviceConfig]:
        """Return a copy of the configured probes."""
        devices: list[DeviceConfig] = self.config_entry.options.get(
            const.CONF_DEVICES, []
        )
        return list(devices)

    def _save(self, options: dict[str, Any]) -> ConfigFlowResult:
        """Save the options; the entry then reloads."""
        return self.async_create_entry(title="", data=options)

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show the options menu."""
        return self.async_show_menu(
            step_id="init",
            menu_options=["add_device", "remove_device", "settings"],
        )

    async def async_step_add_device(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Add a probe by serial."""
        errors: dict[str, str] = {}
        if user_input is not None:
            serial = user_input[const.DEV_SERIAL].strip().upper()
            devices = self._devices()
            if any(d[const.DEV_SERIAL] == serial for d in devices):
                errors["base"] = "duplicate_device"
            else:
                data = self.config_entry.data
                try:
                    device_id = await _lookup_device_id(
                        self.hass,
                        data[const.CONF_PROJECT_ID],
                        data[const.CONF_CREDENTIALS_JSON],
                        serial,
                        self.config_entry.options.get(
                            const.CONF_LOOKBACK_HOURS, const.DEFAULT_LOOKBACK_HOURS
                        ),
                    )
                except _FlowError as err:
                    errors["base"] = err.key
                else:
                    devices.append(_new_device(user_input, serial, device_id))
                    return self._save(
                        {**self.config_entry.options, const.CONF_DEVICES: devices}
                    )
        return self.async_show_form(
            step_id="add_device", data_schema=_device_schema(), errors=errors
        )

    async def async_step_remove_device(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Remove a probe and its device."""
        devices = self._devices()
        if not devices:
            return self.async_abort(reason="no_devices")
        if user_input is not None:
            serial = user_input["device"]
            remaining = [d for d in devices if d[const.DEV_SERIAL] != serial]
            registry = dr.async_get(self.hass)
            # async_get_device is deprecated; scope the lookup to this entry instead.
            for device in dr.async_entries_for_config_entry(
                registry, self.config_entry.entry_id
            ):
                if (const.DOMAIN, serial) in device.identifiers:
                    registry.async_remove_device(device.id)
            options = {**self.config_entry.options, const.CONF_DEVICES: remaining}
            return self._save(options)
        choices = {
            d[const.DEV_SERIAL]: f"{d[const.DEV_NAME]} ({d[const.DEV_SERIAL]})"
            for d in devices
        }
        schema = vol.Schema({vol.Required("device"): vol.In(choices)})
        return self.async_show_form(step_id="remove_device", data_schema=schema)

    async def async_step_settings(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Change the Advanced Options."""
        errors: dict[str, str] = {}
        if user_input is not None:
            if user_input[const.CONF_WARN_HOURS] > user_input[const.CONF_SKIP_HOURS]:
                errors[const.CONF_WARN_HOURS] = "warn_above_skip"
            if (
                user_input[const.CONF_EXPIRE_MINUTES]
                <= user_input[const.CONF_SCAN_INTERVAL]
            ):
                # Sensors would go unavailable between every pair of polls.
                errors[const.CONF_EXPIRE_MINUTES] = "expire_below_interval"
            if not errors:
                return self._save({**self.config_entry.options, **user_input})
        values: Mapping[str, Any] = user_input or self.config_entry.options
        schema = vol.Schema(
            {
                vol.Required(key, default=values.get(key, default)): vol.All(
                    int, vol.Range(min=low, max=high)
                )
                for key, default, low, high in _SETTINGS
            }
        )
        return self.async_show_form(
            step_id="settings", data_schema=schema, errors=errors
        )
