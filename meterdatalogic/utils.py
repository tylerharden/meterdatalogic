# meterdatalogic/utils.py
from __future__ import annotations
import numpy as np
import pandas as pd
from zoneinfo import ZoneInfo
from datetime import time as _time
from typing import Literal

from . import canon
from typing import cast
from .types import CanonFrame


def ensure_tz_aware_index(df: pd.DataFrame, tz: str) -> pd.DataFrame:
    if df.index.name != canon.INDEX_NAME:
        raise ValueError(f"Index must be '{canon.INDEX_NAME}', got {df.index.name}")
    idx = pd.DatetimeIndex(df.index)
    if idx.tz is None:
        df = df.tz_localize(ZoneInfo(tz))
    else:
        df = df.tz_convert(ZoneInfo(tz))
    return df


def infer_cadence_minutes(
    idx: pd.DatetimeIndex, default: int = canon.DEFAULT_CADENCE_MIN
) -> int:
    """
    Infer cadence in minutes from a DatetimeIndex, ignoring duplicate timestamps.
    """
    ts = pd.DatetimeIndex(idx).sort_values().unique()
    if len(ts) < 2:
        return int(default)

    diffs = ts[1:] - ts[:-1]
    diffs_min = (diffs / np.timedelta64(1, "s")).to_numpy(dtype=float) / 60.0
    diffs_min = diffs_min[diffs_min > 0]
    if len(diffs_min) == 0:
        return int(default)

    rounded = np.rint(diffs_min).astype(int)
    vals, counts = np.unique(rounded, return_counts=True)
    return int(vals[np.argmax(counts)])


def interval_hours_from_index(idx: pd.DatetimeIndex) -> float:
    cmin = infer_cadence_minutes(idx, default=canon.DEFAULT_CADENCE_MIN)
    return cmin / 60.0


def interval_hours(df: pd.DataFrame) -> float:
    return interval_hours_from_index(pd.DatetimeIndex(df.index))


def safe_localize_series(ts: pd.Series, tz: str) -> pd.Series:
    s = pd.to_datetime(ts, errors="coerce")
    if getattr(s.dt, "tz", None) is None:
        return s.dt.tz_localize(ZoneInfo(tz))
    return s.dt.tz_convert(ZoneInfo(tz))


def parse_time_str(tstr: str) -> _time:
    """Allow '24:00' → '00:00' rollover safely."""
    s = tstr.strip()
    if s == "24:00":
        return _time(0, 0)
    return pd.to_datetime(s, format="%H:%M").time()


def parse_hhmm(s: str) -> pd.Timestamp:
    """HH:MM to a Timestamp on arbitrary date; handles '24:00' like 00:00."""
    t = parse_time_str(s)
    return pd.Timestamp.combine(pd.Timestamp("1970-01-01"), t)


def time_in_range(times: pd.Series, start: _time, end: _time) -> pd.Series:
    """Return mask for times within [start, end). Handles wrap-around."""
    if start < end:
        return (times >= start) & (times < end)
    else:
        # e.g. 21:00 → 05:00 next day
        return (times >= start) | (times < end)


def local_time_series(idx: pd.DatetimeIndex) -> pd.Series:
    """
    Return a Series of local wall-clock times (datetime.time) indexed by idx.
    Assumes idx is tz-aware.
    """
    if idx.tz is None:
        raise ValueError("Index must be tz-aware for local_time_series.")
    # local already; just use .time
    return pd.Series(idx.time, index=idx)


def day_mask(
    idx: pd.DatetimeIndex,
    days: Literal["ALL", "MF", "MS"] = "ALL",
) -> np.ndarray:
    """
    Return a boolean mask for which timestamps fall on the selected days:
      - 'ALL': all days
      - 'MF': Monday–Friday
      - 'MS': Monday–Saturday
    """
    if days == "ALL":
        return np.ones(len(idx), dtype=bool)

    dow = np.asarray(idx.dayofweek)  # Mon=0..Sun=6
    if days == "MF":
        return dow <= 4
    if days == "MS":
        return dow <= 5
    # Fallback: treat as ALL
    return np.ones(len(idx), dtype=bool)


def month_label(ts: pd.Series | pd.DatetimeIndex, tz: str | None = None) -> pd.Series:
    """Return YYYY-MM month labels from a datetime-like Series/Index."""
    if isinstance(ts, pd.DatetimeIndex):
        idx = ts
        if tz and idx.tz is not None:
            idx = idx.tz_convert(tz)
        return pd.Series(idx.strftime("%Y-%m"), index=idx)
    else:
        s = ts
        if tz:
            try:
                if s.dt.tz is not None:
                    s = s.dt.tz_convert(tz)
            except AttributeError:
                pass
        return s.dt.strftime("%Y-%m")


def build_canon_frame(
    idx: pd.DatetimeIndex,
    kwh: np.ndarray | pd.Series,
    *,
    nmi: str | None,
    channel: str,
    flow: str,
    cadence_min: int | None,
) -> pd.DataFrame:
    df = pd.DataFrame(
        {
            "t_start": idx,
            "nmi": nmi,
            "channel": channel,
            "flow": flow,
            "kwh": np.asarray(kwh, dtype=float),
            "cadence_min": cadence_min,
        }
    ).set_index("t_start")
    return df.sort_index()


def empty_canon_frame(tz: str = canon.DEFAULT_TZ) -> CanonFrame:
    """
    Return an empty CanonFrame with the correct tz-aware index and required columns.
    """
    idx = pd.DatetimeIndex([], tz=ZoneInfo(tz), name=canon.INDEX_NAME)
    out = pd.DataFrame(columns=canon.REQUIRED_COLS, index=idx)
    out.__class__ = CanonFrame
    return cast(CanonFrame, out)


def infer_minutes_from_index(
    idx: pd.DatetimeIndex, default: int = canon.DEFAULT_CADENCE_MIN
) -> int:
    """Alias for infer_cadence_minutes: preferred shared helper name."""
    return infer_cadence_minutes(idx, default)
