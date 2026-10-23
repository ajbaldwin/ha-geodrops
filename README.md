# GeoDrops for Home Assistant

A native Home Assistant integration for [GeoDrops](https://geodrops.io/) soil
moisture probes. It reads your sensor data straight out of BigQuery and
exposes each probe as a Home Assistant device with 27 sensors — no MQTT
bridge, no external service to run, no YAML to hand-edit. Everything is
configured through the UI.

This is a companion project to the standalone
[`ha-geodrops-rachio-irrigation`](https://github.com/ajbaldwin/ha-geodrops-rachio-irrigation)
irrigation scheduler, but it does not require it — install this on its own if
all you want is soil-moisture data in Home Assistant.

## What it does

GeoDrops probes publish their readings to a BigQuery table
(`geodrops-prod.db_public.p_sensor_unified`) that GeoDrops has made publicly
readable. This integration polls that table directly from Home Assistant,
using the [aiogeodrops](https://github.com/ajbaldwin/aiogeodrops) library
over BigQuery's REST API, and turns the latest reading per probe into sensor
entities. There's no MQTT broker, no intermediate sync process,
and no polling service to keep alive outside of Home Assistant itself.

### Supported devices

Any GeoDrops soil probe that reports to GeoDrops' cloud, i.e. whose readings
appear in the GeoDrops app. The integration never talks to a probe directly,
so a probe that isn't uploading to GeoDrops can't be added. No other brand of
soil sensor is supported.

### Use cases

- **Smarter irrigation.** Skip or shorten a watering run when the soil is
  already moist, instead of relying on a fixed schedule or rain forecasts.
- **Plant and lawn care alerts.** Get notified when a bed dries out, or when
  soil temperature drops towards frost.
- **Probe upkeep.** Know when a probe's battery runs low or it stops
  reporting, before its readings go stale.

## Prerequisites

You need a Google Cloud Platform (GCP) project of your own — this is where
your queries run and are billed, not where the data lives.

Follow the GeoDrops community walkthrough (with screenshots),
[Integrating GeoDrops soil moisture sensors with Home Assistant](https://geodrops.discourse.group/t/integrating-geodrops-soil-moisture-sensors-with-home-assistant/280#p-953-step-by-step-setup-5), or the
self-contained steps below. If that link ever moves, search the
[GeoDrops community](https://geodrops.discourse.group/) for "Home Assistant".

1. **Create (or reuse) a GCP project** at the
   [GCP Console](https://console.cloud.google.com/) — e.g. `my-ha-bigquery`.
   Note its **project ID** (you enter it during setup).
2. **Enable the BigQuery API** on that project: APIs & Services → Library →
   search "BigQuery API" → **Enable**.
3. **Create a service account**: IAM & Admin → Service Accounts →
   **Create service account** (e.g. `home-assistant-bigquery`).
4. **Grant it `BigQuery Job User`** (`roles/bigquery.jobUser`) **on your own
   project**. That is the only role required — it lets the account run query
   jobs billed to your project. *(The community guide also adds `BigQuery Data
   Viewer`; that's harmless but not required to read the public `db_public`
   dataset.)*
5. **Create and download a JSON key**: on the service account → Keys → Add key
   → Create new key → **JSON**.
6. **Paste the key's contents into the config flow** at setup (see
   *Configuration* below). Unlike the older MQTT bridge, this integration does
   **not** need the file placed in `/config`; Home Assistant stores it in its
   config entry. Then **delete the downloaded key file**.

**Keeping the key safe.** Home Assistant stores config entries unencrypted,
in `/config/.storage/core.config_entries`, and that file is included in
backups. Anyone who can read your configuration directory or a backup can use
the key. With only BigQuery Job User it can run queries billed to your
project and nothing else, so the risk is cost, not data. To cap that cost, set
a custom quota in the GCP Console: IAM & Admin → Quotas, BigQuery API,
*Query usage per day*. About 30 GiB matches BigQuery's free tier of 1 TiB a
month, which this integration stays well within (see
[Polling and cost](#polling-and-cost)). If a key may
have leaked, delete it on the service account's Keys tab and paste a new one
through **Reconfigure**.

You do **not** need to request access to GeoDrops' data or add any
reader/viewer grant on the `db_public` dataset — GeoDrops publishes it as a
public dataset, so any service account that can run a query job in its own
project can already read it. If a query ever fails with a permissions error
*after* your Job User role is confirmed, the cause is almost certainly on the
GeoDrops side (dataset sharing changed), not your IAM setup.

## Installation

1. In HACS, add this repository as a **custom repository** (category:
   Integration): `https://github.com/ajbaldwin/ha-geodrops-hacs`.

   This repository publishes releases with `hide_default_branch: true`, so
   HACS will only ever offer you tagged releases, never the tip of `main`.
2. Install **GeoDrops** from HACS, then restart Home Assistant
   when prompted.
3. Go to **Settings → Devices & Services → Add Integration**, search for
   **GeoDrops**, and start the config flow.

### Beta versions

New versions are released as betas (`X.Y.Z-beta.N`) before they become a
stable release. HACS only offers betas if you opt in:

1. Go to **Settings → Devices & services → Entities**, search for
   **Pre-release**, and open the one for *GeoDrops* (a switch HACS creates for
   each repository, disabled by default).
2. Enable the entity, wait about 30 seconds, then turn the switch **on**.

HACS then offers each beta as an update. Turn the switch off to go back to
stable releases only; you'll get the next stable when it's newer than the beta
you're on.

## Configuration

The config flow is two steps:

1. **Credentials.** Paste the full contents of your service-account JSON key
   into the "Service-account JSON" field, and enter your GCP **project id**
   (e.g. `your-gcp-project-id` — this is your own project from the
   prerequisites above, not GeoDrops'). Home Assistant validates the
   credentials by making a real BigQuery call before letting you continue.
2. **Add a probe.** Enter the probe's **serial number** exactly as shown in
   the GeoDrops app (e.g. `AAA111`) and a friendly name. The integration
   looks up recent readings for that serial to confirm it exists and has
   reported within the lookback window before adding it — if nothing turns
   up, you'll get an error instead of a silently-empty device. This lookup
   only validates the serial; it does not show a live reading preview.

After the first probe is added, you can add more, remove existing ones, or
tune polling/staleness settings at any time from the integration's
**Configure** options (Settings → Devices & Services → GeoDrops →
Configure). Adding another probe by serial works the same way as the initial
setup.

### Advanced Options

Configure → **Advanced Options** holds the polling and staleness settings.
Saving them reloads the integration.

| Option | Default | Allowed | What it does |
| --- | --- | --- | --- |
| Poll interval (minutes) | 20 | 5–1440 | How often to query BigQuery. Each poll is one query covering every probe. |
| BigQuery lookback (hours) | 12 | 1–168 | How far back each poll searches for a probe's latest reading. A probe with nothing in this window keeps its last reading until "Expire after". |
| Warn after (hours) | 12 | 1–168, at most "Mark unavailable after" | Writes one warning to the Home Assistant log when a probe's data gets older than this, and a note when it reports again. |
| Mark unavailable after (hours) | 12 | 1–168 | Makes a probe's sensors unavailable once its latest reading is older than this, counted from when the probe took the reading. |
| Expire after (minutes) | 80 | 5–10080, longer than the poll interval | Also makes a probe's sensors unavailable if its data hasn't come back from a poll for this long, for example during a Google outage. |
| Offline alert after (hours) | 24 | 1–168 | Shows a repair once a probe's latest reading is older than this. When two or more active probes are that old and none is reporting, shows one "GeoDrops data is delayed" repair instead. |

### Rotating the key or changing project

To paste a new service-account key or switch GCP projects, open the
integration's menu (Settings → Devices & Services → GeoDrops → ⋮) and choose
**Reconfigure**. Leave the key field blank to keep the current key. Your
probes and settings are kept.

If Google stops accepting the stored key (because it was deleted or revoked,
or its service account was disabled), Home Assistant stops polling and flags
GeoDrops as needing re-authentication on the Devices & Services page. Click
**Reconfigure** on it, then create a new JSON key for the service account and
paste it in to get polling going again. Permission errors (for
example, a missing BigQuery Job User role) don't trigger this. Home Assistant
keeps retrying those, and polling recovers on its own once you fix the role
in GCP.

### Taking a probe out of service

Pulling probes for the winter, or while one waits for new batteries? Turn off
the probe's **Active** switch (on its device page, under *Configuration*). While
it is off:

- The probe raises no repairs and writes no staleness warnings, and it never
  counts toward "GeoDrops data is delayed".
- All its sensors show as unavailable, so automations stop using its values and
  dashboards show it as out of service. **Last Reading** stays live, so a probe
  that is back in the ground and reporting is easy to spot.
- The switch stays off until you turn it back on, across restarts.

To take a probe out of use completely, disable its device instead (device page →
⋮ → **Disable**). It is then left out of every poll and raises nothing. Enabling
the device brings it back after a short delay.

## Sensors

Each probe becomes one Home Assistant device with 27 sensors and an Active
switch (see [Taking a probe out of service](#taking-a-probe-out-of-service)):

| Sensor | Description |
| --- | --- |
| Dominant Moisture | Overall moisture reading (%), the probe's headline value |
| Moisture State | Enum classification of the dominant moisture reading (e.g. dry/moist/wet) |
| Moisture Depth 1 | Moisture (%) at depth sensor 1 |
| Moisture Depth 2 | Moisture (%) at depth sensor 2 |
| Moisture Depth 3 | Moisture (%) at depth sensor 3 |
| Reading Quality Depth 1 | Reading-quality classification at depth sensor 1 |
| Reading Quality Depth 2 | Reading-quality classification at depth sensor 2 |
| Reading Quality Depth 3 | Reading-quality classification at depth sensor 3 |
| Reading Quality | GeoDrops' overall reading-quality classification |
| Probe Health | What the probe needs, from GeoDrops' action codes: OK, Calibrating, Max Moisture Required, Recalibration Due, Hardware Check or Error |
| Next Action Codes | GeoDrops' raw action codes (e.g. `ATT_DW_NEW, DW_M_LOW12`), including ones Probe Health doesn't recognize |
| Max Moisture Calibration | Problem when GeoDrops asks you to run the max-moisture (deep water) test in its app; moisture stays `unknown` until you do. Also raised as a repair (binary sensor) |
| Max Moisture Recalibration | Problem when the probe's max-moisture calibration has expired (75 days after the last one) and GeoDrops asks for the test to be run again; moisture keeps reporting meanwhile, at reduced quality. Also raised as a repair. Formerly Wick Status (binary sensor) |
| Hardware Status | Problem when GeoDrops asks for a hardware check or reports a hardware error (binary sensor) |
| Battery | Probe battery level (%), as GeoDrops reports it. See [Battery warning](#battery-warning) for why it can mislead |
| Battery Status | Low when the batteries need replacing soon, judged from how fast the probe's voltage is falling; see [Battery warning](#battery-warning) (binary sensor) |
| Battery Voltage | Battery voltage (mV) |
| Signal Strength | The probe's radio signal strength (dBm) |
| Cloud Upload Delay | The upload delay GeoDrops reports for the latest reading (hours), usually about 1. It isn't how old the data is; Last Reading shows that. `unknown` when GeoDrops reports an impossible value. Formerly Sync Delay. |
| Surface Temperature | Soil surface temperature (°C) |
| Temperature Depth 1 | Soil temperature (°C) at depth sensor 1 |
| Temperature Depth 2 | Soil temperature (°C) at depth sensor 2 |
| Temperature Depth 3 | Soil temperature (°C) at depth sensor 3 |
| Avg. 7-Day Sun | 7-day trailing average sun exposure (hours) |
| Last Reading | When the probe took its latest reading (timestamp). GeoDrops stamps each reading with the end of its half-hour slot, so this can be up to 30 minutes late; it never shows a time in the future. |
| Last Detected Watering | When GeoDrops last detected a watering in the probe's readings (timestamp). Like Last Reading, it never shows a time in the future. |
| Watering Confidence | GeoDrops' irrigation confidence for that watering (%) |

GeoDrops marks only the odd reading as showing a watering, so Last Detected
Watering and Watering Confidence keep the last one seen, across restarts and
while the probe is offline. They show `unknown` until a poll finds one. A
watering is seen only if it falls within some poll's lookback window, so one
during a Home Assistant outage longer than the window is missed.

Moisture-related sensors report `unknown` (rather than a misleading value)
while a probe is still in its factory training period and hasn't produced a
calibrated moisture reading yet. Any other value GeoDrops doesn't report
(for example a missing temperature) shows as `unknown`, never as 0. A probe
whose latest reading is older than the configured "mark unavailable after"
threshold (counted from when the probe took it) goes unavailable entirely. Once a probe's data is older than "warn after", a
warning is written to the Home Assistant log (once, until it reports again).

Battery, Battery Status, Battery Voltage, Signal Strength, Cloud Upload Delay, Last
Reading, Reading Quality, Reading Quality Depth 1–3, Probe Health, Next Action Codes, Watering Confidence and the Max
Moisture Calibration, Max Moisture Recalibration and Hardware Status sensors are **diagnostic** sensors: they are listed under *Diagnostic* on the device page and left off
auto-generated dashboards. Battery Voltage, Signal Strength, Cloud Upload Delay,
Avg. 7-Day Sun, Next Action Codes, Max Moisture Recalibration and Hardware Status are **disabled by default** on newly added probes; enable them from the device page if you want
them. The
Reading Quality sensors stay enabled, because automations and other integrations use
them to decide whether a moisture reading can be trusted.

### Battery warning

GeoDrops' battery percentage is a straight line from 4.0 V (0 %) to about
6.57 V (100 %). Probes run on packs whose voltages differ by more than 2 V,
so a full low-voltage pack can read 10–30 % and a high-voltage pack can read
100 % until shortly before it dies. A pack's voltage also falls off a cliff
at the end: a probe can go from 40 % to silent in about two days.

So Battery Status judges each probe by how fast its own voltage is falling,
from the last 14 days of readings (fetched twice a day):

- **Replace soon** (Battery Status is Low): over the last week the voltage
  fell 10 mV a day or more and is below 5.4 V. Normal drain is about 4 mV a
  day.
- **Replace now** (also Low, plus a repair): it fell 20 mV a day or more, or
  is below 4.4 V. Expect the probe to stop reporting within days.

A drained pack's voltage climbs back for a few days when it rests, so Replace
now stays until the voltage is back above where it was when the fall began.
Fresh batteries clear it within about two days. Battery Status is `unknown`
until a probe has a week of readings.

The thresholds come from GeoDrops' fleet: 166 probes over two months.
Of 8 batteries that ran out in that time, 6 showed Replace soon at least a
week before they collapsed. Some batteries give no warning at all, so keep
the offline repair on too.

### States for automations

Moisture State, Probe Health and the Reading Quality sensors show friendly labels in the UI,
but their raw states (what automations, templates and scripts compare
against) are stable keys:

| Sensor | Raw states (UI label) |
| --- | --- |
| Moisture State | `dry` (Dry), `dry_plus` (Dry+), `moist` (Moist), `moist_plus` (Moist+), `wet` (Wet), `wet_plus` (Wet+) |
| Reading Quality, Reading Quality Depth 1–3 | `bad` (Bad), `poor` (Poor), `good` (Good), `training` (Training) |
| Probe Health | `ok` (OK), `calibrating` (Calibrating), `max_moisture_required` (Max Moisture Required), `recalibration_due` (Recalibration Due), `hardware_check` (Hardware Check), `error` (Error) |

A value GeoDrops doesn't classify is Home Assistant's own `unknown`.

Probe Health shows the most urgent of a probe's codes, in the order Error, Hardware
Check, Recalibration Due, Max Moisture Required, Calibrating. Codes it
doesn't recognize, and GeoDrops' notes, leave it at OK; Next Action Codes
shows them. The notes seen so far, where the digits name the depths:

- `DW_M_LOW`: one depth reads lower than the others, even in wet soil.
- `LAX_M_EVA`: evaporation lag.
- `CHK_M_LOW`: very low moisture at that depth. Usually the soil is dry and it
  clears once watered; a brief one just before a hardware error is a GeoDrops
  glitch.
- `MEM_DW_BAD`: the max-moisture test didn't take at that depth. If it has to
  be rerun, GeoDrops also asks for the test, which raises the repair.

 GeoDrops doesn't document these codes: their meanings come from
comparing them with readings across GeoDrops' probes.

### Automation examples

The examples use a probe named "Front"; replace `front` in the entity ids with
your probe's name.

Only water when the soil is dry, as a condition in an existing irrigation
automation:

```yaml
conditions:
  - condition: state
    entity_id: sensor.front_moisture_state
    state: ["dry", "dry_plus"]
```

Get notified when a probe's batteries need replacing (Battery Status turns
Low):

```yaml
triggers:
  - trigger: state
    entity_id: binary_sensor.front_battery_status
    to: "on"
actions:
  - action: notify.notify
    data:
      message: "Replace the batteries in GeoDrops probe Front soon."
```

Warn about near-freezing soil:

```yaml
triggers:
  - trigger: numeric_state
    entity_id: sensor.front_surface_temperature
    below: 2
actions:
  - action: notify.notify
    data:
      message: "Soil surface at the Front probe is {{ states('sensor.front_surface_temperature') }} °C."
```

## Polling and cost

The integration issues **one BigQuery query per poll**, covering the latest
reading for *all* configured probes at once — it does not issue one query
per device. The default poll interval is **20 minutes**, adjustable in the
integration's options (Settings → Devices & Services → GeoDrops →
Configure → Advanced Options), along with the lookback window
and staleness thresholds. Twice a day it also makes one query for the last
14 days of every probe's battery voltage, for the
[battery warning](#battery-warning). At this query pattern and a typical
handful of probes, usage stays well within BigQuery's free tier.

## Known limitations

- **Readings are only as fresh as GeoDrops' upload.** A probe takes a
  reading every 30 minutes but saves battery by uploading only when soil
  moisture has changed noticeably, or at the latest 3 hours after its last
  upload. GeoDrops adds new uploads to its table once an hour, and the
  integration polls every 20 minutes by default. So on steady soil a value
  can be up to about 5 hours old while the probe is healthy; Last Reading
  shows when it was taken. A latest reading older than 6 hours means the
  probe isn't reporting.
- **Cloud only.** Readings come from GeoDrops' BigQuery table through Google
  Cloud; there is no local API. If Google, GeoDrops or your internet
  connection is down, sensors keep their last value until "Expire after"
  and then go unavailable.
- **GeoDrops reprocesses its data twice a day.** It refits each probe's
  soil profile and rewrites the whole history, which empties its table for
  about 20 minutes. A poll during that window finds nothing; each probe keeps
  its last reading. The rewrite can also adjust past values, so Home
  Assistant's history (recorded as values arrived) can differ slightly from
  what the GeoDrops app shows for the same time, and a sensor can change
  value without a new reading.
- **Probes are added by serial, not discovered.** The table is shared by all
  GeoDrops users, so the integration can't list "your" probes.
- **The first probe is found by searching the last 7 days.** Probes added
  later search the configured lookback window. A probe that hasn't reported
  in that time can't be added until it does.
- **Moisture reads `unknown` during a new probe's training period**, until
  GeoDrops has calibrated it.

## Troubleshooting

**"No readings found for that serial"** when adding a probe. Check the
serial against the GeoDrops app, and that the probe has reported within the
lookback window (12 hours by default; the first probe searches 7 days).

**"Could not query BigQuery"** during setup, or a **"GeoDrops can't query
BigQuery"** repair (Settings → System → Repairs). Google refused the query.
Check that:

1. The project id is your own GCP project, not GeoDrops'.
2. The BigQuery API is enabled on that project.
3. The service account has **BigQuery Job User** on that project.

GeoDrops keeps retrying, and the repair clears itself on the first query that
succeeds.

**A "needs its max-moisture calibration" or "max-moisture calibration has
expired" repair** (Settings → System → Repairs). GeoDrops wants the
max-moisture (deep water) test run on that probe: for the first time, in
which case its moisture sensors stay `unknown` until it is, or again, which
it asks for 75 days after the last one. Run the test from the probe's prompt
in the GeoDrops app. The repair clears itself once GeoDrops stops asking,
which can take a few hours to show up.

**A "has stopped reporting" repair** (Settings → System → Repairs). That
probe's latest reading is older than "Offline alert after" (24 hours by
default). Check in the GeoDrops app that it is online; Wi-Fi and the battery
are the usual causes. The repair clears itself once the probe reports again,
and stays across restarts until then.

**A "Replace the batteries" repair.** That probe's battery voltage is
falling fast or is below 4.4 V, so it will likely stop reporting within days.
Replace its batteries; the repair clears itself within about two days. See
[Battery warning](#battery-warning).

**A "GeoDrops data is delayed" repair.** Every probe stopped at once, which
points at GeoDrops rather than your probes. It clears itself once readings
arrive again. If you've pulled your probes for the season, turn off their
Active switches instead; see
[Taking a probe out of service](#taking-a-probe-out-of-service).

**GeoDrops asks to re-authenticate.** Google stopped accepting the key. See
[Rotating the key or changing project](#rotating-the-key-or-changing-project).

**A probe's sensors are unavailable.** Check its Active switch first. Otherwise,
its latest reading is older than
"Mark unavailable after", or no reading has come back from a poll for
"Expire after". Check that the probe is reporting in the GeoDrops app. To
see whether Wi-Fi is the cause, enable its Signal Strength sensor and check
its history: a weak signal (around -80 dBm or lower) before the probe went
quiet points to Wi-Fi.

**Moisture sensors show `unknown`.** The probe is still in its training
period, or GeoDrops didn't report that value. Temperatures and battery still
update.

**Reporting a problem.** Enable debug logging (Settings → Devices & services
→ GeoDrops → ⋮ → Enable debug logging), reproduce the problem, then disable
it to download the log. Also download diagnostics from the same menu; they
include each probe's last reading and the last error, with the key and
project id removed. Attach both to an
[issue](https://github.com/ajbaldwin/ha-geodrops-hacs/issues).

## Removing the integration

1. Go to **Settings → Devices & services → GeoDrops**, open the ⋮ menu and
   choose **Delete**. This removes every probe with its device and sensors,
   and the stored service-account key.
2. To uninstall the code as well, open **GeoDrops** in HACS, choose ⋮ →
   **Remove**, then restart Home Assistant.
3. Optionally, delete the key in the
   [GCP Console](https://console.cloud.google.com/) (IAM & Admin → Service
   Accounts → your account → Keys), or delete the whole service account.
   Home Assistant no longer holds the key, but the key itself stays valid
   until you delete it.

To remove a single probe instead, use **Configure → Remove a probe**.
