from datetime import UTC, date, datetime, timedelta

from aiogeodrops import BatteryPoint
import pytest

from custom_components.geodrops.battery import (
    BatteryTrend,
    battery_outlook,
    battery_trend,
)

START = datetime(2026, 1, 1, tzinfo=UTC)


def _points(daily_mv, per_day=4):
    """`per_day` readings on each day, every one at that day's voltage."""
    return [
        BatteryPoint(START + timedelta(days=day, hours=h * 24 / per_day), mv)
        for day, mv in enumerate(daily_mv)
        for h in range(per_day)
    ]


def _declining(start_mv, days, mv_per_day):
    return [start_mv + mv_per_day * d for d in range(days)]


def test_normal_drain_is_ok():
    trend = battery_trend(_points(_declining(5500, 14, -4)))
    assert trend.outlook == "ok"
    assert trend.slope == pytest.approx(-4)


def test_flat_low_voltage_pack_is_ok():
    # Some packs sit around 4.5 V for weeks; the level alone is no warning.
    assert battery_trend(_points([4550] * 14)).outlook == "ok"


def test_fast_drain_above_the_voltage_gate_is_ok():
    # Fresh high-voltage packs fall 8-12 mV a day long before they are low.
    assert battery_trend(_points(_declining(6300, 14, -12))).outlook == "ok"


def test_accelerating_drain_is_replace_soon():
    daily = _declining(5300, 7, -4) + _declining(5276 - 15, 7, -15)
    trend = battery_trend(_points(daily))
    assert trend.outlook == "soon"
    assert trend.slope == pytest.approx(-15, abs=2)


def test_replace_soon_clears_once_the_drain_slows():
    # Only Replace now is held: a week of fast drain that settles is not a
    # warning for good.
    daily = _declining(5300, 8, -15) + [5195] * 8
    assert battery_trend(_points(daily)).outlook == "ok"


def test_collapse_is_replace_now():
    daily = [*_declining(5300, 11, -4), 5000, 4700, 4400]
    assert battery_trend(_points(daily)).outlook == "now"


def test_below_the_floor_is_replace_now_without_a_week_of_history():
    assert battery_trend(_points([4350, 4340])).outlook == "now"


def test_short_history_is_unknown():
    trend = battery_trend(_points([5300] * 5))
    assert trend.outlook is None
    assert trend.slope is None


def test_no_history_is_unknown():
    assert battery_trend([]) == BatteryTrend(outlook=None, slope=None, daily=())


def test_recovery_after_a_collapse_keeps_the_warning():
    # A drained pack rests and its voltage climbs back for a while; the slope
    # turns positive, but the battery is no better.
    daily = [5400] * 7 + [4600, 4500] + [5200] * 7
    trend = battery_trend(_points(daily))
    assert trend.slope > 0
    assert trend.outlook == "now"


def test_fresh_batteries_clear_the_warning():
    daily = [5400] * 7 + [4600, 4500] + [5700] * 3
    assert battery_trend(_points(daily)).outlook == "ok"


def test_placeholder_voltage_is_ignored():
    points = _points([5300] * 10)
    # 7100 mV is a GeoDrops placeholder: a day of nothing else drops out, and
    # on other days it doesn't move the median.
    points += [
        BatteryPoint(START + timedelta(days=d, hours=1), 7100) for d in range(10)
    ]
    points += [
        BatteryPoint(START + timedelta(days=10, hours=h), 7100) for h in range(4)
    ]
    trend = battery_trend(points)
    assert trend.outlook == "ok"
    assert [mv for _, mv in trend.daily] == [5300] * 10


def test_daily_medians_are_by_utc_day():
    points = [
        BatteryPoint(datetime(2026, 1, 1, 0, 30, tzinfo=UTC), 5300),
        BatteryPoint(datetime(2026, 1, 1, 12, 0, tzinfo=UTC), 5290),
        BatteryPoint(datetime(2026, 1, 1, 23, 30, tzinfo=UTC), 5000),
        BatteryPoint(datetime(2026, 1, 2, 0, 30, tzinfo=UTC), 5280),
    ]
    assert battery_trend(points).daily == (
        (date(2026, 1, 1), 5290),
        (date(2026, 1, 2), 5280),
    )


@pytest.mark.parametrize(
    ("trend_outlook", "latest_mv", "expected"),
    [
        ("ok", 5300.0, "ok"),
        ("soon", 5100.0, "soon"),
        # The latest reading catches a pack below the floor between fetches.
        ("soon", 4390.0, "now"),
        ("ok", 4390.0, "now"),
        (None, 4390.0, "now"),
        # ...but never clears a held warning.
        ("now", 5300.0, "now"),
        (None, 5300.0, None),
        ("ok", None, "ok"),
        ("ok", 7100.0, "ok"),
    ],
)
def test_outlook_combines_the_trend_and_the_latest_reading(
    trend_outlook, latest_mv, expected
):
    trend = BatteryTrend(outlook=trend_outlook, slope=None, daily=())
    assert battery_outlook(trend, latest_mv) == expected


def test_outlook_without_a_trend_uses_the_latest_reading():
    assert battery_outlook(None, 4390.0) == "now"
    assert battery_outlook(None, 5300.0) is None
