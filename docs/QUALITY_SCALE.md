# Quality scale

A self-assessment of the GeoDrops integration against the Home Assistant
[Integration Quality Scale](https://www.home-assistant.io/docs/quality_scale/)
([rule reference](https://developers.home-assistant.io/docs/core/integration-quality-scale/rules))
and the [development guidelines](https://developers.home-assistant.io/docs/development_guidelines/).

Assessed against v0.7.0, 2026-10-05.

> The quality scale is only formally awarded to core integrations. For a HACS
> integration this is a self-assessment, but every rule below is applicable
> and is what a core reviewer would check.

## Scorecard

| Tier | Rules | Done | Exempt | To do |
| --- | --- | --- | --- | --- |
| Bronze | 20 | 15 | 5 | 0 |
| Silver | 10 | 9 | 1 | 0 |
| Gold | 21 | 18 | 3 | 0 |
| Platinum | 3 | 3 | 0 | 0 |

Every tier is complete. Readings come through the async
[`aiogeodrops`](https://github.com/ajbaldwin/aiogeodrops) library on Home
Assistant's own HTTP session, the integration passes mypy with core's strict
settings, and CI enforces ruff with core's configuration and 100 % test
coverage. All of this shipped in 0.6.0; see [History](#history).

---

## Bronze

| Rule | Status | Notes |
| --- | --- | --- |
| action-setup | Exempt | No service actions. |
| appropriate-polling | Done | 20 min default, 5 min floor. See [core parity](#core-parity-notes) on the configurable interval. |
| brands | Done | `brand/` icons and logos. |
| common-modules | Done | Coordinator in `coordinator.py`, shared entity base in `entity.py`. |
| config-flow | Done | Every flow field has a `data_description`. |
| config-flow-test-coverage | Done | 100 % covered; every error test resubmits valid input and finishes the flow. |
| dependency-transparency | Done | [`aiogeodrops`](https://github.com/ajbaldwin/aiogeodrops) is MIT, published to PyPI from public CI with trusted publishing. |
| docs-actions | Exempt | No actions. |
| docs-conditions | Exempt | No conditions. |
| docs-triggers | Exempt | No triggers. |
| docs-high-level-description | Done | README "What it does". |
| docs-installation-instructions | Done | README "Prerequisites" and "Installation". |
| docs-removal-instructions | Done | README "Removing the integration". |
| entity-event-setup | Exempt | Entities only use `CoordinatorEntity`; no manual subscriptions. |
| entity-unique-id | Done | `{serial}_{suffix}`. |
| has-entity-name | Done | |
| runtime-data | Done | `GeoDropsConfigEntry = ConfigEntry[GeoDropsCoordinator]`. |
| test-before-configure | Done | `validate_access` runs a real zero-byte query. |
| test-before-setup | Done | `async_config_entry_first_refresh`; bad key raises `ConfigEntryAuthFailed`. |
| unique-config-entry | Done | Unique ID is the GCP project ID. |

## Silver

| Rule | Status | Notes |
| --- | --- | --- |
| action-exceptions | Exempt | No actions. |
| config-entry-unloading | Done | Unloads platforms and closes the client. |
| docs-configuration-parameters | Done | README "Advanced Options" table. |
| docs-installation-parameters | Done | Project ID and JSON key are described. |
| entity-unavailable | Done | Per-probe `available` from staleness and expiry. |
| integration-owner | Done | `@ajbaldwin`. |
| log-when-unavailable | Done | Coordinator logs failures once; staleness logs once per episode. |
| parallel-updates | Done | `PARALLEL_UPDATES = 0` in `sensor.py` and `binary_sensor.py`. |
| reauthentication-flow | Done | `reauth_confirm`. |
| test-coverage | Done | 100 %, enforced in CI with `--cov-fail-under=100`. |

## Gold

| Rule | Status | Notes |
| --- | --- | --- |
| devices | Done | One device per probe with serial and model. |
| diagnostics | Done | `diagnostics.py`; key and project id redacted, including from the last error. |
| discovery | Exempt | Cloud data source; nothing to discover on the network. |
| discovery-update-info | Exempt | Same. |
| docs-data-update | Done | README "Polling and cost", "Advanced Options" and the availability rules under "Sensors". |
| docs-examples | Done | README "Automation examples". |
| docs-known-limitations | Done | README "Known limitations". |
| docs-supported-devices | Done | README "Supported devices". |
| docs-supported-functions | Done | Sensor tables. |
| docs-troubleshooting | Done | README "Troubleshooting"; the repair issue links to it. |
| docs-use-cases | Done | README "Use cases". |
| dynamic-devices | Exempt | GeoDrops' table is public and shared; there is no per-account device list to watch. Probes are user-declared by serial. |
| entity-category | Done | Battery, Battery Status, Battery Voltage, Signal Strength, Cloud Upload Delay, Last Reading, Reading Quality, Reading Quality Depth 1–3, Probe Health, Next Action Codes, Watering Confidence and the Max Moisture Calibration, Max Moisture Recalibration and Hardware Status binary sensors are diagnostic. |
| entity-device-class | Done | Cloud Upload Delay is a duration. Battery Status is a battery binary sensor, so low-battery cards and blueprints find it. Avg. 7-Day Sun is hours per day, a rate, so it has none. |
| entity-disabled-by-default | Done | Battery Voltage, Signal Strength, Cloud Upload Delay, Avg. 7-Day Sun, Next Action Codes, Max Moisture Recalibration and Hardware Status, for newly added probes. Battery Status became enabled by default when it took over the battery warning; a one-time entry migration enables it on existing installs unless the user disabled it. Reading Quality Depth 1–3 stay enabled: irrigation integrations read their states, and a disabled entity has none. |
| entity-translations | Done | |
| exception-translations | Done | `exceptions` in `strings.json`; every raised HA exception uses a translation key. |
| icon-translations | Done | `icons.json` with state icons. |
| reconfiguration-flow | Done | |
| repair-issues | Done | A non-transient 403 raises an `access_denied` repair, cleared by the next successful poll or on entry removal. A probe whose nextAction has `ATT_DW_NEW` or `DW_RENEW` raises a per-probe `max_moisture_required` or `max_moisture_recalibration` repair, cleared when the code goes, the probe is removed, or the entry is removed. |
| stale-devices | Done | Options-flow removal, plus `async_remove_config_entry_device` for the device page. |

## Platinum

| Rule | Status | Notes |
| --- | --- | --- |
| async-dependency | Done | [`aiogeodrops`](https://github.com/ajbaldwin/aiogeodrops): async, aiohttp + PyJWT only. |
| inject-websession | Done | The client uses `async_get_clientsession(hass)`. |
| strict-typing | Done | `aiogeodrops` ships `py.typed` and passes `mypy --strict`. The integration is fully annotated and CI runs mypy with HA core's strict settings (`mypy.ini`). |

---

## Development-guidelines conformance

Not quality-scale rules, but a core reviewer blocks on them. Done:

- `ruff.toml` carries HA core's ruff configuration (2026.2), and CI runs
  `ruff check` and `ruff format --check`. Tests are exempt only from the
  docstring rules.
- Every public module, class and function has a docstring; comments are full
  sentences.
- Log messages don't name the integration; the logger name already does.
- Constants are alphabetical within their groups (`const.py`).
- Imports are at module level and sorted core-style.

## Core parity notes

- **Configurable poll interval.** Core reviewers do not accept a
  scan-interval option; users are pointed to disabling polling and calling
  `homeassistant.update_entity` from an automation. Fine for HACS; drop
  `scan_interval_minutes` only if core submission becomes a goal.
- **`quality_scale.yaml`.** Core tracks rule status in this file next to
  `manifest.json`. Adding one here would keep this document's status tables
  in machine-readable form. Run hassfest locally first to confirm it accepts
  the file for a custom integration.

## Possible next step: probes as config subentries

Config subentries would give each probe a native "Add probe" button, its own
reconfigure, and a delete that also removes its device and entities. That
would replace the add/remove menu in the options flow. It needs
`VERSION = 2` and an `async_migrate_entry` that moves `options["devices"]`
into subentries. Entity unique IDs are serial-based, so entities survive.
Not required for any tier; worth doing if the options flow grows.

## History

| Release | Content |
| --- | --- |
| 0.6.0-beta.4 | Bronze and Silver (#14), Gold (#15) |
| 0.6.0-beta.6 | Platinum: the `aiogeodrops` library (#19), strict typing (#21), development guidelines (#22) |
| 0.6.0 | All of the above, stable |
| 0.7.0 | New probe-health, battery and watering entities, assessed against the same rules |
