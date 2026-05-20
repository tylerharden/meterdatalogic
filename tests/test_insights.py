"""Tests for insights evaluators (intermediate and advanced)."""

import datetime as _dt
import numpy as np
import polars as pl

from meterdatalogic import ingest
from meterdatalogic.analytics.insights import InsightConfig
from meterdatalogic.analytics.insights import evaluators_intermediate, evaluators_advanced

TZ = "Australia/Brisbane"


def _ts_range(start: str, periods: int, freq_min: int) -> pl.Series:
    base = _dt.datetime.fromisoformat(start)
    times = [base + _dt.timedelta(minutes=freq_min * i) for i in range(periods)]
    return pl.Series(times, dtype=pl.Datetime("us")).dt.replace_time_zone(TZ)


def _import_df(ts: pl.Series, kwh=0.5) -> pl.DataFrame:
    n = len(ts)
    kwh_vals = [float(kwh)] * n if not hasattr(kwh, "__len__") else [float(v) for v in kwh]
    return pl.DataFrame(
        {
            "t_start": ts,
            "nmi": pl.Series(["Q1234567890"] * n),
            "channel": pl.Series(["E1"] * n),
            "flow": pl.Series(["grid_import"] * n),
            "kwh": pl.Series(kwh_vals, dtype=pl.Float64),
            "cadence_min": pl.Series([30] * n, dtype=pl.Int32),
        }
    )


# ------------------------------------------------------------------
# peak_demand_characteristics
# ------------------------------------------------------------------


def test_peak_demand_characteristics_returns_none_on_empty():
    from meterdatalogic import utils
    df = utils.empty_canon_frame(tz=TZ)
    assert evaluators_intermediate.peak_demand_characteristics(df, config=InsightConfig()) is None


def test_peak_demand_characteristics_returns_none_if_too_short():
    ts = _ts_range("2025-01-01T00:00:00", 48 * 3, 30)
    df = ingest.from_dataframe(_import_df(ts))
    assert evaluators_intermediate.peak_demand_characteristics(df, config=InsightConfig()) is None


def test_peak_demand_characteristics_returns_insight_with_14_days():
    ts = _ts_range("2025-01-01T00:00:00", 48 * 14, 30)
    df = ingest.from_dataframe(_import_df(ts, kwh=0.5))
    result = evaluators_intermediate.peak_demand_characteristics(df, config=InsightConfig())
    assert result is not None
    assert result.id == "peak_demand_characteristics"
    assert result.metrics["mean_peak_kw"] > 0
    assert result.metrics["p95_peak_kw"] >= result.metrics["mean_peak_kw"]
    assert result.severity == "info"


def test_peak_demand_characteristics_spiky_data_triggers_warning():
    ts = _ts_range("2025-01-01T00:00:00", 48 * 14, 30)
    kwh_arr = np.full(len(ts), 0.2)
    ts_list = ts.to_list()
    spike_date = _dt.date(2025, 1, 4)
    for i, t in enumerate(ts_list):
        if t.date() == spike_date and 16 <= t.hour < 21:
            kwh_arr[i] = 5.0
    df = ingest.from_dataframe(_import_df(ts, kwh=kwh_arr))
    result = evaluators_intermediate.peak_demand_characteristics(df, config=InsightConfig())
    assert result is not None
    assert result.severity == "warning"
    assert result.metrics["spiky_ratio"] >= InsightConfig().intermediate.spiky_ratio_threshold


# ------------------------------------------------------------------
# step_change_baseload
# ------------------------------------------------------------------


def test_step_change_baseload_returns_none_on_empty():
    from meterdatalogic import utils
    df = utils.empty_canon_frame(tz=TZ)
    assert evaluators_advanced.step_change_baseload(df, config=InsightConfig()) is None


def test_step_change_baseload_returns_none_if_too_short():
    ts = _ts_range("2025-01-01T00:00:00", 48 * 20, 30)
    df = ingest.from_dataframe(_import_df(ts))
    assert evaluators_advanced.step_change_baseload(df, config=InsightConfig()) is None


def test_step_change_baseload_no_insight_on_uniform_data():
    ts = _ts_range("2025-01-01T00:00:00", 48 * 60, 30)
    df = ingest.from_dataframe(_import_df(ts, kwh=0.4))
    result = evaluators_advanced.step_change_baseload(df, config=InsightConfig())
    assert result is None


def test_step_change_baseload_detects_step_up():
    ts_low = _ts_range("2025-01-01T00:00:00", 48 * 30, 30)
    ts_high = _ts_range("2025-02-01T00:00:00", 48 * 30, 30)
    df_low = _import_df(ts_low, kwh=0.2)
    df_high = _import_df(ts_high, kwh=0.6)
    df = ingest.from_dataframe(pl.concat([df_low, df_high]).sort("t_start"))
    result = evaluators_advanced.step_change_baseload(df, config=InsightConfig())
    assert result is not None
    assert result.id == "step_change_baseload"
    assert result.metrics["change_pct"] >= InsightConfig().advanced.step_change_pct_threshold


def test_step_change_baseload_detects_step_down():
    ts_high = _ts_range("2025-01-01T00:00:00", 48 * 30, 30)
    ts_low = _ts_range("2025-02-01T00:00:00", 48 * 30, 30)
    df_high = _import_df(ts_high, kwh=0.6)
    df_low = _import_df(ts_low, kwh=0.2)
    df = ingest.from_dataframe(pl.concat([df_high, df_low]).sort("t_start"))
    result = evaluators_advanced.step_change_baseload(df, config=InsightConfig())
    assert result is not None
    assert "decrease" in result.message
