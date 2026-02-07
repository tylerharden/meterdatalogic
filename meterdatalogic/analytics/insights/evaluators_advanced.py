from __future__ import annotations

from typing import Optional
import pandas as pd

from .types import Insight, InsightContext
from .config import InsightConfig
from ...core.types import CanonFrame
from ..types import ScenarioResult
from ...core import transform, utils


def _annual_total_cost(d: Optional[pd.DataFrame]) -> float:
    if d is None or d.empty:
        return 0.0
    if "total" in d.columns:
        return float(pd.to_numeric(d["total"], errors="coerce").fillna(0.0).sum())
    # fallback: sum all numeric columns
    return float(d.select_dtypes("number").sum(axis=1).sum())


def ev_impact(
    df: CanonFrame, *, config: InsightConfig, context: Optional[InsightContext] = None
) -> Optional[Insight]:
    if context is None or context.scenarios is None:
        return None
    sc_map = context.scenarios.scenarios
    if "ev" not in sc_map:
        return None
    sc: ScenarioResult = sc_map["ev"]
    # Annual energy delta
    before_kwh = float(sc.summary_before.get("stats", {}).get("total_import_kwh", 0.0))
    after_kwh = float(sc.summary_after.get("stats", {}).get("total_import_kwh", 0.0))
    delta_kwh = after_kwh - before_kwh
    # Annual bill delta if available
    cost_before = _annual_total_cost(sc.cost_before)
    cost_after = _annual_total_cost(sc.cost_after)
    cost_delta = cost_after - cost_before

    # Rough attribution of charging time: compare peak-window import share before/after
    def _peak_share(dfx: pd.DataFrame) -> float:
        prof = transform.profile(dfx, by="slot", reducer="mean", include_import_total=True)
        total_daily_kwh = utils.daily_total_from_profile(prof)
        windows = [
            {
                "key": "peak",
                "start": config.advanced.ev_peak_window_start,
                "end": config.advanced.ev_peak_window_end,
            }
        ]
        stats = transform.window_stats_from_profile(
            prof,
            windows,
            utils.infer_cadence_minutes(pd.DatetimeIndex(dfx.index)),
            total_daily_kwh,
        )
        return float(stats.get("peak", {}).get("share_of_daily_pct", 0.0))

    peak_share_before = _peak_share(sc.df_before)
    peak_share_after = _peak_share(sc.df_after)
    charging_in_peak = peak_share_after > peak_share_before

    direction = "increase" if cost_delta > 0 else "decrease"
    title = "EV charging impact"
    msg = (
        f"EV charging adds ~{delta_kwh:,.0f} kWh/yr and a {direction} in annual bill of ${abs(cost_delta):,.0f}. "
        + (
            "Charging appears concentrated in peak hours."
            if charging_in_peak
            else "Charging appears mostly off-peak."
        )
    )
    return Insight(
        id="ev_impact",
        level="advanced",
        category="scenario",
        title=title,
        message=msg,
        severity="notice",  # type: ignore[arg-type]
        metrics={
            "delta_kwh_year": float(delta_kwh),
            "delta_cost_year": float(cost_delta),
            "peak_share_before_pct": peak_share_before,
            "peak_share_after_pct": peak_share_after,
        },
    )


def battery_impact(
    df: CanonFrame, *, config: InsightConfig, context: Optional[InsightContext] = None
) -> Optional[Insight]:
    if context is None or context.scenarios is None:
        return None
    sc_map = context.scenarios.scenarios
    if "battery" not in sc_map:
        return None
    sc: ScenarioResult = sc_map["battery"]

    def _window_kwh(dfx: pd.DataFrame) -> float:
        prof = transform.profile(dfx, by="slot", reducer="mean", include_import_total=True)
        stats = transform.window_stats_from_profile(
            prof,
            [
                {
                    "key": "win",
                    "start": config.advanced.battery_window_start,
                    "end": config.advanced.battery_window_end,
                }
            ],
            utils.infer_cadence_minutes(pd.DatetimeIndex(dfx.index)),
        )
        return float(stats.get("win", {}).get("kwh_per_day", 0.0))

    before_win = _window_kwh(sc.df_before)
    after_win = _window_kwh(sc.df_after)
    reduction = before_win - after_win

    cost_before = _annual_total_cost(sc.cost_before)
    cost_after = _annual_total_cost(sc.cost_after)
    cost_delta = cost_after - cost_before

    return Insight(
        id="battery_impact",
        level="advanced",
        category="scenario",
        title="Battery reduces evening grid import",
        message=(
            f"Battery cuts average evening import by ~{reduction:.1f} kWh/day and changes annual bill by ${-cost_delta:,.0f}."
        ),
        severity="notice",  # type: ignore[arg-type]
        metrics={
            "evening_import_before_kwh_per_day": before_win,
            "evening_import_after_kwh_per_day": after_win,
            "reduction_kwh_per_day": reduction,
            "annual_bill_change_dollars": float(cost_delta * -1.0),
        },
    )


def load_shifting_opportunities(
    df: CanonFrame, *, config: InsightConfig, context: Optional[InsightContext] = None
) -> Optional[Insight]:
    if df.empty:
        return None
    # Heuristic: high evening share and low daytime share suggests shifting potential
    prof = transform.profile(df, by="slot", reducer="mean", include_import_total=True)
    total_daily_kwh = utils.daily_total_from_profile(prof)
    windows = [
        {"key": "evening", "start": "16:00", "end": "21:00"},
        {"key": "daytime", "start": "09:00", "end": "16:00"},
    ]
    stats = transform.window_stats_from_profile(
        prof,
        windows,
        utils.infer_cadence_minutes(pd.DatetimeIndex(df.index)),
        total_daily_kwh,
    )
    evening = float(stats.get("evening", {}).get("share_of_daily_pct", 0.0))
    daytime = float(stats.get("daytime", {}).get("share_of_daily_pct", 0.0))
    if evening >= 35.0 and daytime <= 30.0:
        return Insight(
            id="load_shifting_opportunities",
            level="advanced",
            category="usage",
            title="Load shifting could reduce bills",
            message=(
                "Recurring evening loads appear misaligned with cheaper or solar-rich periods. "
                "Consider moving hot water, pool pump, or EV charging to daytime/off-peak."
            ),
            severity="notice",  # type: ignore[arg-type]
            metrics={"evening_share_pct": evening, "daytime_share_pct": daytime},
        )
    return None


def step_change_baseload(
    df: CanonFrame, *, config: InsightConfig, context: Optional[InsightContext] = None
) -> Optional[Insight]:
    if df.empty:
        return None
    idx = pd.DatetimeIndex(df.index)
    days = (idx.max().normalize() - idx.min().normalize()).days + 1 if len(idx) else 0
    if days < config.advanced.min_days_for_step_check:
        return None
    # Compute overnight import per day and compare halves
    times = utils.local_time_series(idx)
    overnight_mask = utils.time_in_range(
        times,
        utils.parse_time_str(config.advanced.overnight_start),
        utils.parse_time_str(config.advanced.overnight_end),
    )
    dfx = df[overnight_mask].copy()
    if dfx.empty:
        return None
    daily = dfx.groupby(pd.Grouper(freq="1D"))["kwh"].sum().dropna()
    if len(daily) < config.advanced.min_days_for_step_check:
        return None
    mid = len(daily) // 2
    before = float(daily.iloc[:mid].mean()) if mid > 0 else 0.0
    after = float(daily.iloc[mid:].mean()) if mid < len(daily) else 0.0
    bigger = max(before, after)
    smaller = min(before, after)
    change_pct = ((bigger - smaller) / bigger * 100.0) if bigger > 0 else 0.0
    if change_pct >= config.advanced.step_change_pct_threshold:
        direction = "increase" if after > before else "decrease"
        return Insight(
            id="step_change_baseload",
            level="advanced",
            category="data_quality",
            title="Step change in overnight usage",
            message=(
                f"Overnight (base) usage shows a sustained {direction} of about {change_pct:.0f}%. "
                "This can indicate added/removed appliances or issues like a device left running."
            ),
            severity="warning",  # type: ignore[arg-type]
            metrics={
                "change_pct": change_pct,
                "before_kwh_per_night": before,
                "after_kwh_per_night": after,
            },
        )
    return None
