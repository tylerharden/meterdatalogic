from __future__ import annotations
import numpy as np
import polars as pl
from typing import Iterable, Tuple, Literal, Optional

from ..core import transform, utils
from ..core.types import CanonFrame
from ..analytics.types import Plan


def _tznorm(ts, tz):
    import datetime as _dt
    if isinstance(ts, str):
        ts = pl.Series([ts]).str.strptime(pl.Datetime("us"), "%Y-%m-%d").to_list()[0]
    if isinstance(ts, _dt.datetime):
        if ts.tzinfo is None:
            return ts.replace(tzinfo=_dt.timezone.utc)  # placeholder; tz convert below
    return ts


def _label_cycles(
    t_start: pl.Series,
    cycles: Iterable[Tuple[str | object, str | object]],
) -> pl.Series:
    """Assign each timestamp to a [start, end) cycle label, or null if outside all cycles."""
    import datetime as _dt

    tz = t_start.dtype.time_zone
    if tz is None:
        raise ValueError("t_start must be tz-aware.")

    starts_dt: list[_dt.datetime] = []
    ends_dt: list[_dt.datetime] = []
    labels: list[str] = []

    for s, e in cycles:
        s_pl = pl.Series([str(s)]).str.strptime(pl.Date, "%Y-%m-%d").to_list()[0] if isinstance(s, str) else s
        e_pl = pl.Series([str(e)]).str.strptime(pl.Date, "%Y-%m-%d").to_list()[0] if isinstance(e, str) else e
        # Convert date to tz-aware datetime at midnight
        s_dt = _dt.datetime(s_pl.year, s_pl.month, s_pl.day)
        e_dt = _dt.datetime(e_pl.year, e_pl.month, e_pl.day) + _dt.timedelta(days=1)
        starts_dt.append(s_dt)
        ends_dt.append(e_dt)
        labels.append(f"{s_pl}→{e_pl}")

    # Sort by start
    order = np.argsort([s.timestamp() for s in starts_dt])
    starts_sorted = [starts_dt[i] for i in order]
    ends_sorted = [ends_dt[i] for i in order]
    labels_sorted = [labels[i] for i in order]

    starts_ns = np.array([int(s.timestamp() * 1e9) for s in starts_sorted])
    ends_ns = np.array([int(e.timestamp() * 1e9) for e in ends_sorted])

    # Convert t_start to UTC nanoseconds for searchsorted
    ts_ns = (t_start.dt.convert_time_zone("UTC").dt.epoch(time_unit="ns").to_numpy())

    idx = np.searchsorted(starts_ns, ts_ns, side="right") - 1
    valid = (idx >= 0) & (ts_ns < ends_ns[np.clip(idx, 0, len(ends_ns) - 1)])

    result = np.array([None] * len(t_start), dtype=object)
    result[valid] = np.array(labels_sorted, dtype=object)[idx[valid]]
    return pl.Series(result.tolist(), dtype=pl.String)


def _cycle_billables(
    df: pl.DataFrame,
    plan: Plan,
    cycles: Iterable[Tuple[str | object, str | object]],
    *,
    include_controlled_load: bool = False,
    include_total_import: bool = False,
) -> pl.DataFrame:
    """One row per cycle: TOU band kWh, export_kwh, demand_kw, days_in_cycle."""
    dfx = df.with_columns(_label_cycles(df["t_start"], cycles).alias("cycle"))
    dfx = dfx.filter(pl.col("cycle").is_not_null())

    # ---- IMPORT (TOU) ----
    single_all_time = (
        len(plan.usage_bands) == 1
        and plan.usage_bands[0].start == "00:00"
        and plan.usage_bands[0].end in ("24:00", "00:00")
    )
    if single_all_time:
        band_name = plan.usage_bands[0].name
        tou = (
            dfx.filter(pl.col("flow") == "grid_import")
            .group_by("cycle")
            .agg(pl.col("kwh").sum().alias(band_name))
        )
    else:
        imp = dfx.filter(pl.col("flow") == "grid_import").with_columns(
            pl.col("cycle").alias("_cycle_bak")
        )
        tb = transform.tou_bins(imp, bands=[b.__dict__ for b in plan.usage_bands])
        # tou_bins drops the cycle column; re-derive by joining on month
        if "cycle" not in tb.columns and not tb.is_empty():
            cycle_map = (
                imp.with_columns(pl.col("t_start").dt.strftime("%Y-%m").alias("month"))
                .group_by("month")
                .agg(pl.col("_cycle_bak").first().alias("cycle"))
            )
            tb = tb.join(cycle_map, on="month", how="left")
        if not tb.is_empty() and "cycle" in tb.columns:
            band_cols = [c for c in tb.columns if c not in ("month", "cycle")]
            tou = tb.group_by("cycle").agg([pl.col(c).sum() for c in band_cols])
        else:
            tou = pl.DataFrame({"cycle": dfx["cycle"].unique()})

    # ---- EXPORT ----
    export = (
        dfx.filter(pl.col("flow") == "grid_export_solar")
        .group_by("cycle")
        .agg(pl.col("kwh").sum().alias("export_kwh"))
    )

    # ---- DEMAND ----
    if plan.demand:
        imp_cf = dfx.filter(pl.col("flow") == "grid_import")
        demand = transform.aggregate(
            imp_cf,
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
        demand = pl.DataFrame({"cycle": tou["cycle"].unique(), "demand_kw": 0.0})

    # ---- CONTROLLED LOAD (optional) ----
    controlled_load = None
    if include_controlled_load:
        controlled_load = (
            dfx.filter(pl.col("flow") == "controlled_load_import")
            .group_by("cycle")
            .agg(pl.col("kwh").sum().alias("controlled_load_kwh"))
        )

    # ---- TOTAL IMPORT (optional) ----
    total_import = None
    if include_total_import:
        total_import = (
            dfx.filter(pl.col("flow").str.contains("import"))
            .group_by("cycle")
            .agg(pl.col("kwh").sum().alias("total_import_kwh"))
        )

    # ---- MERGE ----
    out = tou.join(export, on="cycle", how="left").join(demand, on="cycle", how="left")
    if controlled_load is not None:
        out = out.join(controlled_load, on="cycle", how="left")
    if total_import is not None:
        out = out.join(total_import, on="cycle", how="left")

    # Fill numeric nulls
    num_cols = [c for c in out.columns if out[c].dtype in (pl.Float64, pl.Float32, pl.Int64, pl.Int32)]
    out = out.with_columns([pl.col(c).fill_null(0.0) for c in num_cols])

    # ---- EXACT DAY COUNTS ----
    def _days_from_label(lbl: str) -> int:
        import datetime as _dt
        s_str, e_str = lbl.split("→")
        s = _dt.date.fromisoformat(s_str)
        e = _dt.date.fromisoformat(e_str)
        return int((e - s).days) + 1

    days_list = [_days_from_label(str(lbl)) for lbl in out["cycle"].to_list()]
    out = out.with_columns(pl.Series(days_list, dtype=pl.Int32).alias("days_in_cycle"))
    return out


def compute_billables(
    df: CanonFrame,
    plan: Plan,
    *,
    mode: Literal["monthly", "cycles"] = "monthly",
    cycles: Optional[Iterable[Tuple[str | object, str | object]]] = None,
    include_controlled_load: bool = False,
    include_total_import: bool = False,
) -> pl.DataFrame:
    """
    Compute billable quantities (TOU, demand, export) for a plan.

    mode='monthly': one row per calendar month.
    mode='cycles': requires cycles= and returns one row per billing cycle.
    """
    if mode == "monthly":
        tou = transform.tou_bins(
            df.filter(pl.col("flow") == "grid_import"),
            bands=[b.__dict__ for b in plan.usage_bands],
        )
        export = (
            df.filter(pl.col("flow") == "grid_export_solar")
            .sort("t_start")
            .group_by_dynamic("t_start", every="1mo")
            .agg(pl.col("kwh").sum().alias("export_kwh"))
            .with_columns(pl.col("t_start").dt.strftime("%Y-%m").alias("month"))
            .select(["month", "export_kwh"])
        )

        # Base months from export or index range
        base = export.select("month").unique()
        if base.is_empty():
            ts = df["t_start"]
            if len(ts):
                min_ts = ts.min()
                max_ts = ts.max()
                month_range = pl.date_range(
                    min_ts.replace(day=1).date(),
                    max_ts.date(),
                    interval="1mo",
                    eager=True,
                )
                base = pl.DataFrame(
                    {"month": month_range.dt.strftime("%Y-%m")}
                )
        if base.is_empty() and not tou.is_empty():
            base = tou.select("month").unique()
        if base.is_empty():
            cols = ["month", "export_kwh", "demand_kw"] + [b.name for b in plan.usage_bands]
            return pl.DataFrame({c: pl.Series([], dtype=pl.String if c == "month" else pl.Float64) for c in cols})

        if tou.is_empty():
            tou = base.clone()
            for b in plan.usage_bands:
                tou = tou.with_columns(pl.lit(0.0).alias(b.name))

        # Demand
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
            demand = demand.with_columns(
                pl.col("t_start").dt.strftime("%Y-%m").alias("month")
            ).select(["month", "demand_kw"])
        else:
            demand = base.with_columns(pl.lit(0.0).alias("demand_kw"))

        # Optional controlled load
        controlled_load = None
        if include_controlled_load:
            controlled_load = (
                df.filter(pl.col("flow") == "controlled_load_import")
                .sort("t_start")
                .group_by_dynamic("t_start", every="1mo")
                .agg(pl.col("kwh").sum().alias("controlled_load_kwh"))
                .with_columns(pl.col("t_start").dt.strftime("%Y-%m").alias("month"))
                .select(["month", "controlled_load_kwh"])
            )

        # Optional total import
        total_import = None
        if include_total_import:
            total_import = (
                df.filter(pl.col("flow").str.contains("import"))
                .sort("t_start")
                .group_by_dynamic("t_start", every="1mo")
                .agg(pl.col("kwh").sum().alias("total_import_kwh"))
                .with_columns(pl.col("t_start").dt.strftime("%Y-%m").alias("month"))
                .select(["month", "total_import_kwh"])
            )

        out = (
            base.join(tou, on="month", how="left")
            .join(export, on="month", how="left")
            .join(demand, on="month", how="left")
        )
        if controlled_load is not None:
            out = out.join(controlled_load, on="month", how="left")
        if total_import is not None:
            out = out.join(total_import, on="month", how="left")

        num_cols = [c for c in out.columns if out[c].dtype in (pl.Float64, pl.Float32, pl.Int64, pl.Int32)]
        return out.with_columns([pl.col(c).fill_null(0.0) for c in num_cols])

    # cycles mode
    if not cycles:
        raise ValueError("cycles must be provided when mode='cycles'")
    return _cycle_billables(
        df, plan, cycles,
        include_controlled_load=include_controlled_load,
        include_total_import=include_total_import,
    )


def estimate_costs(
    bill: pl.DataFrame,
    plan: Plan,
    *,
    pay_on_time_discount: float = 0.0,
    include_gst: bool = False,
    gst_rate: float = 0.10,
) -> pl.DataFrame:
    """Estimate costs from billables (monthly or cycles)."""
    out = bill.clone()

    # Energy across TOU band columns
    energy = pl.lit(0.0)
    for b in plan.usage_bands:
        if b.name in out.columns:
            energy = energy + pl.col(b.name) * (b.rate_c_per_kwh / 100.0)
    out = out.with_columns(energy.alias("energy_cost"))

    # Demand cost
    if plan.demand and "demand_kw" in out.columns:
        out = out.with_columns(
            (pl.col("demand_kw") * plan.demand.rate_per_kw_per_month).alias("demand_cost")
        )
    else:
        out = out.with_columns(pl.lit(0.0).alias("demand_cost"))

    # Fixed cost (days in period)
    if "cycle" in out.columns:
        if "days_in_cycle" not in out.columns:
            def _days_from_label(lbl: str) -> int:
                import datetime as _dt
                s_str, e_str = lbl.split("→")
                s = _dt.date.fromisoformat(s_str)
                e = _dt.date.fromisoformat(e_str)
                return int((e - s).days) + 1
            days_list = [_days_from_label(str(lbl)) for lbl in out["cycle"].to_list()]
            out = out.with_columns(pl.Series(days_list, dtype=pl.Float64).alias("days_in_cycle"))
        days_expr = pl.col("days_in_cycle").cast(pl.Float64).fill_null(0.0)
    elif "month" in out.columns:
        out = out.with_columns(
            pl.col("month")
            .str.strptime(pl.Date, "%Y-%m")
            .dt.month_end()
            .dt.day()
            .cast(pl.Float64)
            .alias("_days_in_month")
        )
        days_expr = pl.col("_days_in_month")
    else:
        raise ValueError("bill must contain 'month' or 'cycle' column")

    out = out.with_columns(
        (pl.lit(plan.fixed_c_per_day / 100.0) * days_expr).alias("fixed_cost")
    )
    if "_days_in_month" in out.columns:
        out = out.drop("_days_in_month")

    for col in ("export_kwh", "energy_cost", "demand_cost", "fixed_cost"):
        if col not in out.columns:
            out = out.with_columns(pl.lit(0.0).alias(col))
    out = out.with_columns(
        [pl.col(c).fill_null(0.0).cast(pl.Float64) for c in ("export_kwh", "energy_cost", "demand_cost", "fixed_cost")]
    )

    # Feed-in credit (negative)
    out = out.with_columns(
        (pl.col("export_kwh") * (plan.feed_in_c_per_kwh / 100.0) * -1.0).alias("feed_in_credit")
    )

    out = out.with_columns(
        (pl.col("energy_cost") + pl.col("demand_cost") + pl.col("fixed_cost") + pl.col("feed_in_credit")).alias("subtotal")
    )

    charges_only = (pl.col("energy_cost") + pl.col("demand_cost") + pl.col("fixed_cost")).round(2)
    out = out.with_columns(
        (-(charges_only * float(pay_on_time_discount)).round(2)).alias("pay_on_time_discount")
    )

    if include_gst:
        out = out.with_columns(
            ((charges_only + pl.col("pay_on_time_discount")).clip(lower_bound=0.0) * float(gst_rate)).round(2).alias("gst")
        )
    else:
        out = out.with_columns(pl.lit(0.0).alias("gst"))

    out = out.with_columns(
        (pl.col("subtotal") + pl.col("pay_on_time_discount") + pl.col("gst")).alias("total")
    )

    # Order columns
    if "month" in out.columns:
        keep = ["month", "energy_cost", "demand_cost", "fixed_cost", "feed_in_credit",
                "pay_on_time_discount", "gst", "total"]
    else:
        keep = ["cycle", "days_in_cycle", "energy_cost", "demand_cost", "fixed_cost",
                "feed_in_credit", "pay_on_time_discount", "gst", "total"]
    return out.select([c for c in keep if c in out.columns])
