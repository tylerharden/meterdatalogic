from __future__ import annotations
import pandas as pd

def summarise(df: pd.DataFrame) -> dict:
    """
    Expects df with tz-aware DatetimeIndex and column 'kwh'.
    Returns simple stats for first round of tests.
    """
    if "kwh" not in df.columns:
        raise ValueError("DataFrame must contain 'kwh' column")
    total_kwh = float(df["kwh"].sum())
    days = (df.index.max().date() - df.index.min().date()).days + 1
    avg_daily = total_kwh / days if days > 0 else 0.0
    by_day = df["kwh"].resample("1D").sum()
    min_day = float(by_day.min()) if not by_day.empty else 0.0
    max_day = float(by_day.max()) if not by_day.empty else 0.0
    return {
        "kwh_total": total_kwh,
        "avg_daily_kwh": avg_daily,
        "min_day_kwh": min_day,
        "max_day_kwh": max_day,
        "n_days": int(days),
    }
