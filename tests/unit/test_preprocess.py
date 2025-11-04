import pandas as pd
import numpy as np
import pytz
from datetime import datetime

from meterdatalogic.preprocess.clean import clean_basic
from meterdatalogic.preprocess.resample import resample_to

def _tz():
    import pytz
    return pytz.timezone("Australia/Brisbane")

def test_clean_basic_removes_dupes_and_fills():
    tz = _tz()
    idx = pd.to_datetime(
        [tz.localize(datetime(2025,1,1,0,0)), tz.localize(datetime(2025,1,1,0,30)),
         tz.localize(datetime(2025,1,1,0,30))]
    )
    df = pd.DataFrame(index=idx, data={"kwh":[0.5, None, 0.7]})
    out = clean_basic(df, fill_method="zero")
    assert out.index.is_monotonic_increasing
    assert out.shape[0] == 2
    assert out["kwh"].iloc[0] == 0.5
    assert out["kwh"].iloc[1] == 0.7  # last duplicate kept

def test_resample_to_hourly_sums_energy():
    tz = _tz()
    idx = pd.date_range(tz.localize(datetime(2025,1,1,0)), periods=4, freq="15min")
    df = pd.DataFrame(index=idx, data={"kwh":[0.1,0.1,0.1,0.1]})
    hourly = resample_to(df, "1H")
    assert hourly.shape[0] == 1
    assert abs(hourly["kwh"].iloc[0] - 0.4) < 1e-9
