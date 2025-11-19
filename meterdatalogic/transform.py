from __future__ import annotations
import pandas as pd
from typing import Literal, Iterable, Optional

from . import utils
from .types import CanonFrame


def filter_range(
    df: CanonFrame,
    start: Optional[pd.Timestamp] = None,
    end: Optional[pd.Timestamp] = None,
) -> pd.DataFrame:
    return df.loc[start:end] if (start is not None or end is not None) else df


def resample_energy(df: CanonFrame, freq: str) -> pd.DataFrame:
    """
    Sum kWh to a new cadence per (nmi, channel, flow).
    """
    cols = ["nmi", "channel", "flow", "kwh"]
    d = df.reset_index()[["t_start", *cols]]
    out = (
        d.set_index("t_start")
        .groupby(cols[:-1], observed=False)
        .resample(freq, label="left", closed="left")["kwh"]
        .sum()
        .reset_index()
    )
    return out


def collapse_import_export(df: CanonFrame) -> tuple[pd.Series, pd.Series]:
    """
    Return (import_series_kwh, export_series_kwh) summed per interval.

    - Robust to subsets and flow naming like 'grid_export_solar' / 'grid_import'
    - Always reindexes to the full timeline (df.index) with 0.0 fill.
    """
    if not isinstance(df.index, pd.DatetimeIndex):
        raise TypeError("collapse_import_export requires a DatetimeIndex index.")

    idx_full = df.index
    flows = df["flow"].astype(str)

    df_imp = df.loc[flows.str.contains("import", na=False)]
    df_exp = df.loc[flows.str.contains("export", na=False)]

    if df_imp.empty:
        imp = pd.Series(0.0, index=idx_full, name="import_kwh")
    else:
        imp = (
            df_imp.groupby(level=0)["kwh"].sum().reindex(idx_full, fill_value=0.0)
        ).sort_index()
        imp.name = "import_kwh"

    if df_exp.empty:
        exp = pd.Series(0.0, index=idx_full, name="export_kwh")
    else:
        exp = (
            df_exp.groupby(level=0)["kwh"].sum().reindex(idx_full, fill_value=0.0)
        ).sort_index()
        exp.name = "export_kwh"

    return imp, exp


def aggregate_historical_by_flow(df: CanonFrame, freq: str) -> pd.DataFrame:
    """
    Aggregate kWh per flow to a new cadence for charting.

    Returns a DataFrame indexed by t_start with one column per flow, e.g.:

        index: t_start (DatetimeIndex)
        columns: ['grid_import', 'grid_export_solar', ...]

    Example:
        out = aggregate_historical_by_flow(df, "30T")
    """
    d = df.reset_index()[["t_start", "flow", "kwh"]]
    out = (
        d.groupby(["flow", pd.Grouper(key="t_start", freq=freq)])["kwh"]
        .sum()
        .unstack("flow")
        .fillna(0.0)
        .reset_index()
        .set_index("t_start")
        .sort_index()
    )
    return out


def groupby_day(df: CanonFrame) -> pd.DataFrame:
    out = (
        df.reset_index()
        .groupby(["flow", pd.Grouper(key="t_start", freq="1D")])["kwh"]
        .sum()
        .unstack(0)
        .fillna(0.0)
    )
    out.index.name = "day"
    return out


def groupby_month(df: CanonFrame) -> pd.DataFrame:
    out = (
        df.reset_index()
        .groupby(["flow", pd.Grouper(key="t_start", freq="1MS")])["kwh"]
        .sum()
        .unstack(0)
        .fillna(0.0)
        .reset_index()
    )
    out = out.rename(columns={"t_start": "month"})
    out["month"] = utils.month_label(out["month"])
    return out


def profile24(
    df: CanonFrame, by: str = "flow", agg: Literal["mean", "median"] = "mean"
) -> pd.DataFrame:
    # average day shape per interval slot
    s = df.copy()
    s["slot"] = pd.DatetimeIndex(s.index).strftime("%H:%M")
    g = s.groupby(["slot", by])["kwh"]
    out = (
        (g.mean() if agg == "mean" else g.median())
        .unstack(by)
        .fillna(0.0)
        .reset_index()
    )
    return out


def tou_bins(df: pd.DataFrame, bands: Iterable[dict]) -> pd.DataFrame:
    """
    Bin kWh into TOU bands by local time, then aggregate monthly.

    Returns:
        DataFrame with columns:
          - 'month' (YYYY-MM)
          - one column per TOU band name
    """
    s = df.copy()

    # Work in local wall-time; index is already tz-aware canon
    times = utils.local_time_series(pd.DatetimeIndex(s.index))

    assigned = pd.Series(index=s.index, dtype="object")
    for band in bands:
        start = utils.parse_time_str(band["start"])
        end = utils.parse_time_str(band["end"])
        mask = utils.time_in_range(times, start, end)
        assigned[mask] = band["name"]

    s["band"] = assigned.fillna("unassigned")

    out = (
        s.reset_index()
        .groupby(["band", pd.Grouper(key="t_start", freq="1MS")])["kwh"]
        .sum()
        .unstack("band")
        .fillna(0.0)
        .reset_index()
    )

    out = out.rename(columns={"t_start": "month"})
    out["month"] = utils.month_label(out["month"])
    return out


def demand_window(
    df: pd.DataFrame,
    start: str = "16:00",
    end: str = "21:00",
    days: Literal["ALL", "MF", "MS"] = "MF",
) -> pd.DataFrame:
    """
    Estimate monthly demand (kW) from half-hourly (or similar) kWh.

    - Filters to grid_import only.
    - Restricts to specified days (MF or MS) and time window.
    - Converts kWh to kW using cadence_min.
    - Returns the monthly max kW per month.

    Output:
        DataFrame with columns ['month', 'demand_kw']
    """
    s = df.copy()
    idx = pd.DatetimeIndex(s.index)
    # Day-of-week mask via shared helper
    daymask = utils.day_mask(idx, days)

    # Time-of-day mask
    start_t = utils.parse_time_str(start)
    end_t = utils.parse_time_str(end)
    times = utils.local_time_series(idx)
    timemask = utils.time_in_range(times, start_t, end_t)

    # Only consider grid import in that window
    in_window = daymask & timemask & (s["flow"] == "grid_import")
    s = s[in_window].copy()

    if s.empty:
        return pd.DataFrame(columns=["month", "demand_kw"])

    # Convert per-interval kWh -> kW: kWh * (60 / cadence_min)
    factor = 60.0 / s["cadence_min"].astype(float)
    s = s.assign(kW=s["kwh"] * factor)

    out = s.resample("1MS")["kW"].max().to_frame("demand_kw").reset_index()
    out["month"] = utils.month_label(out["t_start"])
    return out[["month", "demand_kw"]]
