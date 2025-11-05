from __future__ import annotations
import pandas as pd
from .types import Plan, ToUBand, DemandCharge
from .transform import tou_bins, demand_window

def monthly_billables(df: pd.DataFrame, plan: Plan) -> pd.DataFrame:
    tou = tou_bins(df[df["flow"] == "grid_import"], bands=[b.__dict__ for b in plan.usage_bands])
    # export credit
    export = (
        df[df["flow"] == "grid_export_solar"]
          .resample("1MS")["kwh"].sum()
          .rename("export_kwh")
          .reset_index()
    )
    export["month"] = export["t_start"].dt.strftime("%Y-%m")
    export = export[["month", "export_kwh"]]
    # demand
    demand = demand_window(df, start=plan.demand.window_start, end=plan.demand.window_end, days=plan.demand.days) \
        if plan.demand else pd.DataFrame({"month": pd.unique(tou["month"]), "demand_kw": 0.0})
    # fixed days
    days = df.resample("1MS").size().rename("rows").reset_index()
    days["month"] = days["t_start"].dt.strftime("%Y-%m")
    # merge
    out = tou.merge(export, on="month", how="left").merge(demand, on="month", how="left").merge(days[["month"]], on="month", how="left")
    out = out.fillna(0.0)
    return out

def estimate_monthly_cost(df: pd.DataFrame, plan: Plan) -> pd.DataFrame:
    bill = monthly_billables(df, plan)
    # energy cost
    energy_cost = 0.0
    for b in plan.usage_bands:
        col = b.name
        if col in bill.columns:
            energy_cost = energy_cost + (bill[col] * (b.rate_c_per_kwh / 100.0))
    bill["energy_cost"] = energy_cost
    # demand
    if plan.demand:
        bill["demand_cost"] = bill["demand_kw"] * plan.demand.rate_per_kw_per_month
    else:
        bill["demand_cost"] = 0.0
    # fixed cost — approximate by counting distinct months (1 charge per month)
    bill["fixed_cost"] = plan.fixed_c_per_day / 100.0 * 30.4375  # avg month days
    # feed-in credit
    bill["feed_in_credit"] = (bill.get("export_kwh", 0.0)) * (plan.feed_in_c_per_kwh / 100.0) * (-1.0)
    bill["total"] = bill[["energy_cost", "demand_cost", "fixed_cost", "feed_in_credit"]].sum(axis=1)
    return bill[["month", "energy_cost", "demand_cost", "fixed_cost", "feed_in_credit", "total"]]
