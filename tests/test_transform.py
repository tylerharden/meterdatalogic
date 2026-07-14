"""Tests for demand windows, grouping, profiles, seasonal_totals, and window_stats_from_profile."""

import datetime as _dt
import polars as pl
import pytest

from meterdatalogic import transform, ingest, canon

TZ = "Australia/Brisbane"


def _ts_range(start: str, periods: int, freq_min: int) -> pl.Series:
    base = _dt.datetime.fromisoformat(start)
    times = [base + _dt.timedelta(minutes=freq_min * i) for i in range(periods)]
    return pl.Series(times, dtype=pl.Datetime("us")).dt.replace_time_zone(TZ)


def _mk_df(ts: pl.Series, kwh=1.0, flow="grid_import") -> pl.DataFrame:
    n = len(ts)
    cadence = canon.infer_cadence_minutes(ts)
    return pl.DataFrame(
        {
            "t_start": ts,
            "nmi": pl.Series(["Q123"] * n),
            "channel": pl.Series(["E1"] * n),
            "flow": pl.Series([flow] * n),
            "kwh": pl.Series(
                [float(kwh)] * n if not hasattr(kwh, "__len__") else list(kwh), dtype=pl.Float64
            ),
            "cadence_min": pl.Series([cadence] * n, dtype=pl.Int32),
        }
    )


def test_window_aggregate_all_vs_mf(halfhour_rng):
    df = _mk_df(halfhour_rng)
    all_days = transform.demand_window(
        df,
        freq="1mo",
        flows=["grid_import"],
        stat="max",
        window_start="16:00",
        window_end="20:00",
        window_days="ALL",
    )
    mf_days = transform.demand_window(
        df,
        freq="1mo",
        flows=["grid_import"],
        stat="max",
        window_start="16:00",
        window_end="20:00",
        window_days="MF",
    )
    joined = mf_days.join(all_days, on="t_start", how="inner", suffix="_all")
    assert (joined["demand_kw"] <= joined["demand_kw_all"]).all()


def test_window_aggregate_wrap_midnight(halfhour_rng):
    df = _mk_df(halfhour_rng)
    wrap = transform.demand_window(
        df,
        freq="1mo",
        flows=["grid_import"],
        stat="max",
        window_start="22:00",
        window_end="03:00",
        window_days="ALL",
    )
    assert "t_start" in wrap.columns and "demand_kw" in wrap.columns
    assert (wrap["demand_kw"] >= 0).all()


def test_window_aggregate_basic(canon_df_one_nmi):
    df = ingest.from_dataframe(canon_df_one_nmi)
    demand = transform.demand_window(
        df,
        freq="1mo",
        flows=["grid_import"],
        stat="max",
        window_start="16:00",
        window_end="21:00",
        window_days="MF",
    )
    assert "t_start" in demand.columns and "demand_kw" in demand.columns
    assert (demand["demand_kw"] >= 0).all()


def test_tou_bins_accepts_24_00(canon_df_one_nmi, tou_bands_basic):
    df = ingest.from_dataframe(canon_df_one_nmi)
    out = transform.tou_bins(df, tou_bands_basic)
    assert "month" in out.columns
    for name in ["off", "peak", "shoulder"]:
        assert name in out.columns


# ------------------------------------------------------------------
# window_stats_from_profile
# ------------------------------------------------------------------


def _uniform_profile(kwh_per_slot: float = 1.0) -> pl.DataFrame:
    """Build a uniform 30-min average-day profile with import_total = kwh_per_slot."""
    slots = [f"{h:02d}:{m:02d}" for h in range(24) for m in (0, 30)]
    return pl.DataFrame(
        {
            "slot": pl.Series(slots),
            "import_total": pl.Series([float(kwh_per_slot)] * len(slots), dtype=pl.Float64),
        }
    )


def test_window_stats_normal_window():
    prof = _uniform_profile(1.0)
    result = transform.window_stats_from_profile(
        prof, windows=[{"key": "peak", "start": "16:00", "end": "21:00"}], cadence_min=30
    )
    w = result["peak"]
    assert w["kwh_per_day"] == pytest.approx(10.0)
    assert w["avg_kw"] == pytest.approx(2.0)
    assert w["share_of_daily_pct"] == pytest.approx(10 / 48 * 100)


def test_window_stats_24_00_end_boundary():
    prof = _uniform_profile(1.0)
    result = transform.window_stats_from_profile(
        prof, windows=[{"key": "evening", "start": "17:00", "end": "24:00"}], cadence_min=30
    )
    w = result["evening"]
    assert w["kwh_per_day"] == pytest.approx(14.0)
    assert w["avg_kw"] == pytest.approx(2.0)


def test_window_stats_wrap_around_midnight():
    prof = _uniform_profile(1.0)
    result = transform.window_stats_from_profile(
        prof, windows=[{"key": "overnight", "start": "22:00", "end": "02:00"}], cadence_min=30
    )
    w = result["overnight"]
    assert w["kwh_per_day"] == pytest.approx(8.0)
    assert w["avg_kw"] == pytest.approx(2.0)


def test_window_stats_multiple_windows_shares_sum():
    prof = _uniform_profile(1.0)
    windows = [
        {"key": "morning", "start": "00:00", "end": "12:00"},
        {"key": "afternoon", "start": "12:00", "end": "24:00"},
    ]
    result = transform.window_stats_from_profile(prof, windows=windows, cadence_min=30)
    total_share = (
        result["morning"]["share_of_daily_pct"] + result["afternoon"]["share_of_daily_pct"]
    )
    assert total_share == pytest.approx(100.0)


# ------------------------------------------------------------------
# demand_window: stat variants and freq=None
# ------------------------------------------------------------------


def test_demand_window_stat_mean(halfhour_rng):
    df = _mk_df(halfhour_rng)
    result = transform.demand_window(df, freq="1mo", stat="mean")
    assert "demand_kw" in result.columns
    assert (result["demand_kw"] > 0).all()


def test_daily_interval_profile_downsamples_to_configured_interval():
    ts = _ts_range("2025-01-01T00:00:00", 24 * 12, 5)
    df = _mk_df(ts, kwh=0.1).with_columns(pl.lit(5).cast(pl.Int32).alias("cadence_min"))
    result = transform.daily_interval_profile(df, interval_min=30)
    assert len(result) == 48
    assert result["slot"].head(2).to_list() == ["00:00", "00:30"]
    assert result["import_kw"][0] == pytest.approx(1.2)


def test_resample_intervals_sums_energy_and_preserves_flow_groups():
    ts = _ts_range("2025-01-01T00:00:00", 12, 5)
    imports = _mk_df(ts, kwh=0.1, flow="grid_import")
    exports = _mk_df(ts, kwh=0.05, flow="grid_export_solar").with_columns(
        pl.lit("B1").alias("channel")
    )
    df = pl.concat([imports, exports])

    result = transform.resample_intervals(df, interval_min=30)

    assert len(result) == 4
    assert set(result["flow"].to_list()) == {"grid_import", "grid_export_solar"}
    assert result.filter(pl.col("flow") == "grid_import")["kwh"][0] == pytest.approx(0.6)
    assert result.filter(pl.col("flow") == "grid_export_solar")["kwh"][0] == pytest.approx(0.3)
    assert result["cadence_min"].unique().to_list() == [30]


def test_resample_intervals_rejects_invalid_interval(halfhour_rng):
    df = _mk_df(halfhour_rng)
    with pytest.raises(ValueError, match="interval_min"):
        transform.resample_intervals(df, interval_min=0)


def test_demand_window_stat_sum(halfhour_rng):
    df = _mk_df(halfhour_rng)
    result = transform.demand_window(df, freq="1mo", stat="sum")
    assert "demand_kw" in result.columns
    assert (result["demand_kw"] > 0).all()


def test_demand_window_freq_none_returns_single_value(halfhour_rng):
    df = _mk_df(halfhour_rng)
    result = transform.demand_window(df, freq=None, stat="max")
    assert len(result) == 1
    assert "demand_kw" in result.columns


def test_demand_window_freq_none_groupby(halfhour_rng):
    df = _mk_df(halfhour_rng)
    result = transform.demand_window(df, freq=None, stat="max", groupby="flow")
    assert "demand_kw" in result.columns
    assert "flow" in result.columns


# ------------------------------------------------------------------
# seasonal_totals
# ------------------------------------------------------------------


def test_seasonal_totals_southern_has_summer_and_winter():
    ts_jan = _ts_range("2025-01-01T00:00:00", 48 * 31, 30)
    ts_jun = _ts_range("2025-06-01T00:00:00", 48 * 30, 30)
    ts = pl.concat([ts_jan, ts_jun])
    n = len(ts)
    df = pl.DataFrame(
        {
            "t_start": ts,
            "nmi": pl.Series(["Q"] * n),
            "channel": pl.Series(["E1"] * n),
            "flow": pl.Series(["grid_import"] * n),
            "kwh": pl.Series([1.0] * n, dtype=pl.Float64),
            "cadence_min": pl.Series([30] * n, dtype=pl.Int32),
        }
    ).sort("t_start")
    out = transform.seasonal_totals(df, hemisphere="southern")
    seasons = out["season"].to_list()
    assert "Summer" in seasons
    assert "Winter" in seasons
    assert "year" in out.columns and "flow" in out.columns and "kwh" in out.columns


def test_seasonal_totals_december_assigned_to_next_year():
    ts_dec = _ts_range("2024-12-01T00:00:00", 48 * 31, 30)
    n = len(ts_dec)
    df = pl.DataFrame(
        {
            "t_start": ts_dec,
            "nmi": pl.Series(["Q"] * n),
            "channel": pl.Series(["E1"] * n),
            "flow": pl.Series(["grid_import"] * n),
            "kwh": pl.Series([1.0] * n, dtype=pl.Float64),
            "cadence_min": pl.Series([30] * n, dtype=pl.Int32),
        }
    )
    out = transform.seasonal_totals(df, hemisphere="southern")
    summer = out.filter(pl.col("season") == "Summer")
    assert len(summer) > 0
    assert 2025 in summer["year"].to_list()


def test_seasonal_totals_northern_hemisphere():
    ts_jun = _ts_range("2025-06-01T00:00:00", 48 * 30, 30)
    n = len(ts_jun)
    df = pl.DataFrame(
        {
            "t_start": ts_jun,
            "nmi": pl.Series(["Q"] * n),
            "channel": pl.Series(["E1"] * n),
            "flow": pl.Series(["grid_import"] * n),
            "kwh": pl.Series([1.0] * n, dtype=pl.Float64),
            "cadence_min": pl.Series([30] * n, dtype=pl.Int32),
        }
    )
    out = transform.seasonal_totals(df, hemisphere="northern")
    assert "Summer" in out["season"].to_list()


def test_seasonal_totals_empty_df():
    empty = canon.empty_canon_frame()
    out = transform.seasonal_totals(empty, hemisphere="southern")
    assert out.is_empty()
    assert "season" in out.columns


def test_seasonal_totals_flow_filter_excludes_all(halfhour_rng):
    df = _mk_df(halfhour_rng)
    out = transform.seasonal_totals(df, hemisphere="southern", flows=["nonexistent"])
    assert out.is_empty()


# ------------------------------------------------------------------
# profile
# ------------------------------------------------------------------


def test_profile_returns_48_slots_for_30min(halfhour_rng):
    df = _mk_df(halfhour_rng)
    prof = transform.profile(df, reducer="mean", include_import_total=True)
    assert len(prof) == 48
    assert "slot" in prof.columns


def test_profile_import_total_present(halfhour_rng):
    df = _mk_df(halfhour_rng)
    prof = transform.profile(df, include_import_total=True)
    assert "import_total" in prof.columns
    assert (prof["import_total"] >= 0).all()


def test_profile_by_not_slot_raises(halfhour_rng):
    df = _mk_df(halfhour_rng)
    with pytest.raises(NotImplementedError):
        transform.profile(df, by="day")  # type: ignore[arg-type]


# ------------------------------------------------------------------
# period_breakdown
# ------------------------------------------------------------------


def test_period_breakdown_daily_structure(halfhour_rng):
    df = _mk_df(halfhour_rng)
    result = transform.period_breakdown(df, freq="1d")
    assert set(result.keys()) == {"total", "peaks", "average"}
    assert "day" in result["total"].columns
    assert len(result["total"]) == 7


def test_period_breakdown_monthly_structure(halfhour_rng):
    df = _mk_df(halfhour_rng)
    result = transform.period_breakdown(df, freq="1mo")
    assert set(result.keys()) == {"total", "peaks", "average"}
    assert "month" in result["total"].columns
