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


def test_demand_window_all_vs_mf(halfhour_rng):
    """MF demand must be <= ALL demand (weekends excluded)."""
    df = _mk_df(halfhour_rng)
    all_days = transform.demand_window(df, start="16:00", end="20:00", days="ALL")
    mf_days = transform.demand_window(df, start="16:00", end="20:00", days="MF")
    assert mf_days["demand_kw"].le(all_days["demand_kw"]).all()


def test_demand_window_wrap_midnight(halfhour_rng):
    """Demand window crossing midnight should still produce non-negative kW."""
    df = _mk_df(halfhour_rng)
    wrap = transform.demand_window(df, start="22:00", end="03:00", days="ALL")
    assert "month" in wrap.columns and "demand_kw" in wrap.columns
    assert (wrap["demand_kw"] >= 0).all()


def test_groupby_day(canon_df_one_nmi):
    """Group by day returns at least one row and includes import column."""
    df = ingest.from_dataframe(canon_df_one_nmi)
    day = transform.groupby_day(df)
    assert "grid_import" in day.columns
    assert len(day.index) >= 1


def test_groupby_month(canon_df_one_nmi):
    """Group by month yields a month label column and >=1 row."""
    df = ingest.from_dataframe(canon_df_one_nmi)
    month = transform.groupby_month(df)
    assert "month" in month.columns
    assert month.shape[0] >= 1


def test_profile24_shape(canon_df_one_nmi):
    """Profile24 should produce 48 slots for 30‑min cadence."""
    df = ingest.from_dataframe(canon_df_one_nmi)
    prof = transform.profile24(df)
    assert prof["slot"].nunique() == 48


def test_demand_window(canon_df_one_nmi):
    """Basic MF 16–21 window produces non-negative monthly peak demand."""
    df = ingest.from_dataframe(canon_df_one_nmi)
    demand = transform.demand_window(df, start="16:00", end="21:00", days="MF")
    assert set(demand.columns) == {"month", "demand_kw"}
    assert (demand["demand_kw"] >= 0).all()


def test_resample_energy_no_warning(canon_df_one_nmi, recwarn):
    """Resampling should not emit FutureWarnings from groupby/resample chain."""
    df = ingest.from_dataframe(canon_df_one_nmi)
    _ = transform.resample_energy(df, "1H")
    assert not any("FutureWarning" in str(w.message) for w in recwarn.list)


def test_tou_bins_accepts_24_00(canon_df_one_nmi, tou_bands_basic):
    df = ingest.from_dataframe(canon_df_one_nmi)
    out = transform.tou_bins(df, tou_bands_basic)
    assert "month" in out.columns
    # Should have columns 'off', 'peak', 'shoulder' (even if some are zeros)
    for name in ["off", "peak", "shoulder"]:
        assert name in out.columns
