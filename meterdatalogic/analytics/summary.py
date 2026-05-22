from __future__ import annotations
from typing import Literal

from .. import config
from ..core import transform, utils
from ..core.types import CanonFrame
from .types import SummaryPayload
from . import insights as insights_mod


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
    total_import_kwh, solar_export_kwh = utils.total_import_export(totals)
    per_day_avg = (total_import_kwh / days) if days else 0.0

    if len(df):
        pos = int(df["kwh"].arg_max())
        max_interval_kwh = float(df["kwh"][pos])
        max_interval_time = str(df["t_start"][pos])
    else:
        max_interval_kwh = 0.0
        max_interval_time = None

    peaks = {
        "max_interval_kwh": max_interval_kwh,
        "max_interval_time": max_interval_time,
    }

    prof = transform.profile(df, by="slot", reducer="mean", include_import_total=True)

    daily_bd = transform.period_breakdown(df, freq="1D", cadence_min=cadence, labels="day")
    monthly_bd = transform.period_breakdown(df, freq="1MS", cadence_min=cadence, labels="month")
    days_df = daily_bd["total"]
    months_df = monthly_bd["total"]

    if not days_df.is_empty():
        days_df = days_df.join(daily_bd["peaks"], on="day", how="left")
        days_df = days_df.join(daily_bd["average"], on="day", how="left")
    if not months_df.is_empty():
        months_df = months_df.join(monthly_bd["peaks"], on="month", how="left")
        months_df = months_df.join(monthly_bd["average"], on="month", how="left")

    prof_records: list[dict] = prof.to_dicts()
    days_total_records: list[dict] = days_df.to_dicts() if not days_df.is_empty() else []
    days_peaks_records: list[dict] = (
        daily_bd["peaks"].to_dicts() if not daily_bd["peaks"].is_empty() else []
    )
    days_avg_records: list[dict] = (
        daily_bd["average"].to_dicts() if not daily_bd["average"].is_empty() else []
    )
    months_total_records: list[dict] = months_df.to_dicts() if not months_df.is_empty() else []
    months_peaks_records: list[dict] = (
        monthly_bd["peaks"].to_dicts() if not monthly_bd["peaks"].is_empty() else []
    )
    months_avg_records: list[dict] = (
        monthly_bd["average"].to_dicts() if not monthly_bd["average"].is_empty() else []
    )

    seasons_df = transform.aggregate(
        df,
        freq="1MS",
        groupby=["season", "flow"],
        hemisphere=hemisphere,
        pivot=False,
        value_col="kwh",
        agg="sum",
    )
    if not seasons_df.is_empty() and "flow" in seasons_df.columns:
        seasons_df = seasons_df.pivot(
            index=["season", "year"], on="flow", values="kwh", aggregate_function="sum"
        )

    seasons_records: list[dict] = seasons_df.to_dicts() if not seasons_df.is_empty() else []

    start_str: str = str(start) if start is not None else ""
    end_str: str = str(end) if end is not None else ""

    base_dict = transform.base_from_profile(prof, cadence)
    total_daily_kwh = utils.daily_total_from_profile(prof)
    windows_stats = transform.window_stats_from_profile(
        prof, config.WINDOWS, cadence, total_daily_kwh
    )
    peak_consumption_kw, peak_time = transform.peak_from_profile(prof, cadence)
    topn = transform.top_n_from_profile(prof, n=config.SUMMARY_TOP_N, total_value=total_daily_kwh)

    payload: SummaryPayload = {  # type: ignore[assignment]
        "meta": {
            "nmis": int(df["nmi"].n_unique()) if "nmi" in df.columns else 0,
            "start": start_str,
            "end": end_str,
            "cadence_min": cadence,
            "days": days,
            "channels": (
                sorted(df["channel"].unique().to_list()) if "channel" in df.columns else []
            ),
            "flows": sorted(df["flow"].unique().to_list()) if "flow" in df.columns else [],
        },
        "stats": {
            "total_import_kwh": total_import_kwh,
            "per_day_avg_kwh": float(per_day_avg),
            "peak_consumption_kw": float(peak_consumption_kw),
            "peak_time": peak_time,
            "solar_export_kwh": solar_export_kwh,
            "peaks": peaks,
            "base": {
                "base_kw": base_dict.get("base_kw", 0.0),
                "base_kwh_per_day": base_dict.get("base_kwh_per_day", 0.0),
                "share_of_daily_pct": float(
                    (base_dict.get("base_kwh_per_day", 0.0) / total_daily_kwh * 100.0)
                    if total_daily_kwh > 0
                    else 0.0
                ),
            },
            "windows": windows_stats,
            "top_hours": {
                "hours": topn.get("labels", []),
                "kwh_total": float(topn.get("value_total", 0.0)),
                "share_of_daily_pct": float(topn.get("share_pct", 0.0)),
            },
        },
        "datasets": {
            "profile24": prof_records,
            "days": {
                "total": days_total_records,
                "peaks": days_peaks_records,
                "average": days_avg_records,
            },
            "months": {
                "total": months_total_records,
                "peaks": months_peaks_records,
                "average": months_avg_records,
            },
            "seasons": seasons_records,
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
