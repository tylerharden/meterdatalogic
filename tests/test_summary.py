"""Tests for the summary module."""

import datetime as _dt
import polars as pl
import pytest

import meterdatalogic as ml

TZ = "Australia/Brisbane"


def _ts_range(start: str, periods: int, freq_min: int) -> pl.Series:
    base = _dt.datetime.fromisoformat(start)
    times = [base + _dt.timedelta(minutes=freq_min * i) for i in range(periods)]
    return pl.Series(times, dtype=pl.Datetime("us")).dt.replace_time_zone(TZ)


def _import_df(ts: pl.Series, kwh=0.5) -> pl.DataFrame:
    n = len(ts)
    return pl.DataFrame(
        {
            "t_start": ts,
            "nmi": pl.Series(["Q1234567890"] * n),
            "channel": pl.Series(["E1"] * n),
            "flow": pl.Series(["grid_import"] * n),
            "kwh": pl.Series([float(kwh)] * n if not hasattr(kwh, "__len__") else list(kwh), dtype=pl.Float64),
            "cadence_min": pl.Series([30] * n, dtype=pl.Int32),
        }
    )


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
    ts = _ts_range("2025-01-01T00:00:00", 2, 30)
    df = pl.DataFrame(
        {
            "t_start": pl.concat([ts.head(1), ts.head(1), ts.tail(1)]),
            "nmi": pl.Series(["N1", "N1", "N1"]),
            "channel": pl.Series(["E1", "B1", "E1"]),
            "flow": pl.Series(["grid_import", "grid_export_solar", "grid_import"]),
            "kwh": pl.Series([0.9, 0.7, 0.5], dtype=pl.Float64),
            "cadence_min": pl.Series([30, 30, 30], dtype=pl.Int32),
        }
    )
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
    all_ts = _ts_range("2025-01-01T00:00:00", 48, 30)
    hours = all_ts.dt.hour().to_numpy()
    night_mask = ~((hours >= 8) & (hours < 16))
    day_mask = (hours >= 8) & (hours < 16)

    night_ts = all_ts.filter(pl.Series(night_mask.tolist()))
    day_ts = all_ts.filter(pl.Series(day_mask.tolist()))

    n_night = len(night_ts)
    n_day = len(day_ts)

    imp = pl.DataFrame({
        "t_start": night_ts,
        "nmi": pl.Series(["Q"] * n_night),
        "channel": pl.Series(["E1"] * n_night),
        "flow": pl.Series(["grid_import"] * n_night),
        "kwh": pl.Series([0.5] * n_night, dtype=pl.Float64),
        "cadence_min": pl.Series([30] * n_night, dtype=pl.Int32),
    })
    exp = pl.DataFrame({
        "t_start": day_ts,
        "nmi": pl.Series(["Q"] * n_day),
        "channel": pl.Series(["B1"] * n_day),
        "flow": pl.Series(["grid_export_solar"] * n_day),
        "kwh": pl.Series([0.4] * n_day, dtype=pl.Float64),
        "cadence_min": pl.Series([30] * n_day, dtype=pl.Int32),
    })
    df = ml.ingest.from_dataframe(pl.concat([imp, exp]))
    stats = ml.summary.summarise(df)["stats"]
    assert stats["total_import_kwh"] == pytest.approx(n_night * 0.5)
    assert stats["solar_export_kwh"] == pytest.approx(n_day * 0.4)


# ------------------------------------------------------------------
# Window stats
# ------------------------------------------------------------------


def test_window_shares_sum_to_100(canon_df_one_nmi):
    df = ml.ingest.from_dataframe(canon_df_one_nmi)
    windows = ml.summary.summarise(df)["stats"]["windows"]
    total = sum(w["share_of_daily_pct"] for w in windows.values())
    assert total == pytest.approx(100.0)


def test_window_avg_kw_positive_for_nonzero_import(canon_df_one_nmi):
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
    df = ml.ingest.from_dataframe(canon_df_one_nmi)
    stats = ml.summary.summarise(df)["stats"]
    base_kwh = stats["base"]["base_kwh_per_day"]
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
    ts = _ts_range("2025-01-01T00:00:00", 48 * 59, 30)
    df = _import_df(ts)
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
