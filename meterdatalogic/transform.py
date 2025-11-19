from __future__ import annotations
import pandas as pd
from typing import Literal, Iterable, Optional, Sequence

from . import utils
from .types import CanonFrame


def _filter_range(
    df: CanonFrame,
    start: Optional[pd.Timestamp] = None,
    end: Optional[pd.Timestamp] = None,
) -> pd.DataFrame:
    return df.loc[start:end] if (start is not None or end is not None) else df


def _time_window_mask(
    idx: pd.DatetimeIndex,
    *,
    start: str,
    end: str,
    days: Literal["ALL", "MF", "MS"] = "ALL",
) -> pd.Series:
    """Combined day-of-week and time-of-day mask for a tz-aware index."""
    daymask = utils.day_mask(idx, days)
    start_t = utils.parse_time_str(start)
    end_t = utils.parse_time_str(end)
    times = utils.local_time_series(idx)
    timemask = utils.time_in_range(times, start_t, end_t)
    return pd.Series(daymask & timemask, index=idx)


def _assign_time_bands(idx: pd.DatetimeIndex, bands: Iterable[dict]) -> pd.Series:
    """
    Assign each timestamp to a named time-of-day band.
    bands: iterable of dicts with keys {"name","start","end"} in HH:MM ("24:00" supported).
    Returns a Series indexed by idx with band names or 'unassigned'.
    """
    times = utils.local_time_series(idx)
    assigned = pd.Series(index=idx, dtype="object")
    for band in bands:
        start = utils.parse_time_str(str(band["start"]))
        end = utils.parse_time_str(str(band["end"]))
        mask = utils.time_in_range(times, start, end)
        assigned[mask] = str(band["name"])
    return assigned.fillna("unassigned")


def _compute_power_from_energy(
    df: pd.DataFrame, *, energy_col: str = "kwh"
) -> pd.Series:
    """Convert per-interval energy (kWh) to power (kW) using cadence_min."""
    factor = 60.0 / df["cadence_min"].astype(float)
    return (df[energy_col].astype(float) * factor).rename("kW")


def aggregate(
    df: CanonFrame,
    *,
    freq: str | None,
    value_col: str = "kwh",
    agg: str = "sum",
    groupby: str | Sequence[str] | None = None,
    pivot: bool = False,
    flows: Iterable[str] | None = None,
    # Optional window filter (time-of-day + day-of-week)
    window_start: str | None = None,
    window_end: str | None = None,
    window_days: Literal["ALL", "MF", "MS"] = "ALL",
    metric: Literal["kWh", "kW"] = "kWh",
    stat: Literal["max", "mean", "sum"] = "max",
    out_col: Optional[str] = None,
    label: Literal["left", "right"] = "left",
    closed: Literal["left", "right"] = "left",
) -> pd.DataFrame:
    """
    Unified aggregation helper for resampling and grouping.

    - Optionally filters to specific `flows`.
    - Optionally applies a day/time window using `window_start`/`window_end` and `window_days`.
    - Supports deriving power (kW) from per-interval energy (kWh) when `metric="kW"`.
    - If `freq` is provided, resamples to that cadence before aggregating.
      If `freq` is None, aggregates over the existing intervals.
    - If `groupby` is provided, groups by those column(s) in addition to time.
    - If `pivot=True`, columns are pivoted by the group keys; otherwise returns tidy rows.

    Returns a DataFrame whose index or column `t_start` reflects the time period when `freq` is set;
    otherwise returns grouped rows without resampling.
    """
    if not isinstance(df.index, pd.DatetimeIndex):
        raise TypeError("aggregate requires a DatetimeIndex index.")

    s = df.copy()
    if flows:
        s = s[s["flow"].isin(list(flows))]
    if s.empty:
        # shape depends on pivot/grouping; return minimal structure
        if pivot and groupby:
            return pd.DataFrame(index=pd.DatetimeIndex([], name="t_start"))
        return pd.DataFrame(columns=["t_start", out_col or value_col])

    # optional window filter
    if window_start is not None and window_end is not None:
        mask = _time_window_mask(
            pd.DatetimeIndex(s.index),
            start=window_start,
            end=window_end,
            days=window_days,
        )
        s = s[mask.values]
        if s.empty:
            if pivot and groupby:
                return pd.DataFrame(index=pd.DatetimeIndex([], name="t_start"))
            return pd.DataFrame(columns=["t_start", out_col or value_col])

    # choose the base series to aggregate
    if metric == "kW":
        base = _compute_power_from_energy(s, energy_col=value_col)
        base_name = out_col or "demand_kw"
    else:
        base = s[value_col].astype(float)
        base_name = out_col or value_col

    # helper for applying aggregation function name
    def _apply_agg(x: pd.Series, how: str):
        if how == "max":
            return x.max()
        if how == "mean":
            return x.mean()
        if how == "sum":
            return x.sum()
        # fall back to pandas agg by name
        return getattr(x, how)()

    grp_cols: list[str] = []
    if groupby is not None:
        grp_cols = [groupby] if isinstance(groupby, str) else list(groupby)

    if freq is None:
        # Aggregate without resampling: group by provided keys only
        if grp_cols:
            out = (
                s.assign(_val=base)
                .groupby(grp_cols, observed=False)["_val"]
                .apply(lambda x: _apply_agg(x, stat if metric == "kW" else agg))
            )
            out = out.reset_index().rename(columns={"_val": base_name})
        else:
            out = pd.DataFrame(
                {base_name: [_apply_agg(base, stat if metric == "kW" else agg)]}
            )
        return out

    # With resampling
    if grp_cols:
        d = s.assign(_val=base)
        # group then resample
        res = (
            d.groupby(grp_cols, observed=False)
            .resample(freq, label=label, closed=closed)["_val"]
            .apply(lambda x: _apply_agg(x, stat if metric == "kW" else agg))
        )
        if pivot:
            out = res.unstack(grp_cols).rename_axis("t_start").sort_index()
            # ensure float fill on empty
            out = out.fillna(0.0)
        else:
            out = res.reset_index().rename(columns={"_val": base_name})
            return out
    else:
        # no group columns, pure resample
        res = base.resample(freq, label=label, closed=closed)
        if metric == "kW":
            series = (
                res.max()
                if stat == "max"
                else (res.mean() if stat == "mean" else res.sum())
            )
        else:
            series = res.agg(agg)
        out = pd.DataFrame({base_name: series})

    # ensure out is a DataFrame (res.unstack or other ops may yield a Series)
    if isinstance(out, pd.Series):
        out = out.to_frame(name=base_name)

    return out


def tou_bins(
    df: pd.DataFrame,
    bands: Iterable[dict],
    *,
    out_freq: str = "1MS",
    flows: Iterable[str] | None = ("grid_import",),
    value_col: str = "kwh",
) -> pd.DataFrame:
    """
    Aggregate energy into named time-of-use (TOU) bands.

    This is the consolidated API for TOU aggregation. It assigns each
    timestamp to a band using `bands` and then aggregates `value_col`
    to the requested `out_freq` (e.g. monthly `1MS`). The returned
    frame contains a `month` column (formatted via `utils.month_label`)
    plus one column per band name.
    """
    s = df.copy()
    if flows:
        s = s[s["flow"].isin(list(flows))]
    if s.empty:
        names = [str(b["name"]) for b in bands]
        # return empty frame with expected columns
        return pd.DataFrame(columns=["month", *names])

    s["band"] = _assign_time_bands(pd.DatetimeIndex(s.index), bands).reindex(s.index)
    out = (
        s.reset_index()
        .groupby(["band", pd.Grouper(key="t_start", freq=out_freq)])[value_col]
        .sum()
        .unstack("band")
        .fillna(0.0)
        .reset_index()
    )

    out = out.rename(columns={"t_start": "month"})
    out["month"] = utils.month_label(out["month"])
    return out
