from __future__ import annotations
import numpy as np
import pandas as pd
from pandas.tseries.frequencies import to_offset
from zoneinfo import ZoneInfo
from . import canon
from typing import Literal


def _ensure_tz_aware_index(df: pd.DataFrame, tz: str) -> pd.DataFrame:
    if df.index.name != canon.INDEX_NAME:
        raise ValueError(f"Index must be '{canon.INDEX_NAME}', got {df.index.name}")
    if df.index.tz is None:
        df = df.tz_localize(ZoneInfo(tz))
    else:
        df = df.tz_convert(ZoneInfo(tz))
    return df


def _infer_minutes_from_index(idx: pd.DatetimeIndex, default=5) -> int:
    """Infer cadence in minutes from an index, ignoring duplicate timestamps."""
    ts = pd.DatetimeIndex(idx).sort_values().unique()
    if len(ts) < 2:
        return default
    diffs = (ts[1:] - ts[:-1]) / np.timedelta64(1, "m")  # minutes as floats
    diffs = diffs[diffs > 0]  # drop 0-min gaps from duplicates
    if len(diffs) == 0:
        return default
    # mode as int minutes
    vals, counts = np.unique(diffs.astype(int), return_counts=True)
    return int(vals[np.argmax(counts)])


def _attach_cadence_per_group(df: pd.DataFrame) -> pd.DataFrame:
    if not isinstance(df.index, pd.DatetimeIndex):
        raise TypeError("Index must be a DatetimeIndex.")

    gcols = ["nmi", "channel"]

    cad_per_group = (
        df.sort_index()
        .groupby(gcols, observed=True)
        .apply(lambda g: _infer_minutes_from_index(g.index), include_groups=False)
        .rename("cadence_min")
        .reset_index()
    )

    out = (
        df.reset_index()
        .merge(cad_per_group, on=gcols, how="left", validate="many_to_one")
        .set_index("t_start")
        .sort_index()
    )
    out["cadence_min"] = out["cadence_min"].astype(int)
    return out


## Ingestion Utilities


def _auto_rename(df: pd.DataFrame) -> pd.DataFrame:
    new = df.copy()

    # 1) If index is already datetime-like, just name it t_start
    if isinstance(new.index, pd.DatetimeIndex):
        new.index.name = canon.INDEX_NAME
    else:
        # 2) Otherwise try to find a timestamp column and set as index
        cols = {c.lower(): c for c in new.columns}
        tcol = next((cols[k] for k in canon.COMMON_TIMESTAMP_NAMES if k in cols), None)
        if tcol is None:
            raise ValueError(
                "No timestamp column found and index is not datetime. "
                "Expected one of: t_start, timestamp, time, ts, datetime, date."
            )
        new = new.rename(columns={tcol: canon.INDEX_NAME}).set_index(canon.INDEX_NAME)

    # 3) Standardize energy column name if needed
    # (only rename if a candidate exists and 'kwh' isn't already present)
    if "kwh" not in new.columns:
        for candidate in ("kwh", "energy", "value", "consumption"):
            if candidate in df.columns:
                new = new.rename(columns={candidate: "kwh"})
                break

    return new


def _safe_localize_series(ts: pd.Series, tz: str) -> pd.Series:
    s = pd.to_datetime(ts, errors="coerce")
    if getattr(s.dt, "tz", None) is None:
        return s.dt.tz_localize(ZoneInfo(tz))
    return s.dt.tz_convert(ZoneInfo(tz))


## String/View Utilities
def _month_str(ts: pd.Timestamp) -> str:
    return ts.strftime("%Y-%m")


def _frequency_str_from_minutes(minutes: int) -> str:
    return to_offset(f"{minutes}min").freqstr


## Scenario helpers
def _indexer(parent_idx: pd.DatetimeIndex, child_idx: pd.DatetimeIndex) -> np.ndarray:
    """Map positions of child_idx into parent_idx (both tz-aware, unique)."""
    loc = parent_idx.get_indexer(child_idx)
    if (loc < 0).any():
        # shouldn't happen if df is aligned, but guard anyway
        raise ValueError("Child index not aligned with parent index.")
    return loc


def _interval_hours(df: pd.DataFrame) -> float:
    cmin = _infer_minutes_from_index(df.index, default=canon.DEFAULT_CADENCE_MIN)
    return cmin / 60.0


def _collapse_flows(df: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
    """
    Return (import_series_kwh, export_series_kwh) summed per interval.
    Robust to subsets and flow naming like 'grid_export_solar' / 'grid_import'.
    """
    idx_full = df.index  # full timeline
    flows = df["flow"].astype(str)

    # Filter first, then groupby(level=0) so lengths match
    df_imp = df.loc[flows.str.contains("import", na=False)]
    df_exp = df.loc[flows.str.contains("export", na=False)]

    imp = (
        df_imp.groupby(level=0)["kwh"].sum()
        if not df_imp.empty
        else pd.Series(dtype=float)
    )
    exp = (
        df_exp.groupby(level=0)["kwh"].sum()
        if not df_exp.empty
        else pd.Series(dtype=float)
    )

    # Reindex to full index to avoid NA and preserve timeline
    imp = imp.reindex(idx_full, fill_value=0.0).sort_index()
    exp = exp.reindex(idx_full, fill_value=0.0).sort_index()
    return imp, exp


def _mask_days(idx: pd.DatetimeIndex, days: Literal["ALL", "MF", "MS"]) -> np.ndarray:
    if days == "ALL":
        return np.ones(len(idx), dtype=bool)
    dow = idx.dayofweek  # Mon=0..Sun=6
    if days == "MF":
        return (dow <= 4).to_numpy()
    if days == "MS":
        return (dow <= 5).to_numpy()
    return np.ones(len(idx), dtype=bool)


## Transform
def _parse_time_str(tstr: str):
    """Allow '24:00' → '00:00' rollover safely."""
    if tstr.strip() == "24:00":
        tstr = "00:00"
    return pd.to_datetime(tstr, format="%H:%M").time()


def _parse_hhmm(s: str) -> pd.Timestamp:
    return pd.to_datetime("00:00" if s.strip() == "24:00" else s, format="%H:%M")


def _time_in_range(times: pd.Series, start, end):
    """Return mask for times within [start, end). Handles wrap-around."""
    if start < end:
        return (times >= start) & (times < end)
    else:
        # e.g. 21:00 → 05:00 next day
        return (times >= start) | (times < end)
