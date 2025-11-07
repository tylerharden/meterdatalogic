"""Scenario tests for EV, PV, battery, and the run() orchestrator."""

import numpy as np
import pandas as pd
import pytest

import meterdatalogic.scenario as scenario
import meterdatalogic.types as mdtypes
from meterdatalogic import utils


@pytest.fixture
def day_30min():
    """One local day at 30‑min cadence (Brisbane, no DST)."""
    return pd.date_range(
        "2025-01-01", periods=48, freq="30min", tz="Australia/Brisbane"
    )


@pytest.fixture
def base_df(day_30min):
    """Canonical-like baseline: 0.5 kWh import per interval, single NMI/channel."""
    return utils.build_canon_frame(
        day_30min,
        np.full(len(day_30min), 0.5),
        nmi="Q123",
        channel="E1",
        flow="grid_import",
        cadence_min=30,
    )


def test_apply_ev_immediate_window_and_limits(day_30min):
    """Input:
    - idx: one day, 30-min intervals, tz-aware.
    - EVConfig: 8 kWh/day target, max 7 kW, window 18:00–22:00, ALL days, 'immediate'.
    Exercise:
    - Window masking and per-interval limit (kW × interval_h).
    Expect:
    - Series length == len(idx).
    - Nonzeros only within 18:00–22:00 local.
    - s.max() ≤ max_kw × 0.5 kWh.
    - Sum ≈ daily_kwh within tolerance (if implemented).
    """
    idx = day_30min
    cfg = mdtypes.EVConfig(
        daily_kwh=8.0,
        max_kw=7.0,
        window_start="18:00",
        window_end="22:00",
        days="ALL",
        strategy="immediate",
    )
    try:
        s = scenario._apply_ev(idx, cfg, interval_h=0.5)
    except NotImplementedError:
        pytest.xfail("_apply_ev not implemented")

    assert isinstance(s, pd.Series) and len(s) == len(idx)
    # Only inside [18:00,22:00)
    times = pd.Series(idx.time, index=idx)
    in_win = utils.time_in_range(
        times,
        pd.Timestamp("2000-01-01 18:00").time(),
        pd.Timestamp("2000-01-01 22:00").time(),
    )
    assert (s[~in_win] == 0).all()
    # Per-interval cap
    assert s.max() <= cfg.max_kw * 0.5 + 1e-9
    # Total close to target (allow tolerance if discretization prevents exact match)
    assert abs(s.sum() - cfg.daily_kwh) <= 0.5


def test_apply_pv_basic_contract(day_30min):
    """Input:
    - idx: one day, 30-min intervals.
    - PVConfig: reasonable system_kwp/inverter_kw/loss_fraction.
    Exercise:
    - Shape generation, loss/clipping, interval scaling.
    Expect:
    - Series length == len(idx), dtype float, non-negative.
    - Zeros likely at night; no values exceed inverter_kw × interval_h.
    """
    cfg = mdtypes.PVConfig(system_kwp=6.6, inverter_kw=5.0, loss_fraction=0.15)
    try:
        s = scenario._apply_pv(day_30min, cfg, interval_h=0.5)
    except NotImplementedError:
        pytest.xfail("_apply_pv not implemented")

    assert isinstance(s, pd.Series) and len(s) == len(day_30min)
    assert s.dtype.kind in "fc"
    assert (s >= -1e-12).all()
    assert s.max() <= cfg.inverter_kw * 0.5 + 1e-9


def test_battery_self_consume_contract():
    """Input:
    - import_prebat: baseline net import after PV-to-load (nonnegative).
    - pv_excess_prebat: PV leftover (candidate for charge/export).
    - BatteryConfig: capacity/max_kw/efficiency, with SoC bounds.
    Exercise:
    - Dispatch loop constraints and bounds.
    Expect:
    - discharge, charge, soc arrays of same length.
    - Non-negative values; per-interval charge/discharge ≤ max_kw × interval_h.
    - 0 ≤ soc ≤ capacity_kwh.
    """
    n = 48
    interval_h = 0.5
    import_prebat = np.full(n, 0.6)  # kWh per interval
    pv_excess_prebat = np.where(np.arange(n) % 6 == 0, 0.4, 0.0)  # some excess
    cfg = mdtypes.BatteryConfig(
        capacity_kwh=10.0, max_kw=5.0, round_trip_eff=0.9, soc_min=0.1, soc_max=0.95
    )

    try:
        discharge, charge, soc = scenario._apply_battery_self_consume(
            import_prebat, pv_excess_prebat, cfg, interval_h
        )
    except NotImplementedError:
        pytest.xfail("_apply_battery_self_consume not implemented")

    assert discharge.shape == charge.shape == soc.shape == (n,)
    assert (discharge >= -1e-12).all() and (charge >= -1e-12).all()
    limit = cfg.max_kw * interval_h + 1e-9
    assert (discharge <= limit).all() and (charge <= limit).all()
    assert (soc >= -1e-9).all() and (soc <= cfg.capacity_kwh + 1e-9).all()


def test_run_wires_components_and_prices(day_30min, monkeypatch):
    """Input:
    - df_before: import-only 0.5 kWh/slot via utils.build_canon_frame.
    - Monkeypatched scenario._apply_ev/pv/battery to deterministic outputs.
    - Plan provided; pricing.estimate_monthly_cost monkeypatched to stub.
    Exercise:
    - run() orchestration and cost calculation path.
    Expect:
    - result has df_before/df_after and cost frames; pricing gets called.
    """
    df_before = utils.build_canon_frame(
        day_30min,
        np.full(len(day_30min), 0.5),
        nmi="Q",
        channel="E1",
        flow="grid_import",
        cadence_min=30,
    )

    # Deterministic components
    ev_series = pd.Series(0.0, index=day_30min)
    ev_series.iloc[36:40] = 0.2
    pv_series = pd.Series(0.0, index=day_30min)
    pv_series.iloc[22:26] = 0.3

    def fake_ev(idx, cfg, interval_h):
        return ev_series

    def fake_pv(idx, cfg, interval_h):
        return pv_series

    def fake_batt(import_prebat, pv_excess_prebat, cfg, interval_h):
        n = len(import_prebat)
        dis = np.zeros(n)
        ch = np.zeros(n)
        soc = np.zeros(n)
        dis[30:32] = 0.1
        return dis, ch, soc

    monkeypatch.setattr(scenario, "_apply_ev", fake_ev, raising=True)
    monkeypatch.setattr(scenario, "_apply_pv", fake_pv, raising=True)
    monkeypatch.setattr(
        scenario, "_apply_battery_self_consume", fake_batt, raising=True
    )

    called = {"pricing": False}

    def fake_price(d, plan):
        called["pricing"] = True
        return pd.DataFrame({"month": ["2025-01"], "total": [123.45]})

    monkeypatch.setattr(
        scenario.pricing, "estimate_monthly_cost", fake_price, raising=True
    )

    plan = mdtypes.Plan(
        usage_bands=[], fixed_c_per_day=0.0, feed_in_c_per_kwh=0.0, demand=None
    )

    if not hasattr(scenario, "run"):
        pytest.skip("scenario.run not available")

    try:
        result = scenario.run(
            df_before,
            ev=mdtypes.EVConfig(),
            pv=mdtypes.PVConfig(system_kwp=1.0, inverter_kw=1.0),
            battery=mdtypes.BatteryConfig(capacity_kwh=1.0, max_kw=1.0),
            plan=plan,
        )
    except NotImplementedError:
        pytest.xfail("scenario.run not implemented")

    assert hasattr(result, "df_before") and hasattr(result, "df_after")
    assert hasattr(result, "cost_before") and hasattr(result, "cost_after")
    assert called["pricing"] is True
