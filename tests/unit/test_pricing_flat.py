import pandas as pd
import numpy as np
import pytz
from datetime import datetime

from meterdatalogic.tariffs.schema import PlanComposite, FlatPlan, DailySupply
from meterdatalogic.tariffs.price_engine import price_monthly

def test_flat_plan_monthly_pricing():
    tz = pytz.timezone("Australia/Brisbane")
    idx = pd.date_range(tz.localize(datetime(2025,1,1)), tz.localize(datetime(2025,1,31,23,30)), freq="30min")
    df = pd.DataFrame(index=idx, data={"kwh": np.full(len(idx), 0.5)})
    plan = PlanComposite(energy=FlatPlan(
        name="Flat",
        daily_supply=DailySupply(cents_per_day=100.0),
        anytime_rate_cents_per_kwh=30.0
    ))
    out = price_monthly(df, plan)
    # Jan has 31 days
    assert out.shape[0] == 1
    usage = out.loc[0, "usage_kwh"]
    assert usage > 0
    supply = out.loc[0, "supply_cents"]
    assert abs(supply - 31*100.0) < 1e-9
    energy = out.loc[0, "energy_cost_cents"]
    assert abs(energy - usage*30.0) < 1e-9
