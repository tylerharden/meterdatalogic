"""Tests for the summary module.

Covers payload structure, energy arithmetic, window stats, solar tracking,
period breakdowns, peaks, and the base/top-hours derived stats.
"""

import pandas as pd
import pytest

import meterdatalogic as ml

TZ = "Australia/Brisbane"


def _import_df(rng, kwh=0.5):
    return pd.DataFrame(
        {"t_start": rng, "nmi": "Q1234567890", "channel": "E1", "kwh": kwh}
    ).set_index("t_start")


# ------------------------------------------------------------------
# Smoke / structure
# ------------------------------------------------------------------


def test_summary_payload_structure(canon_df_mixed_flows):
    df = ml.ingest.from_dataframe(canon_df_mixed_flows, nmi="Q1234567890")
    payload = ml.summary.summarise(df)
    assert "meta" in payload and "stats" in payload and "datasets" in payload
    assert payload["meta"]["cadence_min"] == 30
    assert payload["meta"]["nmis"] == 1
    assert len(payload["datasets"]["profile24"]) >= 1


def test_summary_peak_with_duplicate_timestamps():
    idx = pd.date_range("2025-01-01", periods=2, freq="30min", tz=TZ)
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


# ------------------------------------------------------------------
# Meta fields
# ------------------------------------------------------------------


def test_meta_fields_correct(canon_df_one_nmi):
    df = ml.ingest.from_dataframe(canon_df_one_nmi)
    meta = ml.summary.summarise(df)["meta"]
    assert meta["cadence_min"] == 30
    assert meta["nmis"] == 1
    assert meta["days"] == 7
    assert "grid_import" in meta["flows"]
    assert "E1" in meta["channels"]


# ------------------------------------------------------------------
# Energy arithmetic
# ------------------------------------------------------------------


def test_total_import_and_per_day_arithmetic(canon_df_one_nmi):
    """7 days × 48 intervals × 0.5 kWh = 168 kWh; per-day avg = 24 kWh."""
    df = ml.ingest.from_dataframe(canon_df_one_nmi)
    stats = ml.summary.summarise(df)["stats"]
    assert stats["total_import_kwh"] == pytest.approx(168.0)
    assert stats["per_day_avg_kwh"] == pytest.approx(24.0)


def test_import_only_has_zero_solar_export(canon_df_one_nmi):
    df = ml.ingest.from_dataframe(canon_df_one_nmi)
    assert ml.summary.summarise(df)["stats"]["solar_export_kwh"] == 0.0


def test_solar_export_tracked_separately_from_import():
    """Solar customer: import and export totals are computed independently."""
    rng = pd.date_range("2025-01-01", periods=48, freq="30min", tz=TZ)
    night = [ts for ts in rng if not (8 <= ts.hour < 16)]  # 32 intervals
    day = [ts for ts in rng if 8 <= ts.hour < 16]  # 16 intervals
    imp = pd.DataFrame({"t_start": night, "nmi": "Q", "channel": "E1", "kwh": 0.5}).set_index(
        "t_start"
    )
    exp = pd.DataFrame({"t_start": day, "nmi": "Q", "channel": "B1", "kwh": 0.4}).set_index(
        "t_start"
    )
    df = ml.ingest.from_dataframe(pd.concat([imp, exp]))
    stats = ml.summary.summarise(df)["stats"]
    assert stats["total_import_kwh"] == pytest.approx(len(night) * 0.5)  # 16.0
    assert stats["solar_export_kwh"] == pytest.approx(len(day) * 0.4)  # 6.4


# ------------------------------------------------------------------
# Window stats
# ------------------------------------------------------------------


def test_window_shares_sum_to_100(canon_df_one_nmi):
    """The four hardcoded time windows cover the full day → shares = 100%."""
    df = ml.ingest.from_dataframe(canon_df_one_nmi)
    windows = ml.summary.summarise(df)["stats"]["windows"]
    total = sum(w["share_of_daily_pct"] for w in windows.values())
    assert total == pytest.approx(100.0)


def test_window_avg_kw_positive_for_nonzero_import(canon_df_one_nmi):
    """All windows should have positive avg_kw when there is import throughout the day."""
    df = ml.ingest.from_dataframe(canon_df_one_nmi)
    windows = ml.summary.summarise(df)["stats"]["windows"]
    for key, w in windows.items():
        assert w["avg_kw"] > 0, f"Window '{key}' has zero avg_kw"
        assert w["kwh_per_day"] > 0


# ------------------------------------------------------------------
# Base load
# ------------------------------------------------------------------


def test_base_load_within_bounds(canon_df_one_nmi):
    df = ml.ingest.from_dataframe(canon_df_one_nmi)
    base = ml.summary.summarise(df)["stats"]["base"]
    assert base["base_kw"] >= 0
    assert base["base_kwh_per_day"] >= 0
    assert 0 <= base["share_of_daily_pct"] <= 100


def test_base_load_uniform_data_approx_load(canon_df_one_nmi):
    """For completely uniform import, base ≈ average (min interval ≈ mean)."""
    df = ml.ingest.from_dataframe(canon_df_one_nmi)
    stats = ml.summary.summarise(df)["stats"]
    base_kwh = stats["base"]["base_kwh_per_day"]
    # Uniform 0.5 kWh / interval → base_kwh should equal per_day_avg
    assert base_kwh == pytest.approx(stats["per_day_avg_kwh"])


# ------------------------------------------------------------------
# Peaks
# ------------------------------------------------------------------


def test_peak_interval_kwh_matches_max(canon_df_one_nmi):
    df = ml.ingest.from_dataframe(canon_df_one_nmi)
    peaks = ml.summary.summarise(df)["stats"]["peaks"]
    assert peaks["max_interval_kwh"] == pytest.approx(0.5)
    assert peaks["max_interval_time"] is not None


# ------------------------------------------------------------------
# Top hours
# ------------------------------------------------------------------


def test_top_hours_structure(canon_df_one_nmi):
    df = ml.ingest.from_dataframe(canon_df_one_nmi)
    top = ml.summary.summarise(df)["stats"]["top_hours"]
    assert len(top["hours"]) == 4
    assert 0 <= top["share_of_daily_pct"] <= 100
    assert top["kwh_total"] >= 0


# ------------------------------------------------------------------
# Period breakdowns
# ------------------------------------------------------------------


def test_daily_breakdown_row_count(canon_df_one_nmi):
    """7-day fixture → 7 rows in days.total."""
    df = ml.ingest.from_dataframe(canon_df_one_nmi)
    days = ml.summary.summarise(df)["datasets"]["days"]["total"]
    assert len(days) == 7
    assert "day" in days[0]


def test_monthly_breakdown_spans_two_months():
    """Data crossing a month boundary → 2 entries in months.total."""
    rng = pd.date_range("2025-01-01", periods=48 * 59, freq="30min", tz=TZ)  # Jan+Feb 2025
    df = ml.ingest.from_dataframe(_import_df(rng))
    months = ml.summary.summarise(df)["datasets"]["months"]["total"]
    assert len(months) == 2
    assert "month" in months[0]


# ------------------------------------------------------------------
# Datasets structure
# ------------------------------------------------------------------


def test_datasets_keys_present(canon_df_one_nmi):
    df = ml.ingest.from_dataframe(canon_df_one_nmi)
    datasets = ml.summary.summarise(df)["datasets"]
    assert "profile24" in datasets
    assert "days" in datasets and "months" in datasets and "seasons" in datasets
    assert {"total", "peaks", "average"} == set(datasets["days"].keys())
    assert {"total", "peaks", "average"} == set(datasets["months"].keys())
