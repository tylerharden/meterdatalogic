"""Tests for summary feature."""

import pandas as pd

import meterdatalogic as ml


def test_summary_payload_structure(canon_df_mixed_flows):
    df = ml.ingest.from_dataframe(canon_df_mixed_flows, nmi=1234567890)
    payload = ml.summary.summarise(df)
    assert "meta" in payload and "stats" in payload and "datasets" in payload
    assert payload["meta"]["cadence_min"] == 30
    assert payload["meta"]["nmis"] == 1
    # profile24 has slots
    assert len(payload["datasets"]["profile24"]) >= 1


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
    assert s["stats"]["peaks"]["max_interval_kwh"] == 0.9
