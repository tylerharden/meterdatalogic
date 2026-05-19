from __future__ import annotations

from typing import Optional
import pandas as pd

from .types import Insight, InsightContext
from .config import InsightConfig
from ...core.types import CanonFrame
from ...core import transform


def seasonal_variation(
    df: CanonFrame, *, config: InsightConfig, context: Optional[InsightContext] = None
) -> Optional[Insight]:
    if df.empty:
        return None
    monthly = transform.period_breakdown(df, freq="1MS", labels="month")["total"]
    if monthly.empty or len(monthly) < config.intermediate.min_months_required:
        return None
    # Sum grid import across flow columns for warm and cool months
    monthly = monthly.copy()
    monthly["mm"] = monthly["month"].astype(str).str[-2:]
    flow_cols = [c for c in monthly.columns if "import" in str(c)]
    if not flow_cols:
        flow_cols = [c for c in monthly.columns if c not in ("month", "total_kwh", "mm")]
    monthly["import_kwh"] = monthly[flow_cols].select_dtypes(float).sum(axis=1)
    warm = float(
        monthly.loc[monthly["mm"].isin(config.intermediate.warm_months), "import_kwh"].sum()
    )
    cool = float(
        monthly.loc[monthly["mm"].isin(config.intermediate.cool_months), "import_kwh"].sum()
    )
    if warm == 0 and cool == 0:
        return None
    # Compare larger season to smaller
    bigger = max(warm, cool)
    smaller = min(warm, cool)
    diff_pct = ((bigger - smaller) / bigger * 100.0) if bigger > 0 else 0.0
    if diff_pct >= config.intermediate.seasonal_diff_pct_threshold:
        season = "summer" if warm > cool else "winter"
        return Insight(
            id="seasonal_variation",
            level="intermediate",
            category="usage",
            title="Strong seasonal usage difference",
            message=(
                f"Usage is notably higher in {season} (≈{diff_pct:.0f}% difference)."
                " Consider efficiency or shifting peak-time loads in that season."
            ),
            severity="notice",  # type: ignore[arg-type]
            metrics={"diff_pct": float(diff_pct), "warm_kwh": warm, "cool_kwh": cool},
        )
    return None


def tariff_suitability(
    df: CanonFrame, *, config: InsightConfig, context: Optional[InsightContext] = None
) -> Optional[Insight]:
    if context is None or context.pricing is None:
        return None
    pricing = context.pricing
    if pricing.current_plan not in pricing.costs_by_plan:
        return None

    def _annual_total(d: pd.DataFrame) -> float:
        if "total" not in d.columns:
            return float(d.select_dtypes(float).sum(axis=1).sum())
        return float(pd.to_numeric(d["total"], errors="coerce").fillna(0.0).sum())

    costs = {name: _annual_total(df_) for name, df_ in pricing.costs_by_plan.items()}
    if not costs:
        return None
    current_cost = float(costs.get(pricing.current_plan, 0.0))
    if current_cost <= 0:
        return None
    # find best alternative (excluding current)
    best_alt_name = None
    best_alt_cost = None
    for name, val in costs.items():
        if name == pricing.current_plan:
            continue
        if best_alt_cost is None or val < best_alt_cost:
            best_alt_name, best_alt_cost = name, val
    if best_alt_name is None or best_alt_cost is None:
        return None
    saving = current_cost - best_alt_cost
    saving_pct = (saving / current_cost * 100.0) if current_cost > 0 else 0.0
    if (
        saving_pct >= config.intermediate.tariff_saving_pct_threshold
        and saving >= config.intermediate.tariff_saving_min_dollars
    ):
        return Insight(
            id="tariff_suitability",
            level="intermediate",
            category="tariff",
            title="Cheaper tariff identified",
            message=(
                f"Switching from {pricing.current_plan} to {best_alt_name} could save about ${saving:,.0f}/yr (~{saving_pct:.0f}%)."
            ),
            severity="notice",  # type: ignore[arg-type]
            metrics={
                "current_annual_cost": current_cost,
                "best_alt_annual_cost": best_alt_cost,
                "saving_dollars": saving,
                "saving_pct": saving_pct,
            },
        )
    return None


def peak_demand_characteristics(
    df: CanonFrame, *, config: InsightConfig, context: Optional[InsightContext] = None
) -> Optional[Insight]:
    if df.empty:
        return None
    # Use transform.aggregate to apply the demand window, kW conversion, and daily
    # max in one call - avoids duplicating the cadence-to-kW formula inline.
    daily = transform.aggregate(
        df,
        freq="1D",
        metric="kW",
        stat="max",
        window_start=config.intermediate.demand_window_start,
        window_end=config.intermediate.demand_window_end,
    ).dropna()
    if daily.empty or len(daily) < 7:
        return None
    mean_kw = float(daily["demand_kw"].mean())
    p95_kw = float(daily["demand_kw"].quantile(0.95))
    ratio = (p95_kw / mean_kw) if mean_kw > 0 else 0.0
    if ratio >= config.intermediate.spiky_ratio_threshold:
        return Insight(
            id="peak_demand_characteristics",
            level="intermediate",
            category="tariff",
            title="Spiky peak demand",
            message=(
                "Short, sharp peaks in the demand window increase risk under demand tariffs. "
                "Smoothing or shifting peak loads could improve suitability."
            ),
            severity="warning",  # type: ignore[arg-type]
            metrics={
                "mean_peak_kw": mean_kw,
                "p95_peak_kw": p95_kw,
                "spiky_ratio": ratio,
            },
        )
    else:
        return Insight(
            id="peak_demand_characteristics",
            level="intermediate",
            category="tariff",
            title="Stable peak demand profile",
            message=("Peak demand within the window appears relatively stable rather than spiky."),
            severity="info",  # type: ignore[arg-type]
            metrics={
                "mean_peak_kw": mean_kw,
                "p95_peak_kw": p95_kw,
                "spiky_ratio": ratio,
            },
        )
