from __future__ import annotations

from typing import Optional
import pandas as pd

from .types import Insight, InsightContext
from .config import InsightConfig
from ..types import CanonFrame
from .. import transform, utils


def usage_vs_benchmark(
    df: CanonFrame, *, config: InsightConfig, context: Optional[InsightContext] = None
) -> Optional[Insight]:
    if df.empty:
        return None
    idx = pd.DatetimeIndex(df.index)
    if len(idx) == 0:
        return None
    start = idx.min()
    end = idx.max()
    days = int((end - start).days) + 1 if pd.notna(start) and pd.notna(end) else 1
    if days <= 0:
        days = 1
    total = float(pd.to_numeric(df["kwh"], errors="coerce").fillna(0.0).sum())
    annualised = (total / days) * 365.0
    bench = float(config.basic.benchmark_kwh_per_year)
    if bench <= 0:
        return None
    diff_pct = ((annualised - bench) / bench) * 100.0
    sev: str = "info"
    title = "Usage close to benchmark"
    msg = f"Estimated annual usage ~{annualised:,.0f} kWh vs benchmark {bench:,.0f} kWh (Δ {diff_pct:+.0f}%)."
    if diff_pct >= config.basic.high_usage_pct_threshold:
        sev = "warning"
        title = "Usage above benchmark"
        msg = (
            f"Your annualised usage is about {diff_pct:.0f}% above a typical household."
            " Consider efficiency or load shifting to reduce bills."
        )
    elif diff_pct <= config.basic.low_usage_pct_threshold:
        sev = "notice"
        title = "Usage below benchmark"
        msg = f"Your annualised usage is about {abs(diff_pct):.0f}% below a typical household."
    return Insight(
        id="usage_vs_benchmark",
        level="basic",
        category="usage",
        title=title,
        message=msg,
        severity=sev,  # type: ignore[arg-type]
        metrics={
            "annualised_kwh": float(annualised),
            "benchmark_kwh": bench,
            "delta_pct": float(diff_pct),
        },
    )


def peak_time_bias(
    df: CanonFrame, *, config: InsightConfig, context: Optional[InsightContext] = None
) -> Optional[Insight]:
    if df.empty:
        return None
    # Average-day profile -> window stats
    prof = transform.profile(df, by="slot", reducer="mean", include_import_total=True)
    total_daily_kwh = utils.daily_total_from_profile(prof)
    windows = [
        {
            "key": "peak",
            "start": config.basic.peak_window_start,
            "end": config.basic.peak_window_end,
        }
    ]
    win = transform.window_stats_from_profile(
        prof,
        windows,
        utils.infer_cadence_minutes(pd.DatetimeIndex(df.index)),
        total_daily_kwh,
    )
    share = float(win.get("peak", {}).get("share_of_daily_pct", 0.0))
    if share >= config.basic.peak_share_high_pct:
        return Insight(
            id="peak_time_bias",
            level="basic",
            category="usage",
            title="Heavy evening peak usage",
            message=(
                f"About {share:.0f}% of daily usage occurs between {config.basic.peak_window_start} and {config.basic.peak_window_end}. "
                "Shifting flexible loads to off-peak times could reduce bills."
            ),
            severity="warning",  # type: ignore[arg-type]
            metrics={"peak_share_pct": share},
        )
    # If not high, still return a gentle confirmation insight
    return Insight(
        id="peak_time_bias",
        level="basic",
        category="usage",
        title="Peak-time usage is moderate",
        message=(
            f"Around {share:.0f}% of daily usage is in the {config.basic.peak_window_start}–{config.basic.peak_window_end} window."
        ),
        severity="info",  # type: ignore[arg-type]
        metrics={"peak_share_pct": share},
    )


def data_completeness(
    df: CanonFrame, *, config: InsightConfig, context: Optional[InsightContext] = None
) -> Optional[Insight]:
    if df.empty:
        return None
    idx = pd.DatetimeIndex(df.index)
    cadence_min = int(utils.infer_cadence_minutes(idx))
    if len(idx) == 0 or cadence_min <= 0:
        return None
    start = idx.min().normalize()
    end = idx.max().normalize()
    days = int((end - start).days) + 1
    expected_intervals = int(days * (1440 // cadence_min))
    coverage = (
        (len(idx) / expected_intervals * 100.0) if expected_intervals > 0 else 0.0
    )

    if coverage < config.basic.min_coverage_pct:
        return Insight(
            id="data_completeness",
            level="basic",
            category="data_quality",
            title="Incomplete data coverage",
            message=(
                f"Data coverage is about {coverage:.0f}% over the observed period; insights may be less reliable."
            ),
            severity="warning",  # type: ignore[arg-type]
            metrics={"coverage_pct": float(coverage)},
        )
    return Insight(
        id="data_completeness",
        level="basic",
        category="data_quality",
        title="Good data coverage",
        message=(
            f"Coverage is ~{coverage:.0f}% across {days} days; insights based on solid data."
        ),
        severity="info",  # type: ignore[arg-type]
        metrics={"coverage_pct": float(coverage)},
    )
