from __future__ import annotations
import pandas as pd
from typing import Literal, Iterable
from . import canon, utils


def filter_range(df: pd.DataFrame, start=None, end=None) -> pd.DataFrame:
    return df.loc[start:end] if start or end else df


def resample_energy(
    df: pd.DataFrame, rule: Literal["15min", "30min", "1H", "1D", "1MS"]
) -> pd.DataFrame:
    keys = ["nmi", "channel", "flow"]
    out = (
        df.reset_index()
        .groupby(keys + [pd.Grouper(key="t_start", freq=rule)])["kwh"]
        .sum()
        .reset_index()
        .set_index("t_start")
        .sort_index()
    )
    out["cadence_min"] = (
        60
        if rule == "1H"
        else 1440 if rule in ("1D", "1MS") else int(rule.replace("min", ""))
    )
    return out


def groupby_day(df: pd.DataFrame) -> pd.DataFrame:
    out = (
        df.reset_index()
        .groupby(["flow", pd.Grouper(key="t_start", freq="1D")])["kwh"]
        .sum()
        .unstack(0)
        .fillna(0.0)
    )
    out.index.name = "day"
    return out


def groupby_month(df: pd.DataFrame) -> pd.DataFrame:
    out = (
        df.reset_index()
        .groupby(["flow", pd.Grouper(key="t_start", freq="1MS")])["kwh"]
        .sum()
        .unstack(0)
        .fillna(0.0)
        .reset_index()
    )
    out = out.rename(columns={"t_start": "month"})
    out["month"] = out["month"].dt.strftime("%Y-%m")
    return out


def profile24(
    df: pd.DataFrame, by: str = "flow", agg: Literal["mean", "median"] = "mean"
) -> pd.DataFrame:
    # average day shape per interval slot
    s = df.copy()
    s["slot"] = s.index.strftime("%H:%M")
    g = s.groupby(["slot", by])["kwh"]
    out = (
        (g.mean() if agg == "mean" else g.median())
        .unstack(by)
        .fillna(0.0)
        .reset_index()
    )
    return out


def tou_bins(df: pd.DataFrame, bands: Iterable[dict]) -> pd.DataFrame:
    s = df.copy()
    local = s.index.tz_convert(df.index.tz)
    times = pd.Series(local.time, index=s.index)

    assigned = pd.Series(index=s.index, dtype="object")
    for band in bands:
        start = utils._parse_time_str(band["start"])
        end = utils._parse_time_str(band["end"])
        mask = utils._time_in_range(times, start, end)
        assigned[mask] = band["name"]

    s["band"] = assigned.fillna("unassigned")

    out = (
        s.reset_index()
        .groupby(["band", pd.Grouper(key="t_start", freq="1MS")])["kwh"]
        .sum()
        .unstack(0)
        .fillna(0.0)
        .reset_index()
    )
    out = out.rename(columns={"t_start": "month"})
    out["month"] = out["month"].dt.strftime("%Y-%m")
    return out


def demand_window(
    df: pd.DataFrame, start: str = "16:00", end: str = "21:00", days: str = "MF"
) -> pd.DataFrame:
    s = df.copy()
    t = s.index.tz_convert(df.index.tz)
    dayofweek = t.dayofweek  # Mon=0 ... Sun=6
    if days == "MF":
        daymask = dayofweek <= 4
    else:
        daymask = dayofweek <= 5
    start_t = pd.to_datetime(start).time()
    end_t = pd.to_datetime(end).time()
    timemask = utils._time_in_range(t.time, start_t, end_t)
    s = s[daymask & timemask & (s["flow"] == "grid_import")]
    # Convert half-hour kWh → kW estimate: kWh * (60 / cadence)
    factor = 60 / s["cadence_min"].astype(float)
    s = s.assign(kW=s["kwh"] * factor)
    out = s.resample("1MS")["kW"].max().to_frame("demand_kw").reset_index()
    out["month"] = out["t_start"].dt.strftime("%Y-%m")
    return out[["month", "demand_kw"]]
