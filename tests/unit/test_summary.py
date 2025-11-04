import pandas as pd
import numpy as np
from datetime import datetime
import pytz

from meterdatalogic.features.summary import summarise

def test_summarise_basic_30min_data():
    tz = pytz.timezone("Australia/Brisbane")
    idx = pd.date_range(
        tz.localize(datetime(2025, 1, 1, 0, 0)),
        tz.localize(datetime(2025, 1, 3, 23, 30)),
        freq="30min",
    )
    # 3 days * 48 intervals/day = 144 rows
    df = pd.DataFrame(index=idx, data={"kwh": np.full(len(idx), 0.5)})
    stats = summarise(df)
    assert stats["n_days"] == 3
    # 0.5 kWh per 30min * 48 per day * 3 days = 72 kWh
    assert abs(stats["kwh_total"] - 72.0) < 1e-9
    assert abs(stats["avg_daily_kwh"] - 24.0) < 1e-9
    assert abs(stats["min_day_kwh"] - 24.0) < 1e-9
    assert abs(stats["max_day_kwh"] - 24.0) < 1e-9
