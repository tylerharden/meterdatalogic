from __future__ import annotations
import numpy as np
import pandas as pd
from typing import Iterable, Tuple

from .types import Plan
from . import transform, utils


def _tznorm(ts, tz):
    ts = pd.Timestamp(ts)
    return ts.tz_localize(tz) if ts.tz is None else ts.tz_convert(tz)


def _label_cycles(
    index: pd.DatetimeIndex,
    cycles: Iterable[Tuple[str | pd.Timestamp, str | pd.Timestamp]],
) -> pd.Series:
    """
    Label each timestamp with the [start, end) cycle it belongs to, or <NA> if none.
    Uses searchsorted on sorted starts; no merge_as_of; no reliance on extra columns.
    """
    if index.tz is None:
        raise ValueError("Index must be tz-aware (e.g., Australia/Brisbane).")

    tz = index.tz
    # normalise to midnight in local tz for day math
    starts, ends = [], []
    for s, e in cycles:
        s = _tznorm(s, tz).normalize()
        e = _tznorm(e, tz).normalize()
        e = e + pd.Timedelta(days=1)
        if e <= s:
            raise ValueError(f"Cycle end must be after start: {s} .. {e}")
        starts.append(s)
        ends.append(e)

    # sort by start
    order = np.argsort(starts)
    starts = pd.DatetimeIndex([starts[i] for i in order]).tz_convert(tz)
    ends = pd.DatetimeIndex([ends[i] for i in order]).tz_convert(tz)
    labels = [
        f"{starts[i].date()}→{(ends[i] - pd.Timedelta(days=1)).date()}"
        for i in range(len(starts))
    ]

    # map each ts to the last start <= ts using searchsorted
    ts_i8 = index.asi8
    starts_i8 = starts.asi8
    ends_i8 = ends.asi8

    # idx = index of the candidate cycle (by start), or -1 if before first start
    idx = np.searchsorted(starts_i8, ts_i8, side="right") - 1
    valid = (idx >= 0) & (ts_i8 < ends_i8[np.clip(idx, 0, len(ends_i8) - 1)])

    out = np.array([pd.NA] * len(index), dtype=object)
    out[valid] = np.array(labels, dtype=object)[idx[valid]]
    return pd.Series(out, index=index, dtype="string")


# ------------------ billables over cycles ------------------


def _cycle_billables(
    df: pd.DataFrame,
    plan: Plan,
    cycles: Iterable[Tuple[str | pd.Timestamp, str | pd.Timestamp]],
) -> pd.DataFrame:
    """
    One row per cycle:
      ['cycle', <band columns>, 'export_kwh', 'demand_kw', 'days_in_cycle']
    """
    # attach labels
    dfx = df.copy()
    dfx["cycle"] = _label_cycles(df.index, cycles)
    dfx = dfx[dfx["cycle"].notna()].copy()

    # ---- IMPORT (TOU) ----
    # If only single all-times band, we can do a fast-path.
    single_all_time = (
        len(plan.usage_bands) == 1
        and plan.usage_bands[0].start == "00:00"
        and plan.usage_bands[0].end in ("24:00", "00:00")
    )
    if single_all_time:
        band_name = plan.usage_bands[0].name
        tou = (
            dfx[dfx["flow"] == "grid_import"]
            .groupby("cycle", as_index=False)["kwh"]
            .sum()
            .rename(columns={"kwh": band_name})
        )
    else:
        # full binning then group
        tb = transform.tou_bins(
            dfx[dfx["flow"] == "grid_import"],
            bands=[b.__dict__ for b in plan.usage_bands],
        )
        # ensure we still have 'cycle' to group by
        if "cycle" not in tb.columns:
            # left-join cycle back by index if tou_bins dropped it
            imp = dfx[dfx["flow"] == "grid_import"][["cycle"]].copy()
            tb = imp.join(tb, how="left")
        tou = tb.groupby("cycle", as_index=False).sum(numeric_only=True)

    # ---- EXPORT ----
    export = (
        dfx[dfx["flow"] == "grid_export_solar"]
        .groupby("cycle", as_index=False)["kwh"]
        .sum()
        .rename(columns={"kwh": "export_kwh"})
    )

    # ---- DEMAND ----
    if plan.demand:
        dem = transform.demand_window(
            dfx,
            start=plan.demand.window_start,
            end=plan.demand.window_end,
            days=plan.demand.days,
        )
        # if demand_window already returns per-cycle values, group; else set zeroes
        if "cycle" in dem.columns and "demand_kw" in dem.columns:
            demand = dem.groupby("cycle", as_index=False)["demand_kw"].max()
        else:
            demand = pd.DataFrame({"cycle": tou["cycle"].unique(), "demand_kw": 0.0})
    else:
        demand = pd.DataFrame({"cycle": tou["cycle"].unique(), "demand_kw": 0.0})

    # ---- MERGE ----
    out = tou.merge(export, on="cycle", how="left").merge(
        demand, on="cycle", how="left"
    )
    out = out.fillna(0.0)

    # ---- EXACT DAY COUNTS ----
    def _days_from_label(lbl: str) -> int:
        s_str, e_str = lbl.split("→")
        s = pd.Timestamp(s_str)
        e = pd.Timestamp(e_str)
        return int(((e + pd.Timedelta(days=1)) - s).days)

    out["days_in_cycle"] = out["cycle"].astype(str).map(_days_from_label)
    return out


def estimate_cycle_costs(
    df: pd.DataFrame,
    plan: Plan,
    cycles: Iterable[Tuple[str | pd.Timestamp, str | pd.Timestamp]],
    pay_on_time_discount: float = 0.0,
    include_gst: bool = False,
    gst_rate: float = 0.10,
) -> pd.DataFrame:
    bill = _cycle_billables(df, plan, cycles)

    # Energy across all usage bands your tou emitted (names must match ToUBand.name)
    energy = 0.0
    for b in plan.usage_bands:
        energy = energy + bill.get(b.name, 0.0) * (b.rate_c_per_kwh / 100.0)
    bill["energy_cost"] = energy

    bill["demand_cost"] = (
        bill["demand_kw"] * plan.demand.rate_per_kw_per_month if plan.demand else 0.0
    )
    bill["fixed_cost"] = (plan.fixed_c_per_day / 100.0) * bill["days_in_cycle"]
    bill["feed_in_credit"] = (
        bill.get("export_kwh", 0.0) * (plan.feed_in_c_per_kwh / 100.0) * (-1.0)
    )

    bill["subtotal"] = bill[
        ["energy_cost", "demand_cost", "fixed_cost", "feed_in_credit"]
    ].sum(axis=1)

    # Charges to discount are energy + demand + fixed (exclude feed-in credit)
    charges_only = (
        bill["energy_cost"] + bill["demand_cost"] + bill["fixed_cost"]
    ).round(2)

    # Discount shown on invoices is rounded to cents
    bill["pay_on_time_discount"] = -(charges_only * float(pay_on_time_discount)).round(
        2
    )

    if include_gst:
        # GST base: discounted charges (exclude feed-in credit)
        gst_base = (charges_only + bill["pay_on_time_discount"]).clip(lower=0.0)
        bill["gst"] = (gst_base * float(gst_rate)).round(2)
    else:
        bill["gst"] = 0.0

    bill["total"] = bill["subtotal"] + bill["pay_on_time_discount"] + bill["gst"]

    cols = [
        "cycle",
        "days_in_cycle",
        "energy_cost",
        "demand_cost",
        "fixed_cost",
        "feed_in_credit",
        "pay_on_time_discount",
        "gst",
    ]
    band_cols = [b.name for b in plan.usage_bands if b.name in bill.columns]
    extra = ["export_kwh"] if "export_kwh" in bill.columns else []
    total_col = ["total"]
    # return bill[cols + band_cols + extra]
    return bill[cols + band_cols + total_col]


def monthly_billables(df: pd.DataFrame, plan: Plan) -> pd.DataFrame:
    tou = transform.tou_bins(
        df[df["flow"] == "grid_import"], bands=[b.__dict__ for b in plan.usage_bands]
    )
    # export credit
    export = (
        df[df["flow"] == "grid_export_solar"]
        .resample("1MS")["kwh"]
        .sum()
        .rename("export_kwh")
        .reset_index()
    )
    export["month"] = utils.month_label(export["t_start"])
    export = export[["month", "export_kwh"]]
    # demand
    demand = (
        transform.demand_window(
            df,
            start=plan.demand.window_start,
            end=plan.demand.window_end,
            days=plan.demand.days,
        )
        if plan.demand
        else pd.DataFrame({"month": pd.unique(tou["month"]), "demand_kw": 0.0})
    )
    # merge
    out = tou.merge(export, on="month", how="left").merge(
        demand, on="month", how="left"
    )
    out = out.fillna(0.0)
    return out


def estimate_monthly_cost(df: pd.DataFrame, plan: Plan) -> pd.DataFrame:
    bill = monthly_billables(df, plan)
    # energy cost
    bill["energy_cost"] = sum(
        bill.get(b.name, 0.0) * (b.rate_c_per_kwh / 100.0) for b in plan.usage_bands
    )
    # demand
    if plan.demand:
        bill["demand_cost"] = bill["demand_kw"] * plan.demand.rate_per_kw_per_month
    else:
        bill["demand_cost"] = 0.0
    # fixed cost — approximate by counting distinct months (1 charge per month)
    _p = pd.PeriodIndex(bill["month"], freq="M")
    bill["fixed_cost"] = (plan.fixed_c_per_day / 100.0) * _p.day
    # feed-in credit
    bill["feed_in_credit"] = (
        bill.get("export_kwh", 0.0) * (plan.feed_in_c_per_kwh / 100.0) * (-1.0)
    )
    bill["total"] = bill[
        ["energy_cost", "demand_cost", "fixed_cost", "feed_in_credit"]
    ].sum(axis=1)
    return bill[
        ["month", "energy_cost", "demand_cost", "fixed_cost", "feed_in_credit", "total"]
    ]
