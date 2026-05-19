"""Tests for demand windows, grouping, profiles, and window_stats_from_profile."""

import pandas as pd
import pytest

from meterdatalogic import transform, ingest


def _cadence_min(idx):
    """Compute cadence in minutes via median delta (DST‑robust)."""
    deltas = pd.Series(idx).diff().dropna()
    if deltas.empty:
        return 60
    return int(deltas.median() / pd.Timedelta(minutes=1))


def _mk_df(idx, kwh=1.0, flow="grid_import"):
    """Build a minimal canonical-like frame for a single flow."""
    return pd.DataFrame(
        {
            "t_start": idx,
            "nmi": "Q123",
            "channel": "E1",
            "flow": flow,
            "kwh": kwh,
            "cadence_min": _cadence_min(idx),
        }
    ).set_index("t_start")


def test_window_aggregate_all_vs_mf(halfhour_rng):
    """MF demand must be <= ALL demand (weekends excluded)."""
    df = _mk_df(halfhour_rng)
    all_days = transform.aggregate(
        df,
        freq="1MS",
        flows=["grid_import"],
        metric="kW",
        stat="max",
        out_col="demand_kw",
        window_start="16:00",
        window_end="20:00",
        window_days="ALL",
    )
    mf_days = transform.aggregate(
        df,
        freq="1MS",
        flows=["grid_import"],
        metric="kW",
        stat="max",
        out_col="demand_kw",
        window_start="16:00",
        window_end="20:00",
        window_days="MF",
    )
    # align indexes and compare
    aligned = mf_days.join(all_days, how="inner", lsuffix="_mf", rsuffix="_all")
    assert aligned["demand_kw_mf"].le(aligned["demand_kw_all"]).all()


def test_window_aggregate_wrap_midnight(halfhour_rng):
    """Demand window crossing midnight should still produce non-negative kW."""
    df = _mk_df(halfhour_rng)
    wrap = transform.aggregate(
        df,
        freq="1MS",
        flows=["grid_import"],
        metric="kW",
        stat="max",
        out_col="demand_kw",
        window_start="22:00",
        window_end="03:00",
        window_days="ALL",
    )
    assert isinstance(wrap.index, pd.DatetimeIndex) and "demand_kw" in wrap.columns
    assert (wrap["demand_kw"] >= 0).all()


def test_groupby_day(canon_df_one_nmi):
    """Group by day returns at least one row and includes import column."""
    df = ingest.from_dataframe(canon_df_one_nmi)
    day = transform.aggregate(df, freq="1D", groupby="flow", pivot=True)
    assert "grid_import" in day.columns
    assert len(day.index) >= 1


def test_groupby_month(canon_df_one_nmi):
    """Group by month via generic function yields a monthly index and >=1 row."""
    df = ingest.from_dataframe(canon_df_one_nmi)
    month = transform.aggregate(df, freq="1MS", groupby="flow", pivot=True)
    assert isinstance(month.index, pd.DatetimeIndex)
    assert month.shape[0] >= 1


def test_window_aggregate_basic(canon_df_one_nmi):
    """Basic MF 16–21 window produces non-negative monthly peak demand."""
    df = ingest.from_dataframe(canon_df_one_nmi)
    demand = transform.aggregate(
        df,
        freq="1MS",
        flows=["grid_import"],
        metric="kW",
        stat="max",
        out_col="demand_kw",
        window_start="16:00",
        window_end="21:00",
        window_days="MF",
    )
    assert isinstance(demand.index, pd.DatetimeIndex) and "demand_kw" in demand.columns
    assert (demand["demand_kw"] >= 0).all()


def test_resample_energy_no_warning(canon_df_one_nmi, recwarn):
    """Resampling should not emit FutureWarnings from groupby/resample chain."""
    df = ingest.from_dataframe(canon_df_one_nmi)
    _ = transform.aggregate(
        df, freq="1h", groupby=["nmi", "channel", "flow"], value_col="kwh", pivot=False
    )
    assert not any("FutureWarning" in str(w.message) for w in recwarn.list)


def test_tou_bins_accepts_24_00(canon_df_one_nmi, tou_bands_basic):
    df = ingest.from_dataframe(canon_df_one_nmi)
    out = transform.tou_bins(df, tou_bands_basic)
    assert "month" in out.columns
    # Should have columns 'off', 'peak', 'shoulder' (even if some are zeros)
    for name in ["off", "peak", "shoulder"]:
        assert name in out.columns


# ------------------------------------------------------------------
# window_stats_from_profile
# ------------------------------------------------------------------


def _uniform_profile(kwh_per_slot: float = 1.0) -> pd.DataFrame:
    """Build a uniform 30-min average-day profile with import_total = kwh_per_slot."""
    slots = [f"{h:02d}:{m:02d}" for h in range(24) for m in (0, 30)]
    return pd.DataFrame({"slot": slots, "import_total": kwh_per_slot})


def test_window_stats_normal_window():
    """Window 16:00-21:00 covers 10 slots (5 h) in a 30-min profile."""
    prof = _uniform_profile(1.0)
    result = transform.window_stats_from_profile(
        prof, windows=[{"key": "peak", "start": "16:00", "end": "21:00"}], cadence_min=30
    )
    w = result["peak"]
    assert w["kwh_per_day"] == pytest.approx(10.0)
    assert w["avg_kw"] == pytest.approx(2.0)  # 10 kWh / 5 h
    assert w["share_of_daily_pct"] == pytest.approx(10 / 48 * 100)


def test_window_stats_24_00_end_boundary():
    """'24:00' end boundary is treated as midnight; 17:00-24:00 = 14 slots (7 h)."""
    prof = _uniform_profile(1.0)
    result = transform.window_stats_from_profile(
        prof, windows=[{"key": "evening", "start": "17:00", "end": "24:00"}], cadence_min=30
    )
    w = result["evening"]
    assert w["kwh_per_day"] == pytest.approx(14.0)
    assert w["avg_kw"] == pytest.approx(2.0)  # 14 kWh / 7 h


def test_window_stats_wrap_around_midnight():
    """Wrap-around window 22:00-02:00 covers 8 slots across midnight."""
    prof = _uniform_profile(1.0)
    result = transform.window_stats_from_profile(
        prof, windows=[{"key": "overnight", "start": "22:00", "end": "02:00"}], cadence_min=30
    )
    w = result["overnight"]
    assert w["kwh_per_day"] == pytest.approx(8.0)
    assert w["avg_kw"] == pytest.approx(2.0)  # 8 kWh / 4 h


def test_window_stats_multiple_windows_shares_sum():
    """Non-overlapping windows covering the full day should share = 100%."""
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
