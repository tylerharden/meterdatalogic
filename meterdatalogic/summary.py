from __future__ import annotations
import pandas as pd
from . import types, canon
from .transform import profile24, groupby_month
from .utils import _infer_minutes_from_index


def summarise(df: pd.DataFrame) -> types.SummaryPayload:
    idx = df.index
    start = idx.min()
    end = idx.max()
    days = int((end - start).days) + 1 if pd.notna(start) and pd.notna(end) else 0

    # Prefer inference from the index (works even if df has multiple flows/channels)
    cadence = _infer_minutes_from_index(idx, default=canon.DEFAULT_CADENCE_MIN)
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

    prof = profile24(df)
    months = groupby_month(df).to_dict(orient="records")

    payload: types.SummaryPayload = {
        "meta": {
            "nmis": int(df["nmi"].nunique()) if "nmi" in df.columns else 0,
            "start": start.isoformat() if pd.notna(start) else "",
            "end": end.isoformat() if pd.notna(end) else "",
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
        "profile24": prof.to_dict(orient="records"),
        "months": months,
    }
    return payload
