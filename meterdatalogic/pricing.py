from __future__ import annotations
import numpy as np
import pandas as pd
from typing import Iterable, Tuple, Literal, Optional, cast

from .types import Plan, CanonFrame
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
        f"{starts[i].date()}→{(ends[i] - pd.Timedelta(days=1)).date()}" for i in range(len(starts))
    ]

    # map each ts to the last start <= ts using searchsorted
    def _i8(idx: pd.DatetimeIndex) -> np.ndarray:
        # Convert to int64 nanoseconds for searchsorted in a Pylance-friendly way
        return idx.to_numpy(dtype="datetime64[ns]").astype("int64", copy=False)

    ts_i8 = _i8(index)
    starts_i8 = _i8(starts)
    ends_i8 = _i8(ends)

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
    dfx["cycle"] = _label_cycles(pd.DatetimeIndex(df.index), cycles)
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
            .groupby("cycle", as_index=False)
            .agg(**{band_name: ("kwh", "sum")})
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
        .groupby("cycle", as_index=False)
        .agg(export_kwh=("kwh", "sum"))
    )

    # ---- DEMAND ----
    if plan.demand:
        # Demand per cycle: filter by window, compute kW, then aggregate max per cycle
        imp = cast(CanonFrame, dfx[dfx["flow"] == "grid_import"].copy())
        demand = transform.aggregate(
            imp,
            freq=None,
            groupby=["cycle"],
            metric="kW",
            stat="max",
            out_col="demand_kw",
            window_start=plan.demand.window_start,
            window_end=plan.demand.window_end,
            window_days=plan.demand.days,
        )
    else:
        demand = pd.DataFrame({"cycle": tou["cycle"].unique(), "demand_kw": 0.0})

    # ---- MERGE ----
    out = tou.merge(export, on="cycle", how="left").merge(demand, on="cycle", how="left")
    numeric_cols = out.select_dtypes(include="number").columns
    out[numeric_cols] = out[numeric_cols].fillna(0.0)

    # ---- EXACT DAY COUNTS ----
    def _days_from_label(lbl: str) -> int:
        s_str, e_str = lbl.split("→")
        s = pd.Timestamp(s_str)
        e = pd.Timestamp(e_str)
        return int(((e + pd.Timedelta(days=1)) - s).days)

    out["days_in_cycle"] = out["cycle"].astype(str).map(_days_from_label)
    return out


def compute_billables(
    df: CanonFrame,
    plan: Plan,
    *,
    mode: Literal["monthly", "cycles"] = "monthly",
    cycles: Optional[Iterable[Tuple[str | pd.Timestamp, str | pd.Timestamp]]] = None,
) -> pd.DataFrame:
    """
    Compute billable quantities for a given plan.

    - mode="monthly": returns columns ['month', <band cols>, 'export_kwh', 'demand_kw']
    - mode="cycles": returns columns ['cycle', <band cols>, 'export_kwh', 'demand_kw', 'days_in_cycle']
    """
    if mode == "monthly":
        tou = transform.tou_bins(
            df[df["flow"] == "grid_import"],
            bands=[b.__dict__ for b in plan.usage_bands],
        )
        export = (
            df.loc[df["flow"] == "grid_export_solar", ["kwh"]]
            .resample("1MS")
            .sum()
            .rename(columns={"kwh": "export_kwh"})
            .reset_index()
        )
        export["month"] = utils.month_label(export["t_start"])  # type: ignore[arg-type]
        export = export[["month", "export_kwh"]]

        # Base months from export or index range (fallback), else from tou
        base = export[["month"]].drop_duplicates().copy()
        if base.empty:
            idx = pd.DatetimeIndex(df.index)
            if len(idx):
                rng = pd.date_range(
                    idx.min().normalize(), idx.max().normalize(), freq="MS", tz=idx.tz
                )
                if len(rng):
                    base = pd.DataFrame({"month": utils.month_label(rng).values})
        if base.empty and not tou.empty:
            base = tou[["month"]].drop_duplicates().copy()
        if base.empty:
            # No periods to report
            cols = [
                "month",
                "export_kwh",
                "demand_kw",
                *[b.name for b in plan.usage_bands],
            ]
            return pd.DataFrame(columns=cols)

        # Ensure ToU rows exist for all base months
        if tou.empty:
            tou = base.copy()
            for b in plan.usage_bands:
                tou[b.name] = 0.0

        # Demand calculation or zeros aligned to base months
        if plan.demand:
            demand = transform.aggregate(
                df,
                freq="1MS",
                flows=["grid_import"],
                metric="kW",
                stat="max",
                out_col="demand_kw",
                window_start=plan.demand.window_start,
                window_end=plan.demand.window_end,
                window_days=plan.demand.days,  # type: ignore[arg-type]
            )
            demand = demand.copy()
            demand["month"] = utils.month_label(pd.DatetimeIndex(demand.index))
            demand = demand[["month", "demand_kw"]].reset_index(drop=True)
        else:
            demand = base.copy()
            demand["demand_kw"] = 0.0

        out = (
            base.merge(tou, on="month", how="left")
            .merge(export, on="month", how="left")
            .merge(demand, on="month", how="left")
        )
        numeric_cols = out.select_dtypes(include="number").columns
        out[numeric_cols] = out[numeric_cols].fillna(0.0)
        return out

    # cycles mode
    if not cycles:
        raise ValueError("cycles must be provided when mode='cycles'")
    return _cycle_billables(df, plan, cycles)


def estimate_costs(
    bill: pd.DataFrame,
    plan: Plan,
    *,
    pay_on_time_discount: float = 0.0,
    include_gst: bool = False,
    gst_rate: float = 0.10,
) -> pd.DataFrame:
    """
    Estimate costs from billables (monthly or cycles).
    Detects period type by presence of 'month' or 'cycle'.
    """
    # Energy across ToU band columns
    energy = 0.0
    for b in plan.usage_bands:
        energy = energy + bill.get(b.name, 0.0) * (b.rate_c_per_kwh / 100.0)
    out = bill.copy()
    out["energy_cost"] = energy

    # Demand cost
    out["demand_cost"] = (
        out.get("demand_kw", 0.0) * plan.demand.rate_per_kw_per_month if plan.demand else 0.0
    )

    # Fixed cost
    if "cycle" in out.columns:
        if "days_in_cycle" not in out.columns:
            # compute from label if missing
            def _days_from_label(lbl: str) -> int:
                s_str, e_str = lbl.split("→")
                s = pd.Timestamp(s_str)
                e = pd.Timestamp(e_str)
                return int(((e + pd.Timedelta(days=1)) - s).days)

            out["days_in_cycle"] = out["cycle"].astype(str).map(_days_from_label)
        # Ensure days is numeric (map may produce object dtype)
        days = pd.to_numeric(out["days_in_cycle"], errors="coerce").fillna(0.0)
    elif "month" in out.columns:
        _p = pd.PeriodIndex(out["month"], freq="M")
        # PeriodIndex.days_in_month returns an Index, so convert to Series before to_numeric
        days = pd.Series(_p.days_in_month)
        days = pd.to_numeric(days, errors="coerce").fillna(0.0)
    else:
        raise ValueError("bill must contain 'month' or 'cycle' column")
    out["fixed_cost"] = (plan.fixed_c_per_day / 100.0) * days

    # Coerce numeric columns to avoid object dtype from mappings
    for col in ("export_kwh", "energy_cost", "demand_cost", "fixed_cost"):
        if col in out.columns:
            out[col] = pd.to_numeric(out[col], errors="coerce").fillna(0.0)
        else:
            out[col] = 0.0

    # Feed-in credit (negative)
    out["feed_in_credit"] = out["export_kwh"] * (plan.feed_in_c_per_kwh / 100.0) * (-1.0)

    out["subtotal"] = out[["energy_cost", "demand_cost", "fixed_cost", "feed_in_credit"]].sum(
        axis=1
    )

    charges_only = (out["energy_cost"] + out["demand_cost"] + out["fixed_cost"]).round(2)
    out["pay_on_time_discount"] = -(charges_only * float(pay_on_time_discount)).round(2)

    if include_gst:
        gst_base = (charges_only + out["pay_on_time_discount"]).clip(lower=0.0)
        out["gst"] = (gst_base * float(gst_rate)).round(2)
    else:
        out["gst"] = 0.0

    out["total"] = out["subtotal"] + out["pay_on_time_discount"] + out["gst"]

    # Order columns: period id first, then costs
    if "month" in out.columns:
        cols = [
            "month",
            "energy_cost",
            "demand_cost",
            "fixed_cost",
            "feed_in_credit",
            "pay_on_time_discount",
            "gst",
            "total",
        ]
    else:
        cols = [
            "cycle",
            "days_in_cycle",
            "energy_cost",
            "demand_cost",
            "fixed_cost",
            "feed_in_credit",
            "pay_on_time_discount",
            "gst",
            "total",
        ]
    return out[cols]
