"""Tests for demand windows, grouping, and profiles in transform."""

import pandas as pd

import meterdatalogic.transform as transform
import meterdatalogic.ingest as ingest


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
        df, freq="1H", groupby=["nmi", "channel", "flow"], value_col="kwh", pivot=False
    )
    assert not any("FutureWarning" in str(w.message) for w in recwarn.list)


def test_tou_bins_accepts_24_00(canon_df_one_nmi, tou_bands_basic):
    df = ingest.from_dataframe(canon_df_one_nmi)
    out = transform.tou_bins(df, tou_bands_basic)
    assert "month" in out.columns
    # Should have columns 'off', 'peak', 'shoulder' (even if some are zeros)
    for name in ["off", "peak", "shoulder"]:
        assert name in out.columns
