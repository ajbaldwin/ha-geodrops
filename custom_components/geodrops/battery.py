"""Battery outlook: whether a probe's batteries need replacing, from their trend.

GeoDrops' battery percentage is a straight line from 4.0 V (0 %) to about
6.57 V (100 %), but probes run on packs whose voltages differ by more than 2 V,
and a pack's voltage drops off a cliff at the end. No single voltage or
percentage warns in time, so this judges each probe by how fast its own
voltage is falling.

The thresholds come from GeoDrops' fleet (166 probes, about 60 days; README
"Battery warning"). Normal drain is about 4 mV a day. On 8 batteries that ran
out, a 7-day drain of 10 mV a day or more below 5.4 V came at least a week
before 6 of them collapsed. Packs above 5.4 V can drain that fast while still
fresh.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, timedelta
from statistics import median
from typing import Literal

from aiogeodrops import BatteryPoint

type BatteryOutlook = Literal["ok", "soon", "now"]

# How much history to fetch: the 7-day slope, plus time for a Replace now to
# be held through a recovery.
HISTORY_DAYS = 14
# GeoDrops reports exactly 7100 mV on some probes: a placeholder, not a reading.
PLACEHOLDER_MV = 7000
SLOPE_DAYS = 7
SMOOTHING_DAYS = 3
SOON_SLOPE = -10.0  # mV a day
SOON_BELOW_MV = 5400.0
NOW_SLOPE = -20.0  # mV a day
NOW_BELOW_MV = 4400.0


@dataclass(frozen=True)
class BatteryTrend:
    """A probe's battery outlook, from its voltage history."""

    outlook: BatteryOutlook | None
    """None until there is a week of history (unless already below the floor)."""
    slope: float | None
    """mV a day over the last week, smoothed; None without a week of history."""
    daily: tuple[tuple[date, float], ...]
    """Median voltage of each UTC day, oldest first."""


def battery_trend(points: Iterable[BatteryPoint]) -> BatteryTrend:
    """Judge a probe's batteries from its voltage readings.

    Each day's readings are reduced to their median, and each day's value to
    the median of it and the two days before, so a stray reading can't raise
    a warning. Then, for each day:

    - Replace now: falling 20 mV a day or more over the week, or below 4.4 V.
    - Replace soon: falling 10 mV a day or more, and below 5.4 V.

    A drained pack's voltage climbs back for a few days when it rests, which
    would make the slope look healthy. So Replace now is held until the
    voltage is back above where it was when the fall began: fresh batteries
    are, a recovering pack isn't. Replace soon is judged afresh each day.
    """
    by_day: dict[date, list[float]] = {}
    for point in points:
        if point.battery_mv < PLACEHOLDER_MV:
            by_day.setdefault(point.read_at.date(), []).append(point.battery_mv)
    daily = tuple((day, median(values)) for day, values in sorted(by_day.items()))
    if not daily:
        return BatteryTrend(outlook=None, slope=None, daily=())
    days = [day for day, _ in daily]
    smoothed = [
        median(mv for _, mv in daily[max(0, i - SMOOTHING_DAYS + 1) : i + 1])
        for i in range(len(daily))
    ]
    outlook: BatteryOutlook | None = None
    slope: float | None = None
    # While Replace now is held: the voltage that ends it.
    hold_until: float | None = None
    for i, day in enumerate(days):
        start = _week_before(days, i)
        slope = None
        if start is not None:
            slope = (smoothed[i] - smoothed[start]) / (day - days[start]).days
        if hold_until is not None and smoothed[i] >= hold_until:
            hold_until = None
        if smoothed[i] < NOW_BELOW_MV or (slope is not None and slope <= NOW_SLOPE):
            level = NOW_BELOW_MV if start is None else smoothed[start]
            hold_until = max(level, hold_until or level)
        if hold_until is not None:
            outlook = "now"
        elif slope is None:
            outlook = None
        elif slope <= SOON_SLOPE and smoothed[i] < SOON_BELOW_MV:
            outlook = "soon"
        else:
            outlook = "ok"
    return BatteryTrend(outlook=outlook, slope=slope, daily=daily)


def _week_before(days: list[date], i: int) -> int | None:
    """Index of the latest day at least SLOPE_DAYS before days[i], if any."""
    cutoff = days[i] - timedelta(days=SLOPE_DAYS)
    for j in range(i - 1, -1, -1):
        if days[j] <= cutoff:
            return j
    return None


def battery_outlook(
    trend: BatteryTrend | None, latest_mv: float | None
) -> BatteryOutlook | None:
    """Combine the trend with the latest reading.

    The trend is fetched twice a day; the latest reading arrives with every
    poll, so a pack that falls below the floor in between shows at once.
    """
    outlook = None if trend is None else trend.outlook
    if latest_mv is not None and latest_mv < NOW_BELOW_MV:
        return "now"
    return outlook
