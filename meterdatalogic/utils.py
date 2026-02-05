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


def infer_cadence_minutes(idx: pd.DatetimeIndex, default: int = canon.DEFAULT_CADENCE_MIN) -> int:
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
    """Parse HH:MM string to datetime.time, handling '24:00' → '00:00' rollover.

    Args:
        tstr: Time string in HH:MM format (e.g., '16:00', '24:00')

    Returns:
        datetime.time object

    Example:
        >>> parse_time_str('16:00')
        datetime.time(16, 0)
        >>> parse_time_str('24:00')  # Wraps to midnight
        datetime.time(0, 0)
    """
    s = tstr.strip()
    if s == "24:00":
        return _time(0, 0)
    return pd.to_datetime(s, format="%H:%M").time()


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
    Return a boolean mask for which timestamps fall on the selected days.

    Args:
        idx: tz-aware DatetimeIndex to filter
        days: Day selection - 'ALL' (all days), 'MF' (Mon-Fri), 'MS' (Mon-Sat)

    Returns:
        Boolean numpy array aligned with idx

    Example:
        >>> idx = pd.date_range('2025-01-01', periods=7, freq='D', tz='UTC')
        >>> mask = day_mask(idx, 'MF')
        >>> # Returns True for Mon-Fri, False for Sat-Sun
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


def format_period_label(ts: pd.Series | pd.DatetimeIndex, freq: str) -> pd.Series | np.ndarray:
    """Format timestamps as period labels (day or month) based on frequency.

    Args:
        ts: DateTime Series or Index to format
        freq: '1D' for daily (YYYY-MM-DD) or '1MS'/'MS' for monthly (YYYY-MM)

    Returns:
        Series or array of formatted strings

    Example:
        >>> format_period_label(pd.date_range('2025-01', periods=3, freq='D'), '1D')
        ['2025-01-01', '2025-01-02', '2025-01-03']
    """
    idx = pd.DatetimeIndex(ts) if not isinstance(ts, pd.DatetimeIndex) else ts
    if freq == "1D":
        return idx.strftime("%Y-%m-%d")
    else:  # Monthly
        result = month_label(idx)
        # Return values to avoid index alignment issues
        return result.values if isinstance(result, pd.Series) else result


def compute_flow_totals(df: pd.DataFrame) -> dict[str, float]:
    """Compute total kWh by flow from canonical DataFrame.

    Args:
        df: Canonical DataFrame with 'flow' and 'kwh' columns

    Returns:
        Dictionary mapping flow names to total kWh

    Example:
        >>> totals = compute_flow_totals(df)
        >>> totals['grid_import']
        1234.56
    """
    if df.empty or "flow" not in df.columns or "kwh" not in df.columns:
        return {}
    return df.groupby("flow")["kwh"].sum().to_dict()


def total_import_export(flow_totals: dict[str, float]) -> tuple[float, float]:
    """Extract import and export totals from flow totals dictionary.

    Args:
        flow_totals: Dictionary of flow names to kWh totals

    Returns:
        Tuple of (total_import_kwh, total_export_kwh)

    Example:
        >>> totals = {'grid_import': 1000, 'grid_export_solar': 200}
        >>> import_kwh, export_kwh = total_import_export(totals)
        >>> import_kwh
        1000.0
    """
    import_flows = [k for k in flow_totals.keys() if "import" in k]
    export_flows = [k for k in flow_totals.keys() if "export" in k]

    total_import = float(sum(flow_totals.get(k, 0.0) for k in import_flows))
    total_export = float(sum(flow_totals.get(k, 0.0) for k in export_flows))

    return total_import, total_export


def daily_total_from_profile(profile: pd.DataFrame) -> float:
    """Compute total daily kWh from an average-day profile with import_total.

    Args:
        profile: DataFrame with 'import_total' column (from transform.profile)

    Returns:
        Total daily kWh as float

    Example:
        >>> prof = transform.profile(df, include_import_total=True)
        >>> daily_kwh = daily_total_from_profile(prof)
    """
    if profile.empty or "import_total" not in profile.columns:
        return 0.0
    return float(profile["import_total"].sum())


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
