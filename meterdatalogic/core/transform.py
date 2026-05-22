from __future__ import annotations
import polars as pl
from typing import Literal, Iterable, Optional, Sequence

from . import utils
from .types import CanonFrame
from ..config import SUMMARY_TOP_N


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


def _filter_range(
    df: CanonFrame,
    start: Optional[object] = None,
    end: Optional[object] = None,
) -> CanonFrame:
    conditions = []
    if start is not None:
        conditions.append(pl.col("t_start") >= start)
    if end is not None:
        conditions.append(pl.col("t_start") <= end)
    if conditions:
        return df.filter(pl.all_horizontal(conditions))
    return df


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


def aggregate(
    df: CanonFrame,
    *,
    freq: str | None,
    value_col: str = "kwh",
    agg: str = "sum",
    groupby: str | Sequence[str] | None = None,
    pivot: bool = False,
    flows: Iterable[str] | None = None,
    window_start: str | None = None,
    window_end: str | None = None,
    window_days: Literal["ALL", "MF", "MS"] = "ALL",
    metric: Literal["kWh", "kW"] = "kWh",
    stat: Literal["max", "mean", "sum"] = "max",
    out_col: Optional[str] = None,
    label: Literal["left", "right"] = "left",
    closed: Literal["left", "right"] = "left",
    hemisphere: Literal["northern", "southern"] | None = None,
) -> pl.DataFrame:
    """
    Unified aggregation helper. Filters by flow, applies an optional time window,
    then resamples or groups. metric='kW' converts kWh to power. groupby='season'
    with hemisphere produces seasonal splits.
    """
    if "t_start" not in df.columns:
        raise TypeError("aggregate requires a 't_start' column.")

    s = df
    if flows:
        s = s.filter(pl.col("flow").is_in(list(flows)))
    if s.is_empty():
        base_name = out_col or ("demand_kw" if metric == "kW" else value_col)
        if pivot and groupby:
            return pl.DataFrame({"t_start": pl.Series([], dtype=pl.Datetime("us"))})
        return pl.DataFrame({"t_start": pl.Series([], dtype=pl.Datetime("us")), base_name: []})

    # Optional time window filter
    if window_start is not None and window_end is not None:
        mask = _time_window_mask(
            s["t_start"], start=window_start, end=window_end, days=window_days
        )
        s = s.filter(mask)
        if s.is_empty():
            base_name = out_col or ("demand_kw" if metric == "kW" else value_col)
            if pivot and groupby:
                return pl.DataFrame({"t_start": pl.Series([], dtype=pl.Datetime("us"))})
            return pl.DataFrame(
                {"t_start": pl.Series([], dtype=pl.Datetime("us")), base_name: []}
            )

    if metric == "kW":
        val_series = _compute_power_from_energy(s, energy_col=value_col)
        base_name = out_col or "demand_kw"
        effective_stat = stat
    else:
        val_series = s[value_col].cast(pl.Float64)
        base_name = out_col or value_col
        effective_stat = agg

    s = s.with_columns(val_series.alias("_val"))

    grp_cols: list[str] = []
    if groupby is not None:
        grp_cols = [groupby] if isinstance(groupby, str) else list(groupby)

    # Seasonal columns
    if "season" in grp_cols:
        if hemisphere is None:
            raise ValueError("hemisphere parameter required when groupby includes 'season'")
        season_months = SEASON_DEFINITIONS[hemisphere]
        month_to_season = {
            m: name for name, months_list in season_months.items() for m in months_list
        }
        months = s["t_start"].dt.month()
        years = s["t_start"].dt.year()
        s = s.with_columns(
            [
                months.map_elements(
                    lambda m: month_to_season.get(m, "Unknown"), return_dtype=pl.String
                ).alias("_season"),
                (years + (months == 12).cast(pl.Int32)).alias("_season_year"),
            ]
        )
        grp_cols = ["_season" if c == "season" else c for c in grp_cols]
        if "_season_year" not in grp_cols:
            grp_cols.insert(grp_cols.index("_season") + 1, "_season_year")

    def _agg_expr(col: str, how: str) -> pl.Expr:
        if how == "max":
            return pl.col(col).max()
        if how == "mean":
            return pl.col(col).mean()
        return pl.col(col).sum()

    if freq is None:
        # Aggregate without resampling
        if grp_cols:
            out = (
                s.group_by(grp_cols)
                .agg(_agg_expr("_val", effective_stat).alias(base_name))
            )
        else:
            agg_val = float(
                s["_val"].max() if effective_stat == "max"
                else (s["_val"].mean() if effective_stat == "mean" else s["_val"].sum())
            )
            out = pl.DataFrame({base_name: [agg_val]})

    elif grp_cols:
        # Resample with grouping
        every = _to_polars_freq(freq)
        res = (
            s.sort("t_start")
            .group_by_dynamic("t_start", every=every, group_by=grp_cols, closed=closed)
            .agg(_agg_expr("_val", effective_stat).alias(base_name))
        )
        if pivot:
            # Only single-column groupby supported for pivot
            pivot_col = grp_cols[0]
            out = res.pivot(
                index="t_start", on=pivot_col, values=base_name, aggregate_function="sum"
            ).fill_null(0.0).sort("t_start")
        else:
            out = res.sort("t_start")

    else:
        # Pure resample, no extra grouping
        every = _to_polars_freq(freq)
        out = (
            s.sort("t_start")
            .group_by_dynamic("t_start", every=every, closed=closed)
            .agg(_agg_expr("_val", effective_stat).alias(base_name))
            .sort("t_start")
        )

    # Rename _season/_season_year back to season/year
    if groupby is not None:
        grp_list = [groupby] if isinstance(groupby, str) else list(groupby)
        if "season" in grp_list:
            rename_map = {"_season": "season", "_season_year": "year"}
            rename_present = {k: v for k, v in rename_map.items() if k in out.columns}
            if rename_present:
                out = out.rename(rename_present)

            if hemisphere and "season" in out.columns and "year" in out.columns:
                season_months_def = SEASON_DEFINITIONS[hemisphere]
                season_order = {name: i for i, name in enumerate(season_months_def)}
                out = out.with_columns(
                    pl.col("season")
                    .map_elements(lambda s: season_order.get(s, 99), return_dtype=pl.Int32)
                    .alias("_order")
                ).sort(["year", "_order"]).drop("_order")

    return out


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
            {"month": pl.Series([], dtype=pl.String), **{n: pl.Series([], dtype=pl.Float64) for n in names}}
        )

    s = s.with_columns(_assign_time_bands(s["t_start"], bands_list).alias("band"))

    every = _to_polars_freq(out_freq)
    grouped = (
        s.sort("t_start")
        .group_by_dynamic("t_start", every=every, group_by="band")
        .agg(pl.col(value_col).sum())
    )

    out = grouped.pivot(
        index="t_start", on="band", values=value_col, aggregate_function="sum"
    ).fill_null(0.0).sort("t_start")

    out = out.with_columns(
        pl.col("t_start").dt.strftime("%Y-%m").alias("month")
    ).drop("t_start")

    return out


def base_from_profile(profile_with_import: pl.DataFrame, cadence_min: int) -> dict:
    """Compute base load from average-day import profile. Returns {base_kw, base_kwh_per_day}."""
    if profile_with_import.is_empty():
        return {"base_kw": 0.0, "base_kwh_per_day": 0.0}
    base_interval_kwh = float(profile_with_import["import_total"].min())
    base_kw = base_interval_kwh * (60.0 / cadence_min) if cadence_min else 0.0
    return {"base_kw": float(base_kw), "base_kwh_per_day": float(base_kw * 24.0)}


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


def peak_from_profile(
    profile_with_import: pl.DataFrame, cadence_min: int
) -> tuple[float, Optional[str]]:
    """Peak kW and time from average-day profile import_total."""
    if profile_with_import.is_empty():
        return 0.0, None
    peak_interval_kwh = float(profile_with_import["import_total"].max())
    peak_kw = peak_interval_kwh * (60.0 / cadence_min) if cadence_min else 0.0
    idx = int(profile_with_import["import_total"].arg_max())
    t = str(profile_with_import["slot"][idx]) if idx >= 0 else None
    return float(peak_kw), t


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
        pl.col("kwh").mean() if reducer == "mean"
        else (pl.col("kwh").sum() if reducer == "sum" else pl.col("kwh").max())
    )
    grouped = s.group_by(["slot", pivot_by]).agg(agg_expr)
    prof = grouped.pivot(
        index="slot", on=pivot_by, values="kwh", aggregate_function="first"
    ).fill_null(0.0).sort("slot")

    if include_import_total:
        flow_cols = [c for c in prof.columns if c != "slot"]
        if import_flows:
            cols = [c for c in flow_cols if c in set(import_flows)]
        else:
            cols = [c for c in flow_cols if "import" in str(c)]
            if not cols:
                cols = flow_cols
        float_cols = [c for c in cols if prof[c].dtype in (pl.Float64, pl.Float32, pl.Int32, pl.Int64)]
        prof = prof.with_columns(
            pl.sum_horizontal([pl.col(c).fill_null(0.0) for c in float_cols]).alias("import_total")
        )

    return prof


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
        float_cols = [c for c in flow_cols if totals[c].dtype in (pl.Float64, pl.Float32, pl.Int64, pl.Int32)]
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

    avg_df = aggregate(df, freq=freq, metric="kW", stat="mean", flows=flows)
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
        avg_df = pl.DataFrame(
            {labels: pl.Series([], dtype=pl.String), "avg_interval_kwh": []}
        )

    return {"total": totals, "peaks": peaks, "average": avg_df}


def top_n_from_profile(
    profile_df: pl.DataFrame,
    *,
    group_by: Literal["hour"] = "hour",
    slot_col: str = "slot",
    value_col: str = "import_total",
    n: int = SUMMARY_TOP_N,
    total_value: float | None = None,
) -> dict:
    """Generic top-N reducer from a profile dataframe.

    Currently supports group_by='hour' on slot labels and sums value_col for ranking.
    """
    if group_by != "hour":
        raise NotImplementedError("Only group_by='hour' supported")
    if profile_df.is_empty():
        return {"labels": [], "value_total": 0.0, "share_pct": 0.0}

    grouped = (
        profile_df.with_columns(
            pl.col(slot_col).cast(pl.String).str.slice(0, 2).alias("_h")
        )
        .group_by("_h")
        .agg(pl.col(value_col).sum())
        .sort(value_col, descending=True)
    )
    top = grouped.head(n)
    labels = top["_h"].to_list()
    value_total = float(top[value_col].sum())
    denom = float(total_value) if total_value is not None else float(profile_df[value_col].sum())
    share = (value_total / denom * 100.0) if denom > 0 else 0.0
    return {"labels": labels, "value_total": value_total, "share_pct": float(share)}
