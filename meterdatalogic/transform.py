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


def base_from_profile(profile_with_import: pd.DataFrame, cadence_min: int) -> dict:
    """Compute base load from average-day import profile.

    Returns { base_kw, base_kwh_per_day }.
    """
    if profile_with_import.empty:
        return {"base_kw": 0.0, "base_kwh_per_day": 0.0}
    base_interval_kwh = float(profile_with_import["import_total"].min())
    base_kw = base_interval_kwh * (60.0 / cadence_min) if cadence_min else 0.0
    base_kwh_per_day = base_kw * 24.0
    return {"base_kw": float(base_kw), "base_kwh_per_day": float(base_kwh_per_day)}


def window_stats_from_profile(
    profile_with_import: pd.DataFrame,
    windows: list[dict],
    cadence_min: int,
    total_daily_kwh: float | None = None,
) -> dict:
    """Compute avg_kw, kwh_per_day, share for configured windows using average-day profile.

    windows: list of { key, start, end } in HH:MM.
    """

    def hhmm_to_minutes(hhmm: str) -> int:
        h_str, m_str = hhmm.split(":")
        h_int = int(h_str)
        m_int = int(m_str)
        if h_int == 24 and m_int == 0:
            return 24 * 60
        return h_int * 60 + m_int

    total = (
        float(total_daily_kwh)
        if total_daily_kwh is not None
        else float(profile_with_import["import_total"].sum())
    )
    out: dict[str, dict[str, float]] = {}
    for w in windows:
        start_m = hhmm_to_minutes(str(w["start"]))
        end_m = hhmm_to_minutes(str(w["end"]))
        if end_m < start_m:  # wrap
            mask = profile_with_import["slot"].apply(
                lambda s: (hhmm_to_minutes(s) >= start_m)
                or (hhmm_to_minutes(s) < end_m)
            )
        else:
            mask = profile_with_import["slot"].apply(
                lambda s: (hhmm_to_minutes(s) >= start_m)
                and (hhmm_to_minutes(s) < end_m)
            )
        window_kwh = float(profile_with_import.loc[mask, "import_total"].sum())
        window_hours = (
            (end_m - start_m) / 60.0
            if end_m >= start_m
            else ((24 * 60 - start_m) + end_m) / 60.0
        )
        avg_kw = (window_kwh / window_hours) if window_hours > 0 else 0.0
        share = (window_kwh / total * 100.0) if total > 0 else 0.0
        out[str(w["key"])] = {
            "avg_kw": float(avg_kw),
            "kwh_per_day": float(window_kwh),
            "share_of_daily_pct": float(share),
        }
    return out


def peak_from_profile(
    profile_with_import: pd.DataFrame, cadence_min: int
) -> tuple[float, Optional[str]]:
    """Peak kW and time from average-day profile import_total."""
    if profile_with_import.empty:
        return 0.0, None
    peak_interval_kwh = float(profile_with_import["import_total"].max())
    peak_kw = peak_interval_kwh * (60.0 / cadence_min) if cadence_min else 0.0
    idx = int(profile_with_import["import_total"].to_numpy().argmax())
    t = str(profile_with_import.loc[idx, "slot"]) if idx >= 0 else None
    return float(peak_kw), t


# ---------- More generic power-users' APIs ----------


def profile(
    df: CanonFrame,
    *,
    flows: Iterable[str] | None = None,
    by: Literal["slot"] = "slot",
    reducer: Literal["mean", "sum", "max"] = "mean",
    pivot_by: str = "flow",
    slot_fmt: str = "%H:%M",
    include_import_total: bool = True,
    import_flows: Iterable[str] | None = None,
) -> pd.DataFrame:
    """Generic profile builder. Currently supports average-day by 30-min slot.

    - by="slot": groups by formatted local time of day (e.g., HH:MM) and aggregates per `reducer`.
    - pivot_by: column used to pivot (default flow).
    - include_import_total: adds import_total column by summing import flows.
    """
    if by != "slot":
        raise NotImplementedError("profile currently supports by='slot' only")
    s = df.copy()
    if flows:
        s = s[s["flow"].isin(list(flows))]
    # Index is expected tz-aware canonical; using index directly preserves local tz
    s["slot"] = pd.DatetimeIndex(s.index).strftime(slot_fmt)
    g = s.groupby(["slot", pivot_by])
    if reducer == "mean":
        prof = g["kwh"].mean().unstack(pivot_by).fillna(0.0).reset_index()
    elif reducer == "sum":
        prof = g["kwh"].sum().unstack(pivot_by).fillna(0.0).reset_index()
    elif reducer == "max":
        prof = g["kwh"].max().unstack(pivot_by).fillna(0.0).reset_index()
    else:
        raise ValueError(f"Unsupported reducer: {reducer}")
    if include_import_total:
        flow_cols = [c for c in prof.columns if c != "slot"]
        if import_flows:
            cols = [c for c in flow_cols if c in set(import_flows)]
        else:
            cols = [
                c
                for c in flow_cols
                if ("import" in str(c)) or str(c).startswith("grid_")
            ]
            if not cols:
                cols = flow_cols
        prof["import_total"] = prof[cols].select_dtypes(float).sum(axis=1)
    return prof


def period_breakdown(
    df: CanonFrame,
    *,
    freq: Literal["1D", "1MS"],
    flows: Iterable[str] | None = None,
    cadence_min: int | None = None,
    labels: Literal["day", "month"] | None = None,
) -> dict[str, pd.DataFrame]:
    """Compute core per-period tables in one call: total, peaks, avg_interval_kwh.

    Returns a dict with keys: total, peaks, average. Label column is 'day' or 'month'.
    """
    if labels is None:
        labels = "day" if freq == "1D" else "month"

    totals = aggregate(
        df, freq=freq, groupby="flow", pivot=True, value_col="kwh", flows=flows
    ).reset_index()
    totals = totals.rename(columns={"t_start": labels})
    totals[labels] = utils.format_period_label(totals[labels], freq)
    flow_cols = [c for c in totals.columns if c != labels]
    totals["total_kwh"] = totals[flow_cols].select_dtypes(float).sum(axis=1)

    peaks = aggregate(
        df, freq=freq, value_col="kwh", agg="max", flows=flows
    ).reset_index()
    peaks = peaks.rename(columns={"t_start": labels, "kwh": "peak_interval_kwh"})
    peaks[labels] = utils.format_period_label(peaks[labels], freq)

    avg = aggregate(df, freq=freq, metric="kW", stat="mean", flows=flows).reset_index()
    avg = avg.rename(columns={"t_start": labels, "demand_kw": "mean_kw"})
    avg[labels] = utils.format_period_label(avg[labels], freq)
    if cadence_min:
        avg["avg_interval_kwh"] = avg["mean_kw"] * (cadence_min / 60.0)
    else:
        avg["avg_interval_kwh"] = 0.0
    avg = avg[[labels, "avg_interval_kwh"]]

    return {"total": totals, "peaks": peaks, "average": avg}


def top_n_from_profile(
    profile_df: pd.DataFrame,
    *,
    group_by: Literal["hour"] = "hour",
    slot_col: str = "slot",
    value_col: str = "import_total",
    n: int = 4,
    total_value: float | None = None,
) -> dict:
    """Generic top-N reducer from a profile dataframe.

    Currently supports group_by='hour' on slot labels and sums value_col for ranking.
    """
    if group_by != "hour":
        raise NotImplementedError("Only group_by='hour' supported")
    if profile_df.empty:
        return {"labels": [], "value_total": 0.0, "share_pct": 0.0}
    grouped = (
        profile_df.assign(_h=profile_df[slot_col].astype(str).str.slice(0, 2))
        .groupby("_h")[value_col]
        .sum()
        .sort_values(ascending=False)
    )
    labels = list(grouped.head(n).index)
    value_total = float(grouped.head(n).sum())
    denom = (
        float(total_value)
        if total_value is not None
        else float(profile_df[value_col].sum())
    )
    share = (value_total / denom * 100.0) if denom > 0 else 0.0
    return {"labels": labels, "value_total": value_total, "share_pct": float(share)}
