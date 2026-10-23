# Changelog

## 0.9.0-beta.4 — Battery warning
**New**
- **Battery Status now warns before a probe's batteries run out**, judging from how fast the probe's own voltage is falling rather than GeoDrops' flag, which only fired once the batteries had already failed.
- **A probe whose batteries are about to fail shows in Repairs**, and the repair clears on its own within about two days of fresh batteries going in.

**Changed**
- **Battery Status is now enabled by default and shows Low or Normal**; existing installs get it turned on once, unless you turned it off yourself.

No new entities. Home Assistant reloads the integration once, about 30 seconds after the update, to turn Battery Status on.

## 0.9.0-beta.3 — Seasonal probe removal
**New**
- **Each probe has an Active switch** on its device page: turn it off while a probe is out of the ground, and it raises no repairs and its sensors show as unavailable, except Last Reading.
- **Probes whose device you disable in Home Assistant are no longer polled** and their repairs clear straight away.

One new switch per probe, on by default; nothing changes until you turn one off.

## 0.9.0-beta.2 — Safer logs
**Fixed**
- **Errors in the Home Assistant log no longer show your GCP project or service-account email**, so a log is safe to paste into a GitHub issue.

No entity changes.

## 0.9.0-beta.1 — Offline probe alerts
**New**
- **A probe that stops reporting shows in Repairs** once its latest reading is more than 24 hours old (set under Advanced Options → "Offline alert after"), and clears on its own when it reports again.
- **When every probe stops at once, one "GeoDrops data is delayed" repair** appears instead, since the cause is usually on GeoDrops' side.

**Fixed**
- **Last Reading and Last Detected Watering no longer show a time in the future** for readings uploaded partway through GeoDrops' half-hour slot.
- **A probe no longer briefly shows an older reading** while GeoDrops refreshes its data.
- **Removing a probe keeps working on future Home Assistant versions**, which drop an API it used.

No entity changes; the new alert uses its 24-hour default until you change it.

## 0.8.0 — Calibration repairs
Everything since 0.7.0. If you ran the 0.8.0 beta, nothing has changed since beta.1.

**New**
- **Probes that need their max-moisture calibration show in Repairs**, for a new probe's first test and for the retest GeoDrops asks for every 75 days. Each clears on its own once GeoDrops has the calibration.

**Changed**
- **A probe goes unavailable based only on when its latest reading was taken**, as GeoDrops recommends, so a bad upload-delay value from GeoDrops can no longer push it there early.
- **Wick Status is now Max Moisture Recalibration**, because GeoDrops' code means the calibration has expired, not that a wick needs replacing.
- **Probe Health's `wick_renewal_needed` state is now `recalibration_due`** (shown as Recalibration Due).
- **Sync Delay is now called Cloud Upload Delay**, since it shows the upload delay GeoDrops reports, not how old the data is.

Entity ids are unchanged; update any automation that compares Probe Health against `wick_renewal_needed`.

## 0.8.0-beta.1 — Calibration repairs
**New**
- **Probes that need their max-moisture calibration show in Repairs**, for a new probe's first test and for the retest GeoDrops asks for every 75 days. Each clears on its own once GeoDrops has the calibration.

**Changed**
- **Wick Status is now Max Moisture Recalibration**, because GeoDrops' code means the calibration has expired, not that a wick needs replacing.
- **Probe Health's `wick_renewal_needed` state is now `recalibration_due`** (shown as Recalibration Due).
- **Sync Delay is now called Cloud Upload Delay**, since it shows the upload delay GeoDrops reports, not how old the data is.

Entity ids are unchanged; update any automation that compares Probe Health against `wick_renewal_needed`.

## 0.7.1-beta.1 — Staleness from the reading's own time
**Changed**
- **A probe goes unavailable based only on when its latest reading was taken**, as GeoDrops recommends, so a bad Sync Delay value from GeoDrops can no longer push it there early.
- **Sync Delay is described as GeoDrops defines it**: how long a reading took to reach GeoDrops' cloud after the probe recorded it.

## 0.7.0 — Probe health, battery alerts, and watering detection
Everything since 0.6.0. If you ran the 0.7.0 betas, the only change since beta.5 is that "Warn after" now defaults to 12 hours.

**New**
- **Probe Health** is a diagnostic sensor that shows what a probe needs, read from GeoDrops' action codes: OK, Calibrating, Max Moisture Required, Wick Renewal Needed, Hardware Check or Error.
- **Battery Status, Max Moisture Calibration, Wick Status and Hardware Status** are diagnostic binary sensors that show Problem when GeoDrops flags that issue, so you can be alerted before a probe goes quiet. Battery Status, Wick Status and Hardware Status start disabled on probes you add from now on.
- **Last Detected Watering and Watering Confidence** show when GeoDrops last detected a watering on the probe and how confident it was. Both keep their value across restarts.
- **Reading Quality** is a diagnostic sensor with GeoDrops' overall reading quality, alongside Reading Quality Depth 1–3.
- **Battery Voltage and Signal Strength** are diagnostic sensors that start disabled; enable them from the device page if you want them.
- **Next Action Codes** lists GeoDrops' raw action codes, including ones Probe Health doesn't recognize. It starts disabled.

**Changed**
- **"Warn after" now defaults to 12 hours** (was 6), so the log warning for a quiet probe comes later. A value you saved is kept.
- **A GeoDrops table change no longer takes every sensor down.** Only the sensors that use a missing column go unknown, and a log warning names the column.
- **Avg. 7-Day Sun starts disabled on probes you add from now on.** Existing probes keep it as it is.

**Fixed**
- **Adding a probe searches your lookback setting**, and setting up the integration finds a first probe that reported in the last 7 days, instead of only the last 12 hours.

Each probe now has 27 entities instead of 16; the new ones are listed under *Diagnostic* on the device page. Entity ids of existing sensors are unchanged, so there is nothing to change on your side.

## 0.7.0-beta.5 — Clearer names
**Changed**
- **Quality is now called Reading Quality** (including Depth 1–3), and **Status is now called Probe Health**. Existing entity ids are unchanged.
- **Watering Confidence moves to the Diagnostic section** on the device page.

**Fixed**
- **Setting up the integration now finds a first probe that reported in the last 7 days**, not just the last 12 hours.

Nothing to change on your side.

## 0.7.0-beta.4 — Quieter defaults
**Changed**
- **Max Moisture Status is now called Max Moisture Calibration.** Its entity id is unchanged.
- **Battery Status, Wick Status and Hardware Status start disabled** on probes you add from now on. Status already covers wick and hardware problems.

**Fixed**
- **Adding a probe now searches your lookback setting**, not just the last 12 hours.

Nothing to change on your side.

## 0.7.0-beta.3 — Last detected watering
**New**
- **Last Detected Watering** and **Watering Confidence** sensors: when GeoDrops last detected a watering on the probe, and how confident it was. Both keep their value across restarts.

Each probe now has 27 entities. Nothing to change on your side.

## 0.7.0-beta.2 — Probe status and maintenance alerts
**New**
- **Status** is a new diagnostic sensor that shows what a probe needs, read from GeoDrops' action codes: OK, Calibrating, Max Moisture Required, Wick Renewal Needed, Hardware Check or Error. When a probe has several, it shows the most urgent.
- **Max Moisture Status**, **Wick Status** and **Hardware Status** are new diagnostic binary sensors, on by default. Each shows Problem when GeoDrops asks you to run the max-moisture (deep water) test in its app, replace the probe's wick, or check its hardware. Max Moisture Status explains a probe whose moisture stays `unknown`: it clears once you run the test.
- **Quality** is a new diagnostic sensor: GeoDrops' overall reading quality, alongside Quality Depth 1–3.
- **Next Action Codes** is a new diagnostic sensor that starts disabled. It lists GeoDrops' raw action codes, including ones Status doesn't recognize. Enable it from the device page if you want it.

**Changed**
- **Battery Problem is now called Battery Status**, so it reads "Battery Status: OK" instead of "Battery Problem: OK". Its entity id and history are unchanged.

**Nothing to change on your side.** Each probe now has 25 entities instead of 19; the 6 new ones are listed under *Diagnostic* on the device page. GeoDrops doesn't document its action codes: their meanings come from comparing them with readings across GeoDrops' probes.

## 0.7.0-beta.1 — Battery health, signal strength, and sturdier queries
**New**
- **Battery Problem** is a new diagnostic binary sensor, on by default. It turns on when GeoDrops flags a probe's battery as poor quality, so you can be alerted before the battery dies.
- **Battery Voltage** (mV) and **Signal Strength** (dBm) are new diagnostic sensors. They start disabled on every probe, including existing ones; enable them from the device page if you want them.

**Changed**
- **Avg. 7-Day Sun now starts disabled on probes you add from now on.** Existing probes keep it as it is.
- **A GeoDrops table change no longer takes every sensor down.** GeoDrops has renamed and dropped columns in its data before, and one such change used to make every query fail. Now only the sensors that use a missing column go unknown, and the rest keep working. A warning in the log names the missing columns. This comes from aiogeodrops 0.2.0, which checks which columns GeoDrops' table has before each query; that check scans no data and costs nothing.

**Nothing to change on your side.** Each probe now has 19 entities instead of 16; the 3 new ones are listed under *Diagnostic* on the device page.

## 0.6.0 — Re-authentication, steadier sensors, and a lighter install
Everything since 0.5.1. If you ran the 0.6.0 betas, the only change since beta.7 is the version number.

**⚠️ Before you update**
- **Using [GeoDrops Rachio Irrigation](https://github.com/ajbaldwin/ha-geodrops-rachio-irrigation)? Update it to v1.2.0 or later first.** v1.1.0 and earlier can't read the new Moisture State and Quality states below: they treat every zone as low quality and water nothing. Don't roll it back below v1.2.0 after installing this version.
- **Update automations that check Moisture State or Quality.** These sensors now report stable keys (`moist_plus`, `good`, `training`, …) that the UI still shows as "Moist+", "Good", "Training". Automations and templates comparing against the old text stop matching; the README's "States for automations" table lists every state. An unclassified value is now Home Assistant's own `unknown`.
- **Some sensors move off auto-generated dashboards.** Battery, Sync Delay, Last Reading and Quality Depth 1–3 are now *Diagnostic* sensors: they're listed under *Diagnostic* on the device page and drop off auto-generated dashboards. Entity ids and history are unchanged; add them to a card by hand if you want them there.

**Fixing a broken key**
- **Re-authenticate instead of starting over.** If Google stops accepting your service-account key (deleted, revoked, or its service account disabled), GeoDrops asks you to re-authenticate on the Devices & Services page. Paste a new key and your probes and settings stay as they were.
- **Reconfigure.** Change the GCP project or rotate the key any time from the integration's ⋮ menu → Reconfigure. Leave the key blank to keep the current one.
- **GCP permission problems show in Repairs.** A missing BigQuery role or a disabled BigQuery API raises an issue under Settings → Repairs, linked to the README's troubleshooting section. It clears on its own after the next successful poll.

**Sensors that stay up, and go down when they should**
- **No more twice-daily "unavailable" blips.** About twice a day GeoDrops' data briefly comes back empty. Each probe now keeps its last reading through that, and goes unavailable only when its own data hasn't arrived for longer than "Expire after".
- **"Expire after" defaults to 80 minutes** (was 45), so sensors ride out three missed polls instead of two. A value you saved under Advanced Options is kept.
- **Google hiccups don't need you.** Outages, rate limits and network drops no longer ask you to re-authenticate; the next poll tries again. Each query gives up after about 60 seconds instead of retrying for up to 40 minutes, so setup fails fast with a clear error during an outage.
- **Quiet probes are caught.** A probe goes unavailable once its latest reading is older than "Mark unavailable after", even while GeoDrops keeps serving that same old reading. "Warn after" writes one warning to the log, and a note when the probe reports again.
- **A bad sync delay no longer blanks a probe.** GeoDrops has reported a sync delay of about 2,053 hours on readings only an hour old. A sync delay more than 3 hours longer than the reading's own age is now ignored, and Sync Delay shows `unknown` for it.
- **Missing values show as unknown, not 0.** A probe that doesn't report a temperature or battery no longer shows 0 °C / 0 %, which could trigger frost or low-battery automations.

**New**
- **Last Reading sensor** shows when each probe last took a reading, so each probe now has 16 sensors.
- **Download diagnostics** from the integration's ⋮ menu, for bug reports. The key, the service account's email and your project ids are redacted.
- **Delete a probe from its device page.** Deleting the device also removes the probe from the integration, so it isn't recreated on the next poll.
- **Sync Delay starts disabled on probes you add from now on.** Existing probes keep it as it is; enable it from the device page if you want it.

**Smaller and cleaner**
- **Lighter install, and no grpcio warning from GeoDrops.** GeoDrops reads BigQuery through its own small library, [aiogeodrops](https://github.com/ajbaldwin/aiogeodrops), instead of Google's BigQuery SDK. That removes grpcio, protobuf and the rest of the SDK, along with the "grpcio < 1.83.0 does not support Post-Quantum Cryptography" warning. Polls run on Home Assistant's own event loop instead of a worker thread.
- **Forms check their values and explain errors.** Every field has help text. The poll interval is at least 5 minutes, "Warn after" can't exceed "Mark unavailable after", and "Expire after" must be longer than the poll interval. Pasting JSON that isn't a key file says so, and an unexpected error leaves the form open so you can try again.
- **The README is corrected about the key.** It said Home Assistant stores the key encrypted; it doesn't. Config entries are plain text in `/config/.storage` and in backups. The README now says so, and suggests deleting the downloaded key file and setting a daily BigQuery quota.
- **Docs.** The README gains an Advanced Options reference, automation examples, known limitations, troubleshooting, and removal instructions.

## 0.6.0-beta.7 — Probes no longer blanked by a bad sync delay
- **A probe stays available when GeoDrops reports an impossible sync delay.** GeoDrops' data gave one probe a sync delay of about 2,053 hours (85 days) on readings only an hour old, while the probe kept reporting every 30 minutes. GeoDrops took that at face value and marked all of the probe's sensors unavailable for 6 hours. A sync delay more than 3 hours longer than the reading's own age is now treated as bad data: the probe's age is judged from when the reading was taken instead, and its sensors stay available.
- **Sync Delay shows `unknown` for such a value**, instead of a spike of thousands of hours in its history.
- **Nothing to change on your side.** Poll interval, "Mark unavailable after" and "Expire after" work as before.

## 0.6.0-beta.6 — A lighter, native BigQuery connection
- **Smaller install, and no more grpcio warning from GeoDrops.** GeoDrops now reads BigQuery through its own small library, [aiogeodrops](https://github.com/ajbaldwin/aiogeodrops), instead of Google's BigQuery SDK. That removes grpcio, protobuf and the rest of the SDK from what GeoDrops installs, so the "grpcio < 1.83.0 does not support Post-Quantum Cryptography" warning no longer comes from GeoDrops. Polls also run on Home Assistant's own event loop and HTTP connection instead of a worker thread.
- **Nothing to change on your side.** Sensors, entity IDs, states, options and your stored key are all unchanged. Before this release, readings from the new connection were compared with beta.5 on a live install, and every value matched.
- **Setup survives unexpected errors.** An unexpected error while checking a key or looking up a probe used to end the setup form. Now the form stays open, says to check the log (where the details are), and you can try again.
- **Diagnostics hide more.** Downloaded diagnostics now also redact the service account's email and the project the key was created in, not just the project queries run in.
- **Keeping the key safe.** The README said Home Assistant stores the key encrypted. It doesn't: config entries are kept in plain text in `/config/.storage` and included in backups. The README now says so, and suggests deleting the downloaded key file and setting a daily BigQuery quota to cap the cost if a key ever leaks.
- **Log wording.** The "has not reported for … hours" and "is reporting again" log messages start with "Probe" instead of "GeoDrops probe"; the log line already names the integration.

## 0.6.0-beta.5 — Quality sensors stay on
- **Quality sensors stay enabled on new probes.** beta.4 created Quality Depth 1–3 disabled on newly added probes. A disabled sensor has no state at all, not just a hidden one, so irrigation schedulers and other integrations that check these sensors to decide whether a moisture reading can be trusted would have treated the probe as unreliable. They are enabled again and stay under *Diagnostic* on the device page. Only Sync Delay is disabled by default.

## 0.6.0-beta.4 — Diagnostics, Repairs, and a tidier device page
- **Technical sensors move to the Diagnostic section.** Battery, Sync Delay, Last Reading and Quality Depth 1–3 now appear under *Diagnostic* on the device page and drop off auto-generated dashboards. They keep their entity ids and history; add them to a dashboard card by hand if you want them there.
- **New probes start leaner.** Sync Delay and Quality Depth 1–3 are disabled by default on probes you add from now on. Existing probes keep these sensors as they are. Enable them from the device page if you need them.
- **GCP permission problems show in Repairs.** A missing BigQuery role or a disabled BigQuery API now raises an issue under Settings → Repairs, linked to the README's troubleshooting section. It clears on its own after the next successful poll.
- **Download diagnostics.** The integration's ⋮ menu → Download diagnostics saves settings, poll status, and each probe's last reading for bug reports. The service-account key and project id are redacted.
- **Delete a probe from its device page.** Deleting the device also removes the probe from the integration, so it isn't recreated on the next poll.
- **Clearer forms and errors.** Every setup, add-probe, re-authenticate and reconfigure field has help text, and error messages are translated.
- **Docs.** The README gains an Advanced Options reference, automation examples, known limitations, troubleshooting, and removal instructions.

## 0.6.0-beta.3 — Translated states, a Last Reading sensor, safer settings
- **⚠️ Update automations that check Moisture State or Quality.** These sensors now report stable keys (`moist_plus`, `good`, `training`, …) that the UI still shows as "Moist+", "Good", "Training". Automations and templates comparing against the old text stop matching; the README's "States for automations" table lists every state. An unclassified value is now Home Assistant's own `unknown`.
- **New Last Reading sensor** shows when each probe last took a reading.
- **Missing values show as unknown, not 0.** A probe that doesn't report a temperature or battery no longer shows 0 °C / 0 %, which could trigger frost or low-battery automations.
- **Quiet probes are caught.** A probe now goes unavailable once its latest reading is too old, even while GeoDrops keeps serving that same old reading.
- **"Warn after" works.** A probe past it gets one warning in the Home Assistant log, and a note when it reports again.
- **Advanced Options check their values.** The poll interval is at least 5 minutes, "Warn after" can't exceed "Mark unavailable after", and "Expire after" must be longer than the poll interval. A previously saved value outside these limits keeps working until you next save the form.
- **Clearer setup errors.** Pasting JSON that isn't a key file now says so instead of "Unknown error", and adding an already-configured project stops on the first screen.

## 0.6.0-beta.2 — No more twice-daily "unavailable" blips
- **Probes stay up through GeoDrops' empty polls.** About twice a day GeoDrops' data briefly comes back empty for a poll, and every probe went "unavailable" for 20 minutes even though nothing was wrong. Each probe now keeps its last reading, and goes unavailable only when its own data hasn't arrived for longer than "Expire after" (80 minutes by default). This applies whether the polls failed or just came back empty.

## 0.6.0-beta.1 — Replace a dead key without starting over
- **New key without re-adding probes.** If Google stops accepting your service-account key (deleted, revoked, or its service account disabled), GeoDrops now asks you to re-authenticate on the Devices & Services page — paste a new key and you're back, probes and settings intact. Previously it retried forever and the only fix was deleting and re-adding the integration.
- **Reconfigure.** Change the GCP project or rotate the key any time from the integration's ⋮ menu → Reconfigure. Leave the key blank to keep the current one.
- **Rides out Google hiccups.** Temporary Google errors (outages, rate limits, network drops) no longer trigger a re-authentication prompt; the next poll simply tries again. Permission errors (e.g. a missing BigQuery Job User role) also keep retrying and recover on their own once fixed.
- **No more hung polls.** Each BigQuery query now gives up after about 60 seconds instead of retrying for up to 40 minutes, so setup and "add a probe" fail fast with a clear error during an outage.
- **Fewer false "unavailable" gaps.** The default "Expire after" is now 80 minutes (was 45), so sensors stay up through three missed polls instead of two. If you've ever saved Advanced Options, your stored value is kept — change it under Configure → Advanced Options.

## 0.5.1 — Cleaner setup-screen wording
- The setup screen's help text now points to the integration's Documentation link instead of showing a raw URL in the description. No functional change.

## 0.5.0 — First HACS release
- First tagged release, installable and updatable through HACS as a custom repository. Version is aligned with the standalone `ha-geodrops-integration` service (also v0.5.0) so both GeoDrops paths share one number.
- Native integration: reads GeoDrops soil-moisture straight from BigQuery — no MQTT broker, no separate sync service. Each probe becomes a device with 15 sensors.
- UI setup: paste a service-account JSON key and GCP project id, then add probes by serial; optional Home Assistant Area per probe.
- Configurable poll interval (default 20 minutes) plus lookback and staleness thresholds under Advanced Options.

## 0.1.0
- Initial release: native GeoDrops soil-moisture integration.
- UI config flow (paste service-account JSON) + add probes by serial with live preview.
- 15 sensors per probe; polling coordinator with configurable interval and staleness thresholds.
