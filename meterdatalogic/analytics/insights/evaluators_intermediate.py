from __future__ import annotations

from typing import Optional
import polars as pl

from .types import Insight, InsightContext
from .config import InsightConfig
from ...core.types import CanonFrame
from ...core import transform


def seasonal_variation(
    df: CanonFrame, *, config: InsightConfig, context: Optional[InsightContext] = None
) -> Optional[Insight]:
    if df.is_empty():
        return None
    monthly = transform.period_breakdown(df, freq="1mo", labels="month")["total"]
    if monthly.is_empty() or len(monthly) < config.intermediate.min_months_required:
        return None

    monthly = monthly.with_columns(pl.col("month").str.slice(-2).alias("mm"))
    flow_cols = [c for c in monthly.columns if "import" in str(c) and c not in ("month", "mm")]
    if not flow_cols:
        flow_cols = [c for c in monthly.columns if c not in ("month", "total_kwh", "mm")]

    float_cols = [
        c for c in flow_cols if monthly[c].dtype in (pl.Float64, pl.Float32, pl.Int64, pl.Int32)
    ]
    monthly = monthly.with_columns(
        pl.sum_horizontal([pl.col(c).fill_null(0.0) for c in float_cols]).alias("import_kwh")
    )

    warm = float(
        monthly.filter(pl.col("mm").is_in(config.intermediate.warm_months))["import_kwh"].sum()
    )
    cool = float(
        monthly.filter(pl.col("mm").is_in(config.intermediate.cool_months))["import_kwh"].sum()
    )

    if warm == 0 and cool == 0:
        return None
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
                f"Usage is notably higher in {season} (≈{diff_pct:.0f}% difference). "
                "Consider efficiency or shifting peak-time loads in that season."
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

    def _annual_total(d: pl.DataFrame) -> float:
        if d.is_empty():
            return 0.0
        if "total" in d.columns:
            return float(d["total"].fill_null(0.0).sum())
        num_cols = [
            c for c in d.columns if d[c].dtype in (pl.Float64, pl.Float32, pl.Int64, pl.Int32)
        ]
        return float(sum(d[c].sum() for c in num_cols))

    costs = {name: _annual_total(df_) for name, df_ in pricing.costs_by_plan.items()}
    if not costs:
        return None
    current_cost = float(costs.get(pricing.current_plan, 0.0))
    if current_cost <= 0:
        return None

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
                f"Switching from {pricing.current_plan} to {best_alt_name} could save "
                f"about ${saving:,.0f}/yr (~{saving_pct:.0f}%)."
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
    if df.is_empty():
        return None
    daily = transform.demand_window(
        df,
        freq="1d",
        stat="max",
        window_start=config.intermediate.demand_window_start,
        window_end=config.intermediate.demand_window_end,
    )
    if daily.is_empty() or len(daily) < 7:
        return None
    demand_col = "demand_kw"
    if demand_col not in daily.columns:
        return None
    vals = daily[demand_col].drop_nulls()
    if vals.is_empty():
        return None
    mean_kw = float(vals.mean())
    p95_kw = float(vals.quantile(0.95, interpolation="linear"))
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
            metrics={"mean_peak_kw": mean_kw, "p95_peak_kw": p95_kw, "spiky_ratio": ratio},
        )
    return Insight(
        id="peak_demand_characteristics",
        level="intermediate",
        category="tariff",
        title="Stable peak demand profile",
        message="Peak demand within the window appears relatively stable rather than spiky.",
        severity="info",  # type: ignore[arg-type]
        metrics={"mean_peak_kw": mean_kw, "p95_peak_kw": p95_kw, "spiky_ratio": ratio},
    )
