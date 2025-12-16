from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class BasicInsightsConfig:
    # Usage vs benchmark
    benchmark_kwh_per_year: float = 6000.0
    high_usage_pct_threshold: float = 20.0  # % above benchmark to flag
    low_usage_pct_threshold: float = -20.0  # % below benchmark to flag

    # Peak-time bias window and threshold
    peak_window_start: str = "16:00"
    peak_window_end: str = "21:00"
    peak_window_days: str = "ALL"  # "ALL" | "MF" | "MS"
    peak_share_high_pct: float = 40.0

    # Data completeness
    min_coverage_pct: float = 90.0


@dataclass
class IntermediateInsightsConfig:
    # Seasonal variation
    warm_months: List[str] = field(
        default_factory=lambda: ["12", "01", "02"]
    )  # Dec–Feb
    cool_months: List[str] = field(
        default_factory=lambda: ["06", "07", "08"]
    )  # Jun–Aug
    seasonal_diff_pct_threshold: float = 25.0
    min_months_required: int = 4

    # Tariff suitability
    tariff_saving_pct_threshold: float = 8.0
    tariff_saving_min_dollars: float = 120.0

    # Peak demand characteristics (spikiness)
    demand_window_start: str = "16:00"
    demand_window_end: str = "21:00"
    demand_window_days: str = "MF"
    spiky_ratio_threshold: float = 1.5  # p95 / mean of daily peak kW


@dataclass
class AdvancedInsightsConfig:
    # EV impact window for attribution
    ev_peak_window_start: str = "16:00"
    ev_peak_window_end: str = "21:00"
    ev_peak_window_days: str = "ALL"

    # Battery evaluation window (evening peak)
    battery_window_start: str = "16:00"
    battery_window_end: str = "21:00"
    battery_window_days: str = "ALL"

    # Step change detection (overnight base usage)
    overnight_start: str = "00:00"
    overnight_end: str = "05:00"
    step_change_pct_threshold: float = 30.0  # before/after halves delta
    min_days_for_step_check: int = 30


@dataclass
class InsightConfig:
    basic: BasicInsightsConfig = field(default_factory=BasicInsightsConfig)
    intermediate: IntermediateInsightsConfig = field(
        default_factory=IntermediateInsightsConfig
    )
    advanced: AdvancedInsightsConfig = field(default_factory=AdvancedInsightsConfig)


def default_config() -> InsightConfig:
    return InsightConfig()
