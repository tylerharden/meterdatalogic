from __future__ import annotations
import pandas as pd
from typing import cast

from . import canon, utils, transform
from .types import SummaryPayload, CanonFrame


def summarise(df: CanonFrame) -> SummaryPayload:
    # Configure windows here for easy adjustment
    WINDOWS = [
        {"key": "overnight", "start": "00:00", "end": "05:00"},
        {"key": "morning", "start": "05:00", "end": "09:00"},
        {"key": "daytime", "start": "09:00", "end": "17:00"},
        {"key": "evening", "start": "17:00", "end": "24:00"},
    ]
    idx = df.index
    start = idx.min()
    end = idx.max()
    days = int((end - start).days) + 1 if pd.notna(start) and pd.notna(end) else 0

    cadence = utils.infer_cadence_minutes(
        pd.DatetimeIndex(idx), default=canon.DEFAULT_CADENCE_MIN
    )
    cadence = int(cadence)

    # totals by flow
    totals = df.groupby("flow")["kwh"].sum().to_dict()
    total_energy_kwh = float(sum(totals.values()))
    per_day_avg = (total_energy_kwh / days) if days else 0.0

    if len(df):
        pos = int(df["kwh"].to_numpy().argmax())
        max_interval_kwh = float(df["kwh"].iloc[pos])
        max_interval_time = df.index[pos].isoformat()
    else:
        max_interval_kwh = 0.0
        max_interval_time = None

    peaks = {
        "max_interval_kwh": max_interval_kwh,
        "max_interval_time": max_interval_time,
    }

    # Average-day profile (slot) with import_total
    prof = transform.profile(df, by="slot", reducer="mean", include_import_total=True)

    # Monthly and daily energy by flow (pivoted columns)
    # Daily and monthly breakdowns
    daily_bd = transform.period_breakdown(
        df, freq="1D", cadence_min=cadence, labels="day"
    )
    monthly_bd = transform.period_breakdown(
        df, freq="1MS", cadence_min=cadence, labels="month"
    )
    days_df = daily_bd["total"]
    months_df = monthly_bd["total"]

    # Enrich daily/monthly frames with total/average/peak columns
    # Average is per-interval average using inferred cadence and covered periods
    intervals_per_day = int(round(1440 / cadence)) if cadence else 0

    # Merge peaks/average columns from breakdowns
    if not days_df.empty:
        days_df = days_df.merge(daily_bd["peaks"], on="day", how="left")
        days_df = days_df.merge(daily_bd["average"], on="day", how="left")

    if not months_df.empty:
        months_df = months_df.merge(monthly_bd["peaks"], on="month", how="left")
        months_df = months_df.merge(monthly_bd["average"], on="month", how="left")

    # Pylance-friendly typed records
    prof_records: list[dict[str, float | str]] = prof.to_dict(orient="records")  # type: ignore[assignment]
    # Split days/months into separate lists for total/peaks/average
    days_total_records: list[dict[str, float | str]] = days_df.to_dict(orient="records") if not days_df.empty else []  # type: ignore[assignment]
    days_peaks_records: list[dict[str, float | str]] = daily_bd["peaks"].to_dict(orient="records") if not daily_bd["peaks"].empty else []  # type: ignore[assignment]
    days_avg_records: list[dict[str, float | str]] = daily_bd["average"].to_dict(orient="records") if not daily_bd["average"].empty else []  # type: ignore[assignment]

    months_total_records: list[dict[str, float | str]] = months_df.to_dict(orient="records") if not months_df.empty else []  # type: ignore[assignment]
    months_peaks_records: list[dict[str, float | str]] = monthly_bd["peaks"].to_dict(orient="records") if not monthly_bd["peaks"].empty else []  # type: ignore[assignment]
    months_avg_records: list[dict[str, float | str]] = monthly_bd["average"].to_dict(orient="records") if not monthly_bd["average"].empty else []  # type: ignore[assignment]

    # Ensure explicit str types for start/end
    start_str: str = str(start) if pd.notna(start) else ""
    end_str: str = str(end) if pd.notna(end) else ""

    # Compute stats using transform helpers
    base_dict = transform.base_from_profile(prof, cadence)
    total_daily_kwh = float(prof["import_total"].sum()) if len(prof) else 0.0
    windows_stats = transform.window_stats_from_profile(
        prof, WINDOWS, cadence, total_daily_kwh
    )
    peak_consumption_kw, peak_time = transform.peak_from_profile(prof, cadence)
    topn = transform.top_n_from_profile(prof, n=4, total_value=total_daily_kwh)

    payload: SummaryPayload = cast(
        SummaryPayload,
        {
            "meta": {
                "nmis": int(df["nmi"].nunique()) if "nmi" in df.columns else 0,
                "start": start_str,
                "end": end_str,
                "cadence_min": cadence,
                "days": days,
                "channels": (
                    sorted(df["channel"].unique()) if "channel" in df.columns else []
                ),
                "flows": sorted(df["flow"].unique()) if "flow" in df.columns else [],
            },
            "stats": {
                "total_energy_kwh": total_energy_kwh,
                "per_day_avg_kwh": float(per_day_avg),
                "peak_consumption_kw": float(peak_consumption_kw),
                "peak_time": peak_time,
                "peaks": peaks,
                "base": {
                    "base_kw": base_dict.get("base_kw", 0.0),
                    "base_kwh_per_day": base_dict.get("base_kwh_per_day", 0.0),
                    "share_of_daily_pct": float(
                        (
                            (base_dict.get("base_kwh_per_day", 0.0) / total_daily_kwh)
                            * 100.0
                        )
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
            },
        },
    )
    return payload
