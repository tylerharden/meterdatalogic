from __future__ import annotations

from dataclasses import dataclass, field
from typing import List


@dataclass
class BasicInsightsConfig:
    """Configuration for basic-level insights.

    These thresholds are based on typical Australian residential usage patterns
    and industry benchmarks for customer engagement.
    """

    # Usage vs benchmark
    benchmark_kwh_per_year: float = 6000.0  # Typical 2-3 person household in QLD/NSW
    high_usage_pct_threshold: float = 20.0  # % above benchmark to flag
    low_usage_pct_threshold: float = -20.0  # % below benchmark to flag

    # Peak-time bias window and threshold
    peak_window_start: str = "16:00"  # Typical ToU peak start
    peak_window_end: str = "21:00"  # Typical ToU peak end
    peak_window_days: str = "ALL"  # "ALL" | "MF" | "MS"
    peak_share_high_pct: float = 40.0  # >40% in 5-hour window indicates concentration

    # Data completeness
    min_coverage_pct: float = 90.0  # Below 90% may indicate meter/comms issues


@dataclass
class IntermediateInsightsConfig:
    """Configuration for intermediate-level insights.

    These values are tuned for actionable recommendations based on
    observed usage patterns and tariff structures in Australian retail markets.
    """

    # Seasonal variation
    warm_months: List[str] = field(
        default_factory=lambda: ["12", "01", "02"]  # Dec–Feb (summer in AU)
    )
    cool_months: List[str] = field(
        default_factory=lambda: ["06", "07", "08"]  # Jun–Aug (winter in AU)
    )
    seasonal_diff_pct_threshold: float = 25.0  # >25% variation suggests seasonal load
    min_months_required: int = 4  # Need 4+ months for reliable seasonal analysis

    # Tariff suitability
    tariff_saving_pct_threshold: float = 8.0  # >8% saving worth switching tariffs
    tariff_saving_min_dollars: float = 120.0  # Minimum $120/year to justify effort

    # Peak demand characteristics (spikiness)
    demand_window_start: str = "16:00"  # Typical demand charge window
    demand_window_end: str = "21:00"
    demand_window_days: str = "MF"  # Business days for demand charges
    spiky_ratio_threshold: float = 1.5  # p95/mean >1.5 indicates high variability


@dataclass
class AdvancedInsightsConfig:
    """Configuration for advanced-level insights.

    These parameters support detection of specific behaviors (EV charging,
    baseload changes) and scenario impact assessment.
    """

    # EV impact window for attribution
    ev_peak_window_start: str = "16:00"  # Typical home arrival time
    ev_peak_window_end: str = "21:00"
    ev_peak_window_days: str = "ALL"

    # Battery evaluation window (evening peak)
    battery_window_start: str = "16:00"  # Peak pricing period
    battery_window_end: str = "21:00"
    battery_window_days: str = "ALL"

    # Step change detection (overnight base usage)
    overnight_start: str = "00:00"  # Baseload period
    overnight_end: str = "05:00"
    step_change_pct_threshold: float = 30.0  # >30% change in before/after halves
    min_days_for_step_check: int = 30  # Need 1 month minimum for reliable detection


@dataclass
class InsightConfig:
    basic: BasicInsightsConfig = field(default_factory=BasicInsightsConfig)
    intermediate: IntermediateInsightsConfig = field(default_factory=IntermediateInsightsConfig)
    advanced: AdvancedInsightsConfig = field(default_factory=AdvancedInsightsConfig)


def default_config() -> InsightConfig:
    return InsightConfig()
