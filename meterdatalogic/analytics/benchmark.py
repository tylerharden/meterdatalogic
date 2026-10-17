"""Household peer-group usage benchmarking.

Extends the single-constant `benchmark_kwh_per_year` concept already used by
the insights engine (see `analytics/insights/config.py`'s
`BasicInsightsConfig.benchmark_kwh_per_year`) into a segmented lookup: a
"typical annual kWh" estimate based on household occupancy, air conditioning
type, and hot water system - the three attributes the app's household-profile
step collects that have a large enough effect on usage to be worth
segmenting on.

This is NOT derived from real aggregate customer data. It's a simple,
documented, easily-adjustable model (a base kWh per occupant count, with
multiplicative adjustments for aircon and hot water type) so the numbers can
be swapped for a real reference dataset later without changing the call
signature. Treat results as "ballpark normal, not a leaderboard" - consistent
with how benchmark comparisons are already framed elsewhere in this package
(see docs/features/insights.md limitations).
"""

from __future__ import annotations
from typing import Literal, TypedDict

Occupants = Literal["1", "2", "3", "4", "5+"]
AirconType = Literal["ducted", "split_system", "none"]
HotWater = Literal[
    "electric_controlled_load",
    "electric_resistive",
    "heat_pump",
    "gas",
    "solar",
    "unknown",
]

# Base annual kWh per occupant count (typical AU residential, no major extras).
_BASE_KWH_BY_OCCUPANTS: dict[Occupants, float] = {
    "1": 2800.0,
    "2": 4200.0,
    "3": 5200.0,
    "4": 6000.0,
    "5+": 7000.0,
}

# Multiplicative adjustment for air conditioning type.
_AIRCON_FACTOR: dict[AirconType, float] = {
    "none": 0.85,
    "split_system": 1.0,
    "ducted": 1.35,
}

# Multiplicative adjustment for hot water system.
_HOT_WATER_FACTOR: dict[HotWater, float] = {
    "gas": 0.85,
    "solar": 0.85,
    "heat_pump": 0.90,
    "electric_controlled_load": 1.0,
    "electric_resistive": 1.2,
    "unknown": 1.0,
}

# +/- band around the point estimate used to express a "typical range"
# rather than a single number, so callers can frame this as a ballpark
# rather than a precise ranking.
_RANGE_SPREAD = 0.25


class BenchmarkResult(TypedDict):
    typical_kwh: float
    typical_kwh_low: float
    typical_kwh_high: float
    pct_diff: float


def typical_annual_kwh(
    *,
    occupants: Occupants = "2",
    aircon_type: AirconType = "split_system",
    hot_water: HotWater = "unknown",
) -> float:
    """Point estimate of typical annual kWh for a household peer-group.

    Unrecognised enum values fall back to the most common/neutral bucket
    (2 occupants, split system aircon, factor 1.0 hot water) rather than
    raising, so this degrades gracefully when a household profile is
    incomplete (per the app's "skip this one" / "skip all of this" flow).
    """
    base = _BASE_KWH_BY_OCCUPANTS.get(occupants, _BASE_KWH_BY_OCCUPANTS["2"])
    aircon = _AIRCON_FACTOR.get(aircon_type, 1.0)
    hw = _HOT_WATER_FACTOR.get(hot_water, 1.0)
    return base * aircon * hw


def compare(
    total_annual_kwh: float,
    *,
    occupants: Occupants = "2",
    aircon_type: AirconType = "split_system",
    hot_water: HotWater = "unknown",
) -> BenchmarkResult:
    """Compare a household's actual annual kWh to its peer-group typical range.

    `pct_diff` is positive when the household uses more than typical for its
    peer group, negative when it uses less.
    """
    typical = typical_annual_kwh(occupants=occupants, aircon_type=aircon_type, hot_water=hot_water)
    low = typical * (1.0 - _RANGE_SPREAD)
    high = typical * (1.0 + _RANGE_SPREAD)
    pct_diff = ((total_annual_kwh - typical) / typical * 100.0) if typical > 0 else 0.0
    return {
        "typical_kwh": float(typical),
        "typical_kwh_low": float(low),
        "typical_kwh_high": float(high),
        "pct_diff": float(pct_diff),
    }
