"""Time-series transformations on CanonFrame meter data.

All public functions in this module take a CanonFrame as their primary input and
return a polars DataFrame. They do not mutate the input.

Functions:
    filter_time_window  — filter rows to a time-of-day / day-of-week window
    aggregate           — resample kWh values over time buckets
    demand_window       — convert kWh → kW and aggregate per period
    seasonal_totals     — aggregate kWh grouped by season, year, and flow
    tou_bins            — aggregate kWh into named time-of-use bands
    profile             — build an average-day slot profile
    window_stats_from_profile — compute avg_kw / kwh / share for time windows
    period_breakdown    — per-day or per-month totals, peaks, and averages
"""

from __future__ import annotations
import polars as pl
from typing import Literal, Iterable, Sequence

from . import utils
from .types import CanonFrame


# Season definitions by hemisphere
SEASON_DEFINITIONS = {
    "northern": {
        "Winter": [12, 1, 2],
        "Spring": [3, 4, 5],
        "Summer": [6, 7, 8],
        "Autumn": [9, 10, 11],
    },
    "southern": {
        "Summer": [12, 1, 2],
        "Autumn": [3, 4, 5],
        "Winter": [6, 7, 8],
        "Spring": [9, 10, 11],
    },
}

# Pandas-style → polars duration strings
_FREQ_MAP = {
    "1MS": "1mo",
    "MS": "1mo",
    "1D": "1d",
    "D": "1d",
    "1h": "1h",
    "h": "1h",
    "30min": "30m",
    "30T": "30m",
}


def _to_polars_freq(freq: str) -> str:
    return _FREQ_MAP.get(freq, freq)


def _time_window_mask(
    t_start: pl.Series,
    *,
    start: str,
    end: str,
    days: Literal["ALL", "MF", "MS"] = "ALL",
) -> pl.Series:
    """Combined day-of-week and time-of-day mask for a tz-aware Datetime Series."""
    daymask = utils.day_mask(t_start, days)
    start_t = utils.parse_time_str(start)
    end_t = utils.parse_time_str(end)
    timemask = utils.time_in_range(t_start, start_t, end_t)
    return daymask & timemask


def filter_time_window(
    df: CanonFrame,
    *,
    start: str,
    end: str,
    days: Literal["ALL", "MF", "MS"] = "ALL",
) -> CanonFrame:
    """Filter rows to those within the given time-of-day (and optionally day-of-week) window."""
    if "t_start" not in df.columns:
        raise TypeError("filter_time_window requires a 't_start' column.")
    return df.filter(_time_window_mask(df["t_start"], start=start, end=end, days=days))


def _assign_time_bands(t_start: pl.Series, bands: Iterable[dict]) -> pl.Series:
    """Assign each timestamp to a named band. Unmatched slots → 'unassigned'."""
    result = ["unassigned"] * len(t_start)
    for band in bands:
        start_t = utils.parse_time_str(str(band["start"]))
        end_t = utils.parse_time_str(str(band["end"]))
        name = str(band["name"])
        for i, m in enumerate(utils.time_in_range(t_start, start_t, end_t).to_list()):
            if m:
                result[i] = name
    return pl.Series(result, dtype=pl.String)


def _compute_power_from_energy(df: pl.DataFrame, *, energy_col: str = "kwh") -> pl.Series:
    """Convert per-interval energy (kWh) to power (kW) using cadence_min."""
    factor = 60.0 / df["cadence_min"].cast(pl.Float64)
    return (df[energy_col].cast(pl.Float64) * factor).rename("kW")


def _agg_expr(col: str, how: str) -> pl.Expr:
    """Return a polars aggregation expression for the given strategy."""
    if how == "max":
        return pl.col(col).max()
    if how == "mean":
        return pl.col(col).mean()
    return pl.col(col).sum()


def _resample_val(
    s: pl.DataFrame,
    *,
    freq: str | None,
    grp_cols: list[str],
    stat: str,
    out_col: str,
    closed: Literal["left", "right"] = "left",
) -> pl.DataFrame:
    """Resample a pre-computed '_val' column by freq + optional group columns.

    Handles three paths: no-resample (freq=None), grouped resample, plain resample.
    Does not support pivot — callers handle that themselves.
    """
    if freq is None:
        if grp_cols:
            return s.group_by(grp_cols).agg(_agg_expr("_val", stat).alias(out_col))
        agg_val = float(
            s["_val"].max()
            if stat == "max"
            else (s["_val"].mean() if stat == "mean" else s["_val"].sum())
        )
        return pl.DataFrame({out_col: [agg_val]})
    every = _to_polars_freq(freq)
    if grp_cols:
        return (
            s.sort("t_start")
            .group_by_dynamic("t_start", every=every, group_by=grp_cols, closed=closed)
            .agg(_agg_expr("_val", stat).alias(out_col))
            .sort("t_start")
        )
    return (
        s.sort("t_start")
        .group_by_dynamic("t_start", every=every, closed=closed)
        .agg(_agg_expr("_val", stat).alias(out_col))
        .sort("t_start")
    )


def aggregate(
    df: CanonFrame,
    *,
    freq: str | None,
    value_col: str = "kwh",
    agg: str = "sum",
    groupby: str | Sequence[str] | None = None,
    pivot: bool = False,
    flows: Iterable[str] | None = None,
    closed: Literal["left", "right"] = "left",
) -> pl.DataFrame:
    """
    Resample or group kWh values over time periods.

    For kW demand calculations use demand_window() instead.
    For seasonal grouping use seasonal_totals() instead.
    """
    if "t_start" not in df.columns:
        raise TypeError("aggregate requires a 't_start' column.")

    s = df
    if flows:
        s = s.filter(pl.col("flow").is_in(list(flows)))
    if s.is_empty():
        if pivot and groupby:
            return pl.DataFrame({"t_start": pl.Series([], dtype=pl.Datetime("us"))})
        return pl.DataFrame({"t_start": pl.Series([], dtype=pl.Datetime("us")), value_col: []})

    s = s.with_columns(s[value_col].cast(pl.Float64).alias("_val"))

    grp_cols: list[str] = []
    if groupby is not None:
        grp_cols = [groupby] if isinstance(groupby, str) else list(groupby)

    if pivot and grp_cols and freq is not None:
        every = _to_polars_freq(freq)
        res = (
            s.sort("t_start")
            .group_by_dynamic("t_start", every=every, group_by=grp_cols, closed=closed)
            .agg(_agg_expr("_val", agg).alias(value_col))
        )
        return (
            res.pivot(index="t_start", on=grp_cols[0], values=value_col, aggregate_function="sum")
            .fill_null(0.0)
            .sort("t_start")
        )

    return _resample_val(
        s, freq=freq, grp_cols=grp_cols, stat=agg, out_col=value_col, closed=closed
    )


def demand_window(
    df: CanonFrame,
    *,
    freq: str | None,
    window_start: str | None = None,
    window_end: str | None = None,
    window_days: Literal["ALL", "MF", "MS"] = "ALL",
    stat: Literal["max", "mean", "sum"] = "max",
    flows: Iterable[str] | None = None,
    groupby: str | Sequence[str] | None = None,
    out_col: str = "demand_kw",
    closed: Literal["left", "right"] = "left",
) -> pl.DataFrame:
    """
    Convert interval kWh to kW and aggregate per period, with an optional time-window pre-filter.

    Returns a DataFrame with t_start and <out_col> columns (or groupby cols when freq=None).
    Typical use: monthly peak demand over a pricing window (e.g. 16:00\u201321:00 Mon\u2013Fri).
    """
    if "t_start" not in df.columns:
        raise TypeError("demand_window requires a 't_start' column.")

    s = df
    if flows:
        s = s.filter(pl.col("flow").is_in(list(flows)))
    if s.is_empty():
        return pl.DataFrame({"t_start": pl.Series([], dtype=pl.Datetime("us")), out_col: []})

    if window_start is not None and window_end is not None:
        mask = _time_window_mask(s["t_start"], start=window_start, end=window_end, days=window_days)
        s = s.filter(mask)
        if s.is_empty():
            return pl.DataFrame({"t_start": pl.Series([], dtype=pl.Datetime("us")), out_col: []})

    s = s.with_columns(_compute_power_from_energy(s).alias("_val"))

    grp_cols: list[str] = []
    if groupby is not None:
        grp_cols = [groupby] if isinstance(groupby, str) else list(groupby)

    return _resample_val(s, freq=freq, grp_cols=grp_cols, stat=stat, out_col=out_col, closed=closed)


def seasonal_totals(
    df: CanonFrame,
    *,
    hemisphere: Literal["northern", "southern"],
    flows: Iterable[str] | None = None,
    value_col: str = "kwh",
    agg: str = "sum",
) -> pl.DataFrame:
    """
    Aggregate kWh totals grouped by season, year, and flow.

    Returns long-format (season, year, flow, <value_col>) sorted in calendar season order.
    December is assigned to the following year's season (e.g. Dec 2024 → Summer 2025).
    """
    if "t_start" not in df.columns:
        raise TypeError("seasonal_totals requires a 't_start' column.")

    s = df
    if flows:
        s = s.filter(pl.col("flow").is_in(list(flows)))
    if s.is_empty():
        cols: dict = {
            "season": pl.Series([], dtype=pl.String),
            "year": pl.Series([], dtype=pl.Int32),
        }
        if "flow" in df.columns:
            cols["flow"] = pl.Series([], dtype=pl.String)
        cols[value_col] = pl.Series([], dtype=pl.Float64)
        return pl.DataFrame(cols)

    season_months = SEASON_DEFINITIONS[hemisphere]
    month_to_season = {m: name for name, months_list in season_months.items() for m in months_list}
    months = s["t_start"].dt.month()
    years = s["t_start"].dt.year()
    s = s.with_columns(
        [
            s[value_col].cast(pl.Float64).alias(value_col),
            months.map_elements(
                lambda m: month_to_season.get(m, "Unknown"), return_dtype=pl.String
            ).alias("season"),
            (years + (months == 12).cast(pl.Int32)).alias("year"),
        ]
    )

    grp_cols = ["season", "year"]
    if "flow" in s.columns:
        grp_cols = ["season", "year", "flow"]

    out = s.group_by(grp_cols).agg(_agg_expr(value_col, agg).alias(value_col))

    season_order = {name: i for i, name in enumerate(season_months)}
    return (
        out.with_columns(
            pl.col("season")
            .map_elements(lambda x: season_order.get(x, 99), return_dtype=pl.Int32)
            .alias("_order")
        )
        .sort(["year", "_order"])
        .drop("_order")
    )


def tou_bins(
    df: CanonFrame,
    bands: Iterable[dict],
    *,
    out_freq: str = "1MS",
    flows: Iterable[str] | None = ("grid_import",),
    value_col: str = "kwh",
) -> pl.DataFrame:
    """Aggregate energy into named TOU bands. Returns a month + per-band kWh frame."""
    bands_list = list(bands)
    s = df
    if flows:
        s = s.filter(pl.col("flow").is_in(list(flows)))
    if s.is_empty():
        names = [str(b["name"]) for b in bands_list]
        return pl.DataFrame(
            {
                "month": pl.Series([], dtype=pl.String),
                **{n: pl.Series([], dtype=pl.Float64) for n in names},
            }
        )

    s = s.with_columns(_assign_time_bands(s["t_start"], bands_list).alias("band"))

    every = _to_polars_freq(out_freq)
    grouped = (
        s.sort("t_start")
        .group_by_dynamic("t_start", every=every, group_by="band")
        .agg(pl.col(value_col).sum())
    )

    out = (
        grouped.pivot(index="t_start", on="band", values=value_col, aggregate_function="sum")
        .fill_null(0.0)
        .sort("t_start")
    )

    out = out.with_columns(pl.col("t_start").dt.strftime("%Y-%m").alias("month")).drop("t_start")

    return out


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
) -> pl.DataFrame:
    """Generic profile builder. Currently supports average-day by 30-min slot."""
    if by != "slot":
        raise NotImplementedError("profile currently supports by='slot' only")

    s = df
    if flows:
        s = s.filter(pl.col("flow").is_in(list(flows)))

    s = s.with_columns(pl.col("t_start").dt.strftime(slot_fmt).alias("slot"))

    agg_expr = (
        pl.col("kwh").mean()
        if reducer == "mean"
        else (pl.col("kwh").sum() if reducer == "sum" else pl.col("kwh").max())
    )
    grouped = s.group_by(["slot", pivot_by]).agg(agg_expr)
    prof = (
        grouped.pivot(index="slot", on=pivot_by, values="kwh", aggregate_function="first")
        .fill_null(0.0)
        .sort("slot")
    )

    if include_import_total:
        flow_cols = [c for c in prof.columns if c != "slot"]
        if import_flows:
            cols = [c for c in flow_cols if c in set(import_flows)]
        else:
            cols = [c for c in flow_cols if "import" in str(c)]
            if not cols:
                cols = flow_cols
        float_cols = [
            c for c in cols if prof[c].dtype in (pl.Float64, pl.Float32, pl.Int32, pl.Int64)
        ]
        prof = prof.with_columns(
            pl.sum_horizontal([pl.col(c).fill_null(0.0) for c in float_cols]).alias("import_total")
        )

    return prof


def window_stats_from_profile(
    profile_with_import: pl.DataFrame,
    windows: list[dict],
    cadence_min: int,
    total_daily_kwh: float | None = None,
) -> dict:
    """Compute avg_kw, kwh_per_day, share for configured windows using average-day profile."""
    total = (
        float(total_daily_kwh)
        if total_daily_kwh is not None
        else float(profile_with_import["import_total"].sum())
    )
    slot_times_py = [utils.parse_time_str(str(s)) for s in profile_with_import["slot"].to_list()]
    out: dict[str, dict[str, float]] = {}
    for w in windows:
        start_t = utils.parse_time_str(str(w["start"]))
        end_t = utils.parse_time_str(str(w["end"]))
        mask = [
            (t >= start_t and t < end_t) if start_t < end_t else (t >= start_t or t < end_t)
            for t in slot_times_py
        ]
        window_kwh = float(profile_with_import.filter(pl.Series(mask))["import_total"].sum())
        start_m = start_t.hour * 60 + start_t.minute
        end_m = end_t.hour * 60 + end_t.minute
        if end_m == 0:
            end_m = 24 * 60
        window_hours = (
            (end_m - start_m) / 60.0 if end_m >= start_m else ((24 * 60 - start_m) + end_m) / 60.0
        )
        avg_kw = (window_kwh / window_hours) if window_hours > 0 else 0.0
        share = (window_kwh / total * 100.0) if total > 0 else 0.0
        out[str(w["key"])] = {
            "avg_kw": float(avg_kw),
            "kwh_per_day": float(window_kwh),
            "share_of_daily_pct": float(share),
        }
    return out


def period_breakdown(
    df: CanonFrame,
    *,
    freq: Literal["1D", "1MS"],
    flows: Iterable[str] | None = None,
    cadence_min: int | None = None,
    labels: Literal["day", "month"] | None = None,
) -> dict[str, pl.DataFrame]:
    """Compute core per-period tables: total, peaks, avg_interval_kwh.

    Returns a dict with keys: total, peaks, average. Label column is 'day' or 'month'.
    """
    if labels is None:
        labels = "day" if freq == "1D" else "month"

    label_fmt = "%Y-%m-%d" if freq == "1D" else "%Y-%m"

    totals = aggregate(df, freq=freq, groupby="flow", pivot=True, value_col="kwh", flows=flows)
    if "t_start" in totals.columns:
        totals = totals.rename({"t_start": labels}).with_columns(
            pl.col(labels).dt.strftime(label_fmt).alias(labels)
        )
        flow_cols = [c for c in totals.columns if c != labels]
        float_cols = [
            c for c in flow_cols if totals[c].dtype in (pl.Float64, pl.Float32, pl.Int64, pl.Int32)
        ]
        totals = totals.with_columns(
            pl.sum_horizontal([pl.col(c).fill_null(0.0) for c in float_cols]).alias("total_kwh")
        )
    else:
        totals = pl.DataFrame({labels: pl.Series([], dtype=pl.String)})

    peaks = aggregate(df, freq=freq, value_col="kwh", agg="max", flows=flows)
    if "t_start" in peaks.columns:
        peaks = peaks.rename({"t_start": labels, "kwh": "peak_interval_kwh"}).with_columns(
            pl.col(labels).dt.strftime(label_fmt).alias(labels)
        )
    else:
        peaks = pl.DataFrame({labels: pl.Series([], dtype=pl.String), "peak_interval_kwh": []})

    avg_df = demand_window(df, freq=freq, stat="mean", flows=flows)
    if "t_start" in avg_df.columns:
        avg_df = avg_df.rename({"t_start": labels, "demand_kw": "mean_kw"}).with_columns(
            pl.col(labels).dt.strftime(label_fmt).alias(labels)
        )
        if cadence_min:
            avg_df = avg_df.with_columns(
                (pl.col("mean_kw") * (cadence_min / 60.0)).alias("avg_interval_kwh")
            )
        else:
            avg_df = avg_df.with_columns(pl.lit(0.0).alias("avg_interval_kwh"))
        avg_df = avg_df.select([labels, "avg_interval_kwh"])
    else:
        avg_df = pl.DataFrame({labels: pl.Series([], dtype=pl.String), "avg_interval_kwh": []})

    return {"total": totals, "peaks": peaks, "average": avg_df}
