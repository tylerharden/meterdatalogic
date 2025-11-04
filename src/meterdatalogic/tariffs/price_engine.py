from __future__ import annotations
import pandas as pd
from .schema import PlanComposite, FlatPlan, TouPlan

def price_monthly(df: pd.DataFrame, plan: PlanComposite) -> pd.DataFrame:
    """
    Returns a monthly table with columns: usage_kwh, energy_cost_cents, supply_cents, total_cents.
    For now implement flat plan only; TOU to follow.
    """
    if "kwh" not in df.columns:
        raise ValueError("DataFrame must contain 'kwh'")
    monthly = df["kwh"].resample("MS").sum().to_frame("usage_kwh")

    supply_cpd = plan.energy.daily_supply.cents_per_day
    days_per_month = df["kwh"].resample("MS").apply(lambda s: s.index.days_in_month[0])
    monthly["supply_cents"] = days_per_month * supply_cpd

    if isinstance(plan.energy, FlatPlan):
        rate = plan.energy.anytime_rate_cents_per_kwh
        monthly["energy_cost_cents"] = monthly["usage_kwh"] * rate
    else:
        # placeholder until TOU implemented
        monthly["energy_cost_cents"] = 0.0

    monthly["total_cents"] = monthly["supply_cents"] + monthly["energy_cost_cents"]
    return monthly.reset_index().rename(columns={"index": "month"})
