from __future__ import annotations
import pandas as pd
from pandas.tseries.frequencies import to_offset
from zoneinfo import ZoneInfo
from . import canon

def ensure_tz_aware_index(df: pd.DataFrame, tz: str) -> pd.DataFrame:
    if df.index.name != canon.INDEX_NAME:
        raise ValueError(f"Index must be '{canon.INDEX_NAME}', got {df.index.name}")
    if df.index.tz is None:
        df = df.tz_localize(ZoneInfo(tz))
    else:
        df = df.tz_convert(ZoneInfo(tz))
    return df

def infer_cadence_minutes(idx: pd.DatetimeIndex, default: int = canon.DEFAULT_CADENCE_MIN) -> int:
    if len(idx) < 2:
        return default
    # infer on first 200 deltas
    deltas = pd.Series(idx[1: min(len(idx), 200)] - idx[0: min(len(idx)-1, 199)])
    minutes = int(round(deltas.mode().iloc[0].total_seconds() / 60))
    return minutes or default

def month_str(ts: pd.Timestamp) -> str:
    return ts.strftime("%Y-%m")

def frequency_str_from_minutes(minutes: int) -> str:
    return to_offset(f"{minutes}min").freqstr
