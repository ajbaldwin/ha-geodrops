"""Pure transforms: state maps and staleness classification."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from aiogeodrops import DeviceReading

type Staleness = Literal["ok", "warn", "skip"]

# How far a row's sync delay may exceed the reading's own age before it is
# treated as bad data. Normal rows exceed it by about an hour at most.
SYNC_DELAY_SLACK_HOURS = 3

# Enum states are translation keys (see strings.json "entity" and icons.json):
# the UI shows "Good", "Wet+", ... while automations compare the stable keys.
# An unmapped value is None, i.e. Home Assistant's own "unknown".
_QCN_STATE = {2: "good", 1: "poor", 0: "bad", -1: "training"}
QCN_OPTIONS = ["bad", "poor", "good", "training"]

_MI_STATE = {
    5: "wet_plus",
    4: "wet",
    3: "moist_plus",
    2: "moist",
    1: "dry_plus",
    0: "dry",
}
MOISTURE_STATE_OPTIONS = ["dry", "dry_plus", "moist", "moist_plus", "wet", "wet_plus"]


# GeoDrops' nextAction codes, by the Probe Health state they produce. Meanings come
# from correlating each code with qcn and moisture across GeoDrops' fleet
# (github.com/theOrakle/geodrops, enrich.py):
# - ATT_DW_NEW: the app's "Action Required: Learn Max Moisture". Moisture
#   stays unknown until the max-moisture (deep water) test is run in the app.
# - ATT_SS_NEW, MEM_T_LRN: new-sensor and temperature learning; qcn is -1.
# - DW_RENEW: the max-moisture calibration has expired and the test should be
#   run again. It fires 75 days after the last one (dateLastCalibDeepWater);
#   moisture keeps reporting meanwhile, at reduced quality.
# - CHK_M_HWR, CHK_T_HWR, NULL_HWR: GeoDrops asks for a hardware check.
# - ERR_LOSS, ERR_NULL: hardware error.
# Other codes are notes, not states:
# - DW_M_LOW<depths>: one depth reads lower than expected; fires on wet soil too.
# - LAX_M_EVA<depths>: evaporation lag.
# - CHK_M_LOW<depths>: raw moisture very low at those depths. Either dry soil
#   for days (clears when watered) or a one-reading drop on every depth just
#   before ERR_LOSS, often on several probes at once (a GeoDrops glitch).
#   Reinstalling the probe never cleared it, so it isn't a soil-contact check.
# - MEM_DW_BAD<depths>: the max-moisture test didn't take at those depths. It
#   lasts about 36 hours, alongside ATT_DW_NEW when the test must be rerun.
MAX_MOISTURE_CODES = frozenset({"ATT_DW_NEW"})
RECALIBRATION_CODES = frozenset({"DW_RENEW"})
HARDWARE_CODES = frozenset({"CHK_M_HWR", "CHK_T_HWR", "NULL_HWR"})
ERROR_CODES = frozenset({"ERR_LOSS", "ERR_NULL"})
_CALIBRATING_CODES = frozenset({"ATT_SS_NEW", "MEM_T_LRN"})

# Most urgent first: a probe with several codes shows the first that matches.
_STATUS_BY_CODES = (
    ("error", ERROR_CODES),
    ("hardware_check", HARDWARE_CODES),
    ("recalibration_due", RECALIBRATION_CODES),
    ("max_moisture_required", MAX_MOISTURE_CODES),
    ("calibrating", _CALIBRATING_CODES),
)
STATUS_OPTIONS = [*(state for state, _ in _STATUS_BY_CODES), "ok"]


def next_action_to_status(codes: frozenset[str] | None) -> str | None:
    """Return the Probe Health sensor state for a probe's nextAction codes.

    None (unknown) when GeoDrops' table has no nextAction column.
    """
    if codes is None:
        return None
    for state, state_codes in _STATUS_BY_CODES:
        if codes & state_codes:
            return state
    return "ok"


def has_code(codes: frozenset[str] | None, wanted: frozenset[str]) -> bool | None:
    """Whether any of `wanted` is among a probe's codes; None if unknown."""
    return None if codes is None else bool(codes & wanted)


def qcn_to_state(value: int) -> str | None:
    """Return the Reading Quality sensor state for a GeoDrops qcn value."""
    return _QCN_STATE.get(value)


def moisture_index_to_state(value: int) -> str | None:
    """Return the Moisture State sensor state for a GeoDrops moisture index."""
    return _MI_STATE.get(value)


def classify_staleness(age_hours: float, warn_hours: int, skip_hours: int) -> Staleness:
    """'skip' above skip_hours, 'warn' above warn_hours, else 'ok'. Strict > (matches source)."""
    if age_hours > skip_hours:
        return "skip"
    if age_hours > warn_hours:
        return "warn"
    return "ok"


def sync_delay_hours(reading: DeviceReading, now: datetime) -> float | None:
    """Return GeoDrops' sync delay, or None when it can't be right.

    The sync delay is how long a reading took to reach GeoDrops' cloud after
    the probe recorded it, so it can't be much longer than the reading's own
    age. Rows normally carry up to about an hour more delay than their age
    (`date` can even be later than the upload), so SYNC_DELAY_SLACK_HOURS allows for
    that. A GeoDrops bug serves delays of thousands of hours on fresh rows.
    """
    delay = reading.sync_delay_hours
    if delay is None or reading.read_at is None:
        return delay
    clock_age = (now - reading.read_at).total_seconds() / 3600
    if delay > clock_age + SYNC_DELAY_SLACK_HOURS:
        return None
    return delay


def data_age_hours(reading: DeviceReading, now: datetime) -> float | None:
    """Return the hours since a reading was taken (its `date`), or None.

    GeoDrops' guidance: a latest reading more than 6 hours old means the probe
    isn't reporting. A healthy probe reads every 30 minutes and uploads at
    least every 3 hours, and GeoDrops appends uploads hourly, so its latest
    reading stays under about 5 hours old. The sync delay plays no part; it explains a slow upload,
    not whether one happened, and GeoDrops sometimes serves bogus values.
    """
    if reading.read_at is None:
        return None
    return (now - reading.read_at).total_seconds() / 3600
