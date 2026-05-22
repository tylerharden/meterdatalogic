"""Tests for demand windows, grouping, profiles, and window_stats_from_profile."""

import polars as pl
import pytest

from meterdatalogic import transform, ingest, utils


def _mk_df(ts: pl.Series, kwh=1.0, flow="grid_import") -> pl.DataFrame:
    n = len(ts)
    cadence = utils.infer_cadence_minutes(ts)
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
