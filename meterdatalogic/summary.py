from __future__ import annotations
import pandas as pd
from . import types, canon
from .transform import profile24, groupby_month

def summarize(df: pd.DataFrame) -> types.SummaryPayload:
    idx = df.index
    start = idx.min()
    end = idx.max()
    days = int((end - start).days) + 1 if pd.notna(start) and pd.notna(end) else 0
    cadence = int(df["cadence_min"].iloc[0]) if len(df) else canon.DEFAULT_CADENCE_MIN

    # totals by flow
    totals = df.groupby("flow")["kwh"].sum().to_dict()
    per_day_avg = (sum(totals.values()) / days) if days else 0.0

    # peaks
    max_row = df.loc[df["kwh"].idxmax()] if len(df) else None
    peaks = {
        "max_interval_kwh": float(max_row["kwh"]) if max_row is not None else 0.0,
        "max_interval_time": str(df["kwh"].idxmax()) if len(df) else None,
    }

    # profile24 & months
    prof = profile24(df)
    months = groupby_month(df).to_dict(orient="records")

    payload: types.SummaryPayload = {
        "meta": {
            "nmis": int(df["nmi"].nunique()) if "nmi" in df.columns else 0,
            "start": start.isoformat() if pd.notna(start) else "",
            "end": end.isoformat() if pd.notna(end) else "",
            "cadence_min": cadence,
            "days": days,
        },
        "energy": {k: float(v) for k, v in totals.items()},
        "per_day_avg_kwh": float(per_day_avg),
        "peaks": peaks,
        "profile24": prof.to_dict(orient="records"),
        "months": months,
    }
    return payload
