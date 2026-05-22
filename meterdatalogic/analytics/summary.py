from __future__ import annotations
from typing import Literal

import polars as pl

from .. import config
from ..core import transform, utils
from ..core.types import CanonFrame
from .types import SummaryPayload, SummaryPeaks
from . import insights as insights_mod


def _profile_kw_stat(
    profile: pl.DataFrame,
    cadence_min: int,
    *,
    reducer: Literal["min", "max"],
    col: str = "import_total",
) -> tuple[float, str | None]:
    """Return (kW, slot_label) for the min or max interval in a profile column."""
    if profile.is_empty():
        return 0.0, None
    series = profile[col]
    idx = int(series.arg_min() if reducer == "min" else series.arg_max())
    kw = float(series[idx]) * (60.0 / cadence_min) if cadence_min else 0.0
    return float(kw), (str(profile["slot"][idx]) if idx >= 0 else None)


def _top_hours(
    profile: pl.DataFrame,
    *,
    n: int = config.SUMMARY_TOP_N,
    total_value: float | None = None,
) -> dict:
    """Top-N hours by import kWh, grouped from slot labels (HH prefix)."""
    if profile.is_empty():
        return {"labels": [], "value_total": 0.0, "share_pct": 0.0}
    grouped = (
        profile.with_columns(pl.col("slot").cast(pl.String).str.slice(0, 2).alias("_h"))
        .group_by("_h")
        .agg(pl.col("import_total").sum())
        .sort("import_total", descending=True)
    )
    top = grouped.head(n)
    value_total = float(top["import_total"].sum())
    denom = float(total_value) if total_value is not None else float(profile["import_total"].sum())
    share = (value_total / denom * 100.0) if denom > 0 else 0.0
    return {"labels": top["_h"].to_list(), "value_total": value_total, "share_pct": float(share)}


def _to_records(df: pl.DataFrame) -> list[dict]:
    """Return df as a list of dicts, or [] if empty."""
    return df.to_dicts() if not df.is_empty() else []


def _joined_breakdown(bd: dict[str, pl.DataFrame], label_col: str) -> pl.DataFrame:
    """Join peaks and average onto the total table from a period_breakdown result."""
    result = bd["total"]
    if not result.is_empty():
        result = result.join(bd["peaks"], on=label_col, how="left")
        result = result.join(bd["average"], on=label_col, how="left")
    return result


def summarise(
    df: CanonFrame, hemisphere: Literal["northern", "southern"] | None = None
) -> SummaryPayload:
    if hemisphere is None:
        hemisphere = config.DEFAULT_HEMISPHERE

    ts_col = df["t_start"]
    start = ts_col.min()
    end = ts_col.max()
    days = int((end - start).days) + 1 if (start is not None and end is not None) else 0

    cadence = utils.infer_cadence_minutes(ts_col, default=config.DEFAULT_CADENCE_MIN)

    totals = utils.compute_flow_totals(df)
    total_import_kwh = float(sum(totals.get(k, 0.0) for k in totals if "import" in k))
    solar_export_kwh = float(sum(totals.get(k, 0.0) for k in totals if "export" in k))
    per_day_avg = (total_import_kwh / days) if days else 0.0

    if len(df):
        pos = int(df["kwh"].arg_max())
        max_interval_kwh = float(df["kwh"][pos])
        max_interval_time = str(df["t_start"][pos])
    else:
        max_interval_kwh = 0.0
        max_interval_time = None

    peaks: SummaryPeaks = {
        "max_interval_kwh": max_interval_kwh,
        "max_interval_time": max_interval_time,
    }

    prof = transform.profile(df, by="slot", reducer="mean", include_import_total=True)

    daily_bd = transform.period_breakdown(df, freq="1d", cadence_min=cadence, labels="day")
    monthly_bd = transform.period_breakdown(df, freq="1mo", cadence_min=cadence, labels="month")

    seasons_df = transform.seasonal_totals(df, hemisphere=hemisphere)
    if not seasons_df.is_empty() and "flow" in seasons_df.columns:
        seasons_df = seasons_df.pivot(
            index=["season", "year"], on="flow", values="kwh", aggregate_function="sum"
        )

    base_kw, _ = _profile_kw_stat(prof, cadence, reducer="min")
    total_daily_kwh = utils.daily_total_from_profile(prof)
    peak_consumption_kw, peak_time = _profile_kw_stat(prof, cadence, reducer="max")
    topn = _top_hours(prof, total_value=total_daily_kwh)

    payload: SummaryPayload = {  # type: ignore[assignment]
        "meta": {
            "nmis": int(df["nmi"].n_unique()) if "nmi" in df.columns else 0,
            "start": str(start) if start is not None else "",
            "end": str(end) if end is not None else "",
            "cadence_min": cadence,
            "days": days,
            "channels": (
                sorted(df["channel"].unique().to_list()) if "channel" in df.columns else []
            ),
            "flows": sorted(df["flow"].unique().to_list()) if "flow" in df.columns else [],
        },
        "stats": {
            "total_import_kwh": total_import_kwh,
            "solar_export_kwh": solar_export_kwh,
            "per_day_avg_kwh": float(per_day_avg),
            "peak_consumption_kw": float(peak_consumption_kw),
            "peak_time": peak_time,
            "peaks": peaks,
            "base": {
                "base_kw": base_kw,
                "base_kwh_per_day": base_kw * 24.0,
                "share_of_daily_pct": float(
                    (base_kw * 24.0 / total_daily_kwh * 100.0) if total_daily_kwh > 0 else 0.0
                ),
            },
            "windows": transform.window_stats_from_profile(
                prof, config.WINDOWS, cadence, total_daily_kwh
            ),
            "top_hours": {
                "hours": topn.get("labels", []),
                "kwh_total": float(topn.get("value_total", 0.0)),
                "share_of_daily_pct": float(topn.get("share_pct", 0.0)),
            },
        },
        "datasets": {
            "profile24": _to_records(prof),
            "days": {
                "total": _to_records(_joined_breakdown(daily_bd, "day")),
                "peaks": _to_records(daily_bd["peaks"]),
                "average": _to_records(daily_bd["average"]),
            },
            "months": {
                "total": _to_records(_joined_breakdown(monthly_bd, "month")),
                "peaks": _to_records(monthly_bd["peaks"]),
                "average": _to_records(monthly_bd["average"]),
            },
            "seasons": _to_records(seasons_df),
        },
    }

    try:
        _ins = insights_mod.generate_insights(df)
        payload["insights"] = [
            {
                "id": i.id,
                "level": i.level,
                "category": i.category,
                "severity": i.severity,
                "title": i.title,
                "message": i.message,
                "tags": i.tags,
                "metrics": i.metrics,
                "extras": i.extras,
            }
            for i in _ins
        ]
    except Exception:
        pass

    return payload
