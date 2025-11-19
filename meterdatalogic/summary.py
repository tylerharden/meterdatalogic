from __future__ import annotations
import pandas as pd
from typing import cast

from . import canon, utils, transform
from .types import SummaryPayload, CanonFrame


def summarise(df: CanonFrame) -> SummaryPayload:
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
    per_day_avg = (sum(totals.values()) / days) if days else 0.0

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

    prof = transform.profile24(df)  # average day
    months = transform.groupby_month(df)  # monthly totals per flow
    days_df = transform.groupby_day(df).reset_index()  # day, flows...
    days_df["day"] = days_df["day"].dt.strftime("%Y-%m-%d")

    # Pylance-friendly typed records
    prof_records: list[dict[str, float | str]] = prof.to_dict(orient="records")  # type: ignore[assignment]
    months_records: list[dict[str, float | str]] = months.to_dict(orient="records")  # type: ignore[assignment]
    days_records: list[dict[str, float | str]] = days_df.to_dict(orient="records")  # type: ignore[assignment]

    # Ensure explicit str types for start/end
    start_str: str = str(start) if pd.notna(start) else ""
    end_str: str = str(end) if pd.notna(end) else ""

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
            "energy": {k: float(v) for k, v in totals.items()},
            "per_day_avg_kwh": float(per_day_avg),
            "peaks": peaks,
            "profile24": prof_records,
            "months": months_records,
            "days_series": days_records,
        },
    )
    return payload
