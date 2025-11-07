from __future__ import annotations
import numpy as np
import pandas as pd
from zoneinfo import ZoneInfo
from datetime import time as _time

from . import canon


def ensure_tz_aware_index(df: pd.DataFrame, tz: str) -> pd.DataFrame:
    if df.index.name != canon.INDEX_NAME:
        raise ValueError(f"Index must be '{canon.INDEX_NAME}', got {df.index.name}")
    if df.index.tz is None:
        df = df.tz_localize(ZoneInfo(tz))
    else:
        df = df.tz_convert(ZoneInfo(tz))
    return df


def infer_minutes_from_index(idx: pd.DatetimeIndex, default=5) -> int:
    """Infer cadence in minutes from an index, ignoring duplicate timestamps."""
    ts = pd.DatetimeIndex(idx).sort_values().unique()
    if len(ts) < 2:
        return default
    diffs = ts[1:] - ts[:-1]  # TimedeltaIndex
    # keep strictly positive and round to nearest minute to avoid 29.999 -> 29
    diffs_min = (diffs / np.timedelta64(1, "s")).to_numpy(dtype=float) / 60.0
    diffs_min = diffs_min[diffs_min > 0]
    if len(diffs_min) == 0:
        return default
    rounded = np.rint(diffs_min).astype(int)
    vals, counts = np.unique(rounded, return_counts=True)
    return int(vals[np.argmax(counts)])


def safe_localize_series(ts: pd.Series, tz: str) -> pd.Series:
    s = pd.to_datetime(ts, errors="coerce")
    if getattr(s.dt, "tz", None) is None:
        return s.dt.tz_localize(ZoneInfo(tz))
    return s.dt.tz_convert(ZoneInfo(tz))


def interval_hours(df: pd.DataFrame) -> float:
    cmin = infer_minutes_from_index(df.index, default=canon.DEFAULT_CADENCE_MIN)
    return cmin / 60.0


def parse_time_str(tstr: str):
    """Allow '24:00' → '00:00' rollover safely."""
    s = tstr.strip()
    if s == "24:00":
        return _time(0, 0)
    return pd.to_datetime(s, format="%H:%M").time()


def parse_hhmm(s: str) -> pd.Timestamp:
    """HH:MM to a Timestamp on arbitrary date; handles '24:00' like 00:00."""
    t = parse_time_str(s)
    return pd.Timestamp.combine(pd.Timestamp("1970-01-01"), t)


def time_in_range(times: pd.Series, start, end):
    """Return mask for times within [start, end). Handles wrap-around."""
    if start < end:
        return (times >= start) & (times < end)
    else:
        # e.g. 21:00 → 05:00 next day
        return (times >= start) | (times < end)


def month_label(ts: pd.Series | pd.DatetimeIndex, tz: str | None = None) -> pd.Series:
    """Return YYYY-MM month labels from a datetime-like Series/Index.

    Avoids Period conversion (which drops tz and emits warnings).
    If tz is provided and the input is tz-aware, values are converted to that
    timezone before labeling.
    """
    if isinstance(ts, pd.DatetimeIndex):
        idx = ts
        if tz and idx.tz is not None:
            idx = idx.tz_convert(tz)
        return idx.strftime("%Y-%m")
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
    """
    Construct a canonical DataFrame block for a single flow over an index.
    """
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
