import pandas as pd
import numpy as np
import meterdatalogic as ml


def test_summary_peak_with_duplicate_timestamps():
    idx = pd.date_range("2025-01-01", periods=2, freq="30min", tz="Australia/Brisbane")
    df = pd.DataFrame(
        {
            "t_start": [idx[0], idx[0], idx[1]],
            "nmi": ["N1", "N1", "N1"],
            "channel": ["E1", "B1", "E1"],
            "flow": ["grid_import", "grid_export_solar", "grid_import"],
            "kwh": [0.9, 0.7, 0.5],
            "cadence_min": 30,
        }
    ).set_index("t_start")
    ml.validate.assert_canon(df)
    s = ml.summary.summarise(df)
    assert s["peaks"]["max_interval_kwh"] == 0.9
