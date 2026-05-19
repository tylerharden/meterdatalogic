"""Scenario tests for EV, PV, battery, and the run() orchestrator."""

import numpy as np
import pandas as pd
import pytest

from meterdatalogic import scenario, utils
import meterdatalogic.types as mdtypes


@pytest.fixture
def day_30min():
    """One local day at 30‑min cadence (Brisbane, no DST)."""
    return pd.date_range("2025-01-01", periods=48, freq="30min", tz="Australia/Brisbane")


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


def test_apply_ev_immediate_wraparound_window_starts_at_window_start():
    """Regression: EV with a wrap-around window (18:00–07:00) must charge from
    18:00, not from midnight.

    Before the fix, positions were iterated in calendar order within each day,
    so 00:00–06:30 slots were filled first and the chart showed a midnight spike.
    """
    # Two full days so each calendar day has both early-morning and evening slots.
    idx = pd.date_range("2025-01-13", periods=2 * 48, freq="30min", tz="Australia/Brisbane")
    cfg = mdtypes.EVConfig(
        daily_kwh=7.0,
        max_kw=7.0,
        window_start="18:00",
        window_end="07:00",
        days="ALL",
        strategy="immediate",
    )
    s = scenario._apply_ev(idx, cfg, interval_h=0.5)

    # Charging should only appear in the evening (18:00+), NOT at midnight.
    midnight_slots = s.between_time("00:00", "06:59")
    evening_slots = s.between_time("18:00", "23:59")

    assert midnight_slots.sum() < 1e-9, (
        f"EV charged {midnight_slots.sum():.3f} kWh at midnight — "
        "window ordering bug: should start charging from 18:00, not 00:00"
    )
    assert evening_slots.sum() > 0, "No EV charging found in evening window"
    # 7 kW charger, 7 kWh/day at 0.5h intervals → fills in exactly 2 slots
    assert abs(s.sum() - 2 * 7.0) < 1e-6, f"Expected 14 kWh total for 2 days, got {s.sum()}"


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
    monkeypatch.setattr(scenario, "_apply_battery_self_consume", fake_batt, raising=True)

    called = {"pricing": False}

    def fake_price(d, plan):
        called["pricing"] = True
        return pd.DataFrame({"month": ["2025-01"], "total": [123.45]})

    def fake_price_accept_kwargs(d, plan, **kwargs):
        return fake_price(d, plan)

    monkeypatch.setattr(scenario.pricing, "estimate_costs", fake_price_accept_kwargs, raising=True)

    plan = mdtypes.Plan(usage_bands=[], fixed_c_per_day=0.0, feed_in_c_per_kwh=0.0, demand=None)

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


# ---------------------------------------------------------------------------
# Regression: multi-flow df must not double scenario totals
# ---------------------------------------------------------------------------


@pytest.fixture
def multi_flow_df(day_30min):
    """Canonical df with both grid_import and grid_export_solar rows.

    Mirrors a real net-metered solar customer: import during non-solar hours,
    export during daylight only (never simultaneously positive at the same slot).
    The scenario engine must not duplicate values when building the after-series.
    """
    night_idx = pd.DatetimeIndex([ts for ts in day_30min if not (8 <= ts.hour < 16)])
    import_frame = utils.build_canon_frame(
        night_idx,
        np.full(len(night_idx), 0.5),
        nmi="Q123",
        channel="E1",
        flow="grid_import",
        cadence_min=30,
    )
    daylight_idx = pd.DatetimeIndex([ts for ts in day_30min if 8 <= ts.hour < 16])
    export_frame = utils.build_canon_frame(
        daylight_idx,
        np.full(len(daylight_idx), 0.1),
        nmi="Q123",
        channel="B1",
        flow="grid_export_solar",
        cadence_min=30,
    )
    return pd.concat([import_frame, export_frame]).sort_index()


def test_run_no_scenario_preserves_totals(multi_flow_df):
    """Regression: summary_before and summary_after totals must match the
    baseline when no EV/PV/battery is added.

    Before the idx_full fix, idx_full included duplicate timestamps (one per
    flow), causing every value to be replicated and totals to double.
    """
    result = scenario.run(multi_flow_df)

    before_import = result.summary_before["stats"]["total_import_kwh"]
    after_import = result.summary_after["stats"]["total_import_kwh"]

    before_export = result.summary_before["stats"]["solar_export_kwh"]
    after_export = result.summary_after["stats"]["solar_export_kwh"]

    # After = baseline (no additions); must not be doubled
    assert (
        abs(after_import - before_import) < 1e-6
    ), f"Import doubled: before={before_import}, after={after_import}"
    assert (
        abs(after_export - before_export) < 1e-6
    ), f"Export doubled: before={before_export}, after={after_export}"


def test_run_multiflow_import_total_is_not_doubled(multi_flow_df):
    """Regression: total_import_kwh in summary_before must reflect actual data,
    not a doubled value due to duplicate-index reindex.

    The fixture has 32 night intervals × 0.5 kWh = 16.0 kWh import.
    (16 daytime slots use export-only rows.)
    """
    result = scenario.run(multi_flow_df)
    expected_import = 32 * 0.5  # 16.0 kWh (night slots only)
    actual = result.summary_before["stats"]["total_import_kwh"]
    assert (
        abs(actual - expected_import) < 0.01
    ), f"Expected {expected_import} kWh import, got {actual} — possible doubling regression"


# ---------------------------------------------------------------------------
# Battery behavior: with PV, battery must reduce grid import
# ---------------------------------------------------------------------------


def test_battery_with_pv_reduces_import(day_30min):
    """A battery paired with PV should reduce grid import compared to PV alone.

    The battery absorbs daytime PV excess and discharges in the evening,
    reducing the net draw from the grid.
    """
    base = utils.build_canon_frame(
        day_30min,
        np.full(len(day_30min), 0.5),
        nmi="Q",
        channel="E1",
        flow="grid_import",
        cadence_min=30,
    )
    pv_cfg = mdtypes.PVConfig(system_kwp=6.6, inverter_kw=5.0, loss_fraction=0.15)
    bat_cfg = mdtypes.BatteryConfig(capacity_kwh=10.0, max_kw=5.0)

    result_pv_only = scenario.run(base, pv=pv_cfg)
    result_pv_bat = scenario.run(base, pv=pv_cfg, battery=bat_cfg)

    import_pv = result_pv_only.summary_after["stats"]["total_import_kwh"]
    import_pv_bat = result_pv_bat.summary_after["stats"]["total_import_kwh"]

    assert (
        import_pv_bat <= import_pv
    ), f"Battery+PV import ({import_pv_bat}) should be ≤ PV-only import ({import_pv})"


def test_battery_only_does_not_increase_import(day_30min):
    """Battery without PV has no source to charge from (MVP: PV-only charging).
    The after-import must equal the before-import — not increase.
    """
    base = utils.build_canon_frame(
        day_30min,
        np.full(len(day_30min), 0.5),
        nmi="Q",
        channel="E1",
        flow="grid_import",
        cadence_min=30,
    )
    bat_cfg = mdtypes.BatteryConfig(capacity_kwh=10.0, max_kw=5.0)

    result = scenario.run(base, battery=bat_cfg)

    before = result.summary_before["stats"]["total_import_kwh"]
    after = result.summary_after["stats"]["total_import_kwh"]

    assert after <= before + 1e-6, f"Battery-only raised import: before={before}, after={after}"


def test_battery_without_pv_is_strict_noop(day_30min):
    """Battery-only on an import-only baseline (no existing solar export) is a
    strict no-op: no export to charge from, so charge/discharge stay at zero
    and before/after totals match exactly.
    """
    base = utils.build_canon_frame(
        day_30min,
        np.full(len(day_30min), 0.5),
        nmi="Q",
        channel="E1",
        flow="grid_import",
        cadence_min=30,
    )
    bat_cfg = mdtypes.BatteryConfig(capacity_kwh=10.0, max_kw=5.0)

    result = scenario.run(base, battery=bat_cfg)

    before_import = result.summary_before["stats"]["total_import_kwh"]
    after_import = result.summary_after["stats"]["total_import_kwh"]
    before_export = result.summary_before["stats"].get("solar_export_kwh", 0.0)
    after_export = result.summary_after["stats"].get("solar_export_kwh", 0.0)

    assert abs(after_import - before_import) < 1e-6
    assert abs(after_export - before_export) < 1e-6
    assert abs(result.explain["battery_charge_kwh"]) < 1e-6
    assert abs(result.explain["battery_discharge_kwh"]) < 1e-6


def test_ev_mf_strategy_skips_weekends_and_hits_daily_target():
    """EV(MF) should charge only on weekdays and hit daily_kwh target each weekday."""
    idx = pd.date_range("2025-01-06", periods=7 * 48, freq="30min", tz="Australia/Brisbane")
    # Zero baseline to isolate EV contribution in after-series.
    base = utils.build_canon_frame(
        idx,
        np.zeros(len(idx)),
        nmi="Q",
        channel="E1",
        flow="grid_import",
        cadence_min=30,
    )
    ev_cfg = mdtypes.EVConfig(
        daily_kwh=8.0,
        max_kw=7.0,
        window_start="18:00",
        window_end="22:00",
        days="MF",
        strategy="immediate",
    )

    result = scenario.run(base, ev=ev_cfg)

    # Exactly 5 weekdays in the selected week.
    assert abs(result.explain["ev_kwh"] - (5 * ev_cfg.daily_kwh)) < 1e-6

    df_after = result.df_after
    weekend = pd.Series(df_after.index.dayofweek >= 5, index=df_after.index)
    weekend_kwh = float(df_after.loc[weekend, "kwh"].sum()) if len(df_after) else 0.0
    assert weekend_kwh < 1e-9


def test_run_energy_balance_invariant_with_ev_pv_battery(day_30min):
    """End-to-end conservation check for scenario.run.

    For one intervalized horizon:
      import_reduction = (baseline_import + ev - after_import)
      pv_effective_on_import = pv + battery_discharge - battery_charge - export_delta
    These two should match within numerical tolerance.
    """
    base = utils.build_canon_frame(
        day_30min,
        np.full(len(day_30min), 0.8),
        nmi="Q",
        channel="E1",
        flow="grid_import",
        cadence_min=30,
    )
    ev_cfg = mdtypes.EVConfig(
        daily_kwh=6.0,
        max_kw=7.0,
        window_start="18:00",
        window_end="22:00",
        days="ALL",
        strategy="scheduled",
    )
    pv_cfg = mdtypes.PVConfig(system_kwp=6.6, inverter_kw=5.0, loss_fraction=0.15)
    bat_cfg = mdtypes.BatteryConfig(capacity_kwh=10.0, max_kw=5.0, round_trip_eff=0.9)

    result = scenario.run(base, ev=ev_cfg, pv=pv_cfg, battery=bat_cfg)

    before_import = float(result.summary_before["stats"]["total_import_kwh"])
    after_import = float(result.summary_after["stats"]["total_import_kwh"])
    before_export = float(result.summary_before["stats"].get("solar_export_kwh", 0.0))
    after_export = float(result.summary_after["stats"].get("solar_export_kwh", 0.0))

    ev_kwh = float(result.explain["ev_kwh"])
    pv_kwh = float(result.explain["pv_kwh"])
    bat_dis = float(result.explain["battery_discharge_kwh"])
    bat_ch = float(result.explain["battery_charge_kwh"])
    export_delta = after_export - before_export

    import_reduction = before_import + ev_kwh - after_import
    pv_effective_on_import = pv_kwh + bat_dis - bat_ch - export_delta

    assert abs(import_reduction - pv_effective_on_import) < 1e-6, (
        "Scenario energy-balance invariant failed: "
        f"import_reduction={import_reduction}, pv_effective_on_import={pv_effective_on_import}"
    )


def test_run_delta_matches_before_after_summaries(day_30min):
    """`result.delta` should be consistent with summary before/after totals."""
    base = utils.build_canon_frame(
        day_30min,
        np.full(len(day_30min), 0.6),
        nmi="Q",
        channel="E1",
        flow="grid_import",
        cadence_min=30,
    )
    result = scenario.run(
        base,
        ev=mdtypes.EVConfig(daily_kwh=4.0, max_kw=7.0),
        pv=mdtypes.PVConfig(system_kwp=5.0, inverter_kw=4.0),
        battery=mdtypes.BatteryConfig(capacity_kwh=8.0, max_kw=4.0),
    )

    before_import = float(result.summary_before["stats"]["total_import_kwh"])
    after_import = float(result.summary_after["stats"]["total_import_kwh"])
    before_export = float(result.summary_before["stats"].get("solar_export_kwh", 0.0))
    after_export = float(result.summary_after["stats"].get("solar_export_kwh", 0.0))

    assert abs(result.delta["import_kwh_delta"] - (after_import - before_import)) < 1e-9
    assert abs(result.delta["export_kwh_delta"] - (after_export - before_export)) < 1e-9


def test_profile24_daytime_not_inflated_by_ev_only(day_30min):
    """Regression: EV-only scenario (night charging) must not raise daytime profile24.

    Adding EV with window 18:00–22:00 should leave daytime slots (08:00–16:00)
    unchanged in profile24, because EV never charges during the day. Before the
    fix, zero-import intervals were dropped from df_after causing the mean for
    solar-era daytime slots to be computed over fewer (all-positive) samples,
    biasing the daytime average upward.
    """

    # Build two days where slots 12:00–14:00 have zero import (mimicking full
    # solar offset). Other daytime slots have modest import.
    idx = pd.date_range("2025-01-13", periods=2 * 48, freq="30min", tz="Australia/Brisbane")
    kwh_vals = np.full(len(idx), 0.3)
    # Zero out 12:00–13:30 slots (8 slots per day) to simulate solar coverage.
    for i, ts in enumerate(idx):
        if ts.hour in (12, 13):
            kwh_vals[i] = 0.0

    # Build a minimal canonical frame from ingest (not raw build_canon_frame)
    # so it matches what real data looks like.
    raw = pd.DataFrame(
        {
            "t_start": idx,
            "nmi": "Q",
            "channel": "E1",
            "flow": "grid_import",
            "kwh": kwh_vals,
            "cadence_min": 30,
        }
    ).set_index("t_start")

    result = scenario.run(
        raw,
        ev=mdtypes.EVConfig(
            daily_kwh=7.0,
            max_kw=7.0,
            window_start="18:00",
            window_end="22:00",
            days="ALL",
            strategy="immediate",
        ),
    )

    # Extract profile24 slot values for 12:00 from before and after.
    before_prof = {r["slot"]: r for r in result.summary_before["datasets"]["profile24"]}
    after_prof = {r["slot"]: r for r in result.summary_after["datasets"]["profile24"]}

    for slot in ("12:00", "12:30", "13:00", "13:30"):
        before_val = float(before_prof.get(slot, {}).get("import_total", 0.0))
        after_val = float(after_prof.get(slot, {}).get("import_total", 0.0))
        assert abs(after_val - before_val) < 1e-9, (
            f"Slot {slot} profile24 changed after EV-only scenario: "
            f"before={before_val:.4f}, after={after_val:.4f}. "
            "Daytime import must not change when EV charges at night."
        )


def _series_from_after(df_after, idx, flow_name):
    """Rebuild a dense per-interval series for a flow from sparse canonical rows."""
    if len(df_after) == 0:
        return np.zeros(len(idx), dtype=float)
    flow_mask = df_after["flow"] == flow_name
    if not flow_mask.any():
        return np.zeros(len(idx), dtype=float)
    return (
        df_after.loc[flow_mask]
        .groupby(level=0)["kwh"]
        .sum()
        .reindex(idx, fill_value=0.0)
        .to_numpy(dtype=float)
    )


def test_run_ev_only_trace_matches_expected_import_curve(day_30min):
    """Golden trace: EV-only run should equal baseline + EV profile at each slot."""
    baseline = np.linspace(0.2, 0.8, len(day_30min), dtype=float)
    base = utils.build_canon_frame(
        day_30min,
        baseline,
        nmi="Q",
        channel="E1",
        flow="grid_import",
        cadence_min=30,
    )
    ev_cfg = mdtypes.EVConfig(
        daily_kwh=2.0,
        max_kw=2.0,  # per-interval cap = 1.0 kWh
        window_start="18:00",
        window_end="20:00",
        days="ALL",
        strategy="immediate",
    )

    result = scenario.run(base, ev=ev_cfg)
    expected_ev = scenario._apply_ev(day_30min, ev_cfg, interval_h=0.5).to_numpy(dtype=float)
    expected_import = baseline + expected_ev

    actual_import = _series_from_after(result.df_after, day_30min, "grid_import")
    actual_export = _series_from_after(result.df_after, day_30min, "grid_export_solar")

    np.testing.assert_allclose(actual_import, expected_import, rtol=0, atol=1e-9)
    np.testing.assert_allclose(actual_export, np.zeros(len(day_30min)), rtol=0, atol=1e-9)


def test_run_pv_only_trace_matches_expected_split(day_30min):
    """Golden trace: PV-only run should split into import=max(load-pv,0), export=max(pv-load,0)."""
    baseline = np.full(len(day_30min), 0.35, dtype=float)
    base = utils.build_canon_frame(
        day_30min,
        baseline,
        nmi="Q",
        channel="E1",
        flow="grid_import",
        cadence_min=30,
    )
    pv_cfg = mdtypes.PVConfig(system_kwp=6.6, inverter_kw=5.0, loss_fraction=0.15)

    result = scenario.run(base, pv=pv_cfg)
    expected_pv = scenario._apply_pv(day_30min, pv_cfg, interval_h=0.5).to_numpy(dtype=float)
    expected_import = np.maximum(baseline - expected_pv, 0.0)
    expected_export = np.maximum(expected_pv - baseline, 0.0)

    actual_import = _series_from_after(result.df_after, day_30min, "grid_import")
    actual_export = _series_from_after(result.df_after, day_30min, "grid_export_solar")

    np.testing.assert_allclose(actual_import, expected_import, rtol=0, atol=1e-9)
    np.testing.assert_allclose(actual_export, expected_export, rtol=0, atol=1e-9)


def test_run_pv_battery_trace_matches_dispatch(day_30min):
    """Golden trace: PV+battery run should match dispatch math at each interval."""
    baseline = np.full(len(day_30min), 0.5, dtype=float)
    base = utils.build_canon_frame(
        day_30min,
        baseline,
        nmi="Q",
        channel="E1",
        flow="grid_import",
        cadence_min=30,
    )
    pv_cfg = mdtypes.PVConfig(system_kwp=6.6, inverter_kw=5.0, loss_fraction=0.15)
    bat_cfg = mdtypes.BatteryConfig(capacity_kwh=10.0, max_kw=5.0, round_trip_eff=0.9)

    result = scenario.run(base, pv=pv_cfg, battery=bat_cfg)

    pv_arr = scenario._apply_pv(day_30min, pv_cfg, interval_h=0.5).to_numpy(dtype=float)
    used_by_load = np.minimum(pv_arr, baseline)
    expected_import = baseline - used_by_load
    expected_leftover = pv_arr - used_by_load
    _dis, _ch, _soc = scenario._apply_battery_self_consume(
        expected_import,
        expected_leftover,
        bat_cfg,
        0.5,
    )
    expected_export = expected_leftover

    actual_import = _series_from_after(result.df_after, day_30min, "grid_import")
    actual_export = _series_from_after(result.df_after, day_30min, "grid_export_solar")

    np.testing.assert_allclose(actual_import, expected_import, rtol=0, atol=1e-9)
    np.testing.assert_allclose(actual_export, expected_export, rtol=0, atol=1e-9)


# ---------------------------------------------------------------------------
# PV-only (stacked) scenario: customer already has solar export
# ---------------------------------------------------------------------------


@pytest.fixture
def solar_customer_df(day_30min):
    """Canonical df for a net-metered solar customer (stacked case).

    Mirrors a typical QB-style NEM12 dataset: either importing or exporting
    at each interval, never both simultaneously.
    - Night (outside 08:00–16:00): import=0.5 kWh, no export row.
    - Daytime (08:00–15:30): no import row, export=0.4 kWh (solar > load).
    """
    # Night: import only
    night_idx = pd.DatetimeIndex([ts for ts in day_30min if not (8 <= ts.hour < 16)])
    imp = utils.build_canon_frame(
        night_idx,
        np.full(len(night_idx), 0.5),
        nmi="Q",
        channel="E1",
        flow="grid_import",
        cadence_min=30,
    )
    # Daytime: export only (solar fully covers load, exporting surplus)
    daylight_idx = pd.DatetimeIndex([ts for ts in day_30min if 8 <= ts.hour < 16])
    exp = utils.build_canon_frame(
        daylight_idx,
        np.full(len(daylight_idx), 0.4),
        nmi="Q",
        channel="B1",
        flow="grid_export_solar",
        cadence_min=30,
    )
    return pd.concat([imp, exp]).sort_index()


def test_battery_only_with_existing_solar_reduces_import_and_export(solar_customer_df):
    """Battery-only scenario on a customer who already has solar export.

    The battery should charge from existing solar export during the day and
    discharge to reduce evening/night import. Both import and export must
    decrease compared to the baseline.
    """
    bat_cfg = mdtypes.BatteryConfig(capacity_kwh=10.0, max_kw=5.0, round_trip_eff=0.9)
    result = scenario.run(solar_customer_df, battery=bat_cfg)

    assert (
        result.delta["import_kwh_delta"] < 0
    ), "Battery should reduce import by discharging against evening load"
    assert (
        result.delta["export_kwh_delta"] < 0
    ), "Battery should reduce export by absorbing solar that would have been sent to grid"
    assert result.explain["battery_charge_kwh"] > 0, "Battery must have charged from existing solar"
    assert (
        result.explain["battery_discharge_kwh"] > 0
    ), "Battery must have discharged to reduce import"


def test_pv_stacked_increases_export_and_decreases_import(solar_customer_df):
    """Adding PV to a dataset that already has solar export (stacked mode):
    - import should decrease (PV offsets some load)
    - export should increase (excess PV added to existing export)
    """
    pv_cfg = mdtypes.PVConfig(system_kwp=6.6, inverter_kw=5.0, loss_fraction=0.15)
    result = scenario.run(solar_customer_df, pv=pv_cfg)

    assert result.delta["import_kwh_delta"] < 0, "PV must reduce grid import"
    assert result.delta["export_kwh_delta"] > 0, "Stacked PV must increase solar export"


def test_pv_stacked_export_equals_original_plus_new_excess(solar_customer_df, day_30min):
    """Total after-export equals original export + PV excess not consumed by load."""
    pv_cfg = mdtypes.PVConfig(system_kwp=6.6, inverter_kw=5.0, loss_fraction=0.15)
    result = scenario.run(solar_customer_df, pv=pv_cfg)

    pv_arr = scenario._apply_pv(day_30min, pv_cfg, interval_h=0.5).to_numpy(dtype=float)

    orig_import = (
        solar_customer_df[solar_customer_df["flow"] == "grid_import"]
        .groupby(level=0)["kwh"]
        .sum()
        .reindex(day_30min, fill_value=0.0)
        .to_numpy()
    )
    orig_export = (
        solar_customer_df[solar_customer_df["flow"] == "grid_export_solar"]
        .groupby(level=0)["kwh"]
        .sum()
        .reindex(day_30min, fill_value=0.0)
        .to_numpy()
    )

    # Net-meter formulation: PV offsets net load (import - export), not just import.
    net_before = orig_import - orig_export
    net_after = net_before - pv_arr  # no EV
    expected_after_export = np.maximum(-net_after, 0.0)

    actual_after_export = _series_from_after(result.df_after, day_30min, "grid_export_solar")
    np.testing.assert_allclose(actual_after_export, expected_after_export, rtol=0, atol=1e-9)


def test_pv_self_consumption_pct_is_accurate(day_30min):
    """explain.pv_self_consumption_pct = (PV used by load / total PV) × 100."""
    base = utils.build_canon_frame(
        day_30min,
        np.full(len(day_30min), 0.3),
        nmi="Q",
        channel="E1",
        flow="grid_import",
        cadence_min=30,
    )
    pv_cfg = mdtypes.PVConfig(system_kwp=6.6, inverter_kw=5.0, loss_fraction=0.15)
    result = scenario.run(base, pv=pv_cfg)

    pv_arr = scenario._apply_pv(day_30min, pv_cfg, interval_h=0.5).to_numpy(dtype=float)
    baseline = np.full(len(day_30min), 0.3)
    used_by_load = np.minimum(pv_arr, baseline)
    pv_total = pv_arr.sum()
    expected_pct = float(used_by_load.sum() / pv_total * 100.0) if pv_total > 0 else 0.0

    actual_pct = result.explain.get("pv_self_consumption_pct")
    assert actual_pct is not None
    assert (
        abs(actual_pct - expected_pct) < 1e-6
    ), f"pv_self_consumption_pct={actual_pct:.4f}%, expected={expected_pct:.4f}%"


def test_pv_does_not_change_evening_peak_demand(day_30min):
    """PV generation stops before peak-demand window (19:00+), so adding PV
    must not affect the peak demand figure reported in the summary.
    """
    kwh_vals = np.full(len(day_30min), 0.3)
    for i, ts in enumerate(day_30min):
        if ts.hour == 19:
            kwh_vals[i] = 2.0  # 4.0 kW evening peak

    base = utils.build_canon_frame(
        day_30min, kwh_vals, nmi="Q", channel="E1", flow="grid_import", cadence_min=30
    )
    pv_cfg = mdtypes.PVConfig(system_kwp=6.6, inverter_kw=5.0, loss_fraction=0.15)
    result = scenario.run(base, pv=pv_cfg)

    before_peak = result.summary_before["stats"]["peak_consumption_kw"]
    after_peak = result.summary_after["stats"]["peak_consumption_kw"]

    assert abs(after_peak - before_peak) < 1e-6, (
        f"Evening peak changed after PV: before={before_peak:.4f}, after={after_peak:.4f}. "
        "PV is zero at 19:00 so peak demand must be unchanged."
    )


# ---------------------------------------------------------------------------
# Net-meter formulation: EV + solar customer correctness
# ---------------------------------------------------------------------------


def test_ev_on_solar_customer_no_simultaneous_import_and_export(solar_customer_df, day_30min):
    """Regression: adding EV to a solar customer must not produce simultaneous
    import AND export at the same interval.

    The naive `s_import0 + ev` formulation ignores that existing solar export
    can absorb EV demand. The net-meter formulation (`net_before + ev - pv`)
    routes EV load through available solar surplus first.
    """
    ev_cfg = mdtypes.EVConfig(
        daily_kwh=4.0,
        max_kw=5.0,
        window_start="09:00",  # daytime to overlap with solar export in the fixture
        window_end="14:00",
        days="ALL",
        strategy="scheduled",
    )
    result = scenario.run(solar_customer_df, ev=ev_cfg)

    after_import = _series_from_after(result.df_after, day_30min, "grid_import")
    after_export = _series_from_after(result.df_after, day_30min, "grid_export_solar")

    # At every interval, at most one of import or export may be positive.
    both_positive = (after_import > 1e-9) & (after_export > 1e-9)
    assert not both_positive.any(), (
        f"Simultaneous import and export found at {both_positive.sum()} interval(s). "
        "EV demand during solar hours should reduce export, not add import alongside it."
    )


def test_ev_on_solar_customer_reduces_export_before_adding_import(solar_customer_df, day_30min):
    """When EV is added during solar hours, existing export should be consumed
    first. Only intervals where EV demand exceeds the available export surplus
    should switch to importing from the grid.

    Fixture solar export is 0.2 kWh/interval (0.4 kW). EV scheduled at 0.25 kWh
    per slot (0.5 kW). In the solar window, EV > export → some import is expected,
    but export should drop to ~0 (fully consumed) rather than staying at 0.2.
    """
    ev_cfg = mdtypes.EVConfig(
        daily_kwh=4.0,
        max_kw=5.0,
        window_start="08:00",
        window_end="16:00",
        days="ALL",
        strategy="scheduled",
    )
    baseline_export = (
        solar_customer_df[solar_customer_df["flow"] == "grid_export_solar"]
        .groupby(level=0)["kwh"]
        .sum()
        .reindex(day_30min, fill_value=0.0)
        .to_numpy()
    )
    result = scenario.run(solar_customer_df, ev=ev_cfg)

    after_export = _series_from_after(result.df_after, day_30min, "grid_export_solar")

    # Solar window export must be ≤ baseline (EV must have consumed some of it)
    assert after_export.sum() < baseline_export.sum(), (
        "EV during solar hours should reduce total export "
        f"(before={baseline_export.sum():.3f}, after={after_export.sum():.3f})"
    )


def test_ev_pv_battery_combo_on_solar_customer_energy_balance(solar_customer_df, day_30min):
    """Full combo (EV + PV + battery) on an existing-solar customer.

    Verifies the energy-balance invariant holds for the net-meter formulation:
      import_reduction = used_by_load + battery_discharge
      (where import_reduction accounts for EV load added)
    """
    ev_cfg = mdtypes.EVConfig(
        daily_kwh=6.0,
        max_kw=7.0,
        window_start="18:00",
        window_end="22:00",
        days="ALL",
        strategy="scheduled",
    )
    pv_cfg = mdtypes.PVConfig(system_kwp=6.6, inverter_kw=5.0, loss_fraction=0.15)
    bat_cfg = mdtypes.BatteryConfig(capacity_kwh=10.0, max_kw=5.0, round_trip_eff=0.9)

    result = scenario.run(solar_customer_df, ev=ev_cfg, pv=pv_cfg, battery=bat_cfg)

    before_import = float(result.summary_before["stats"]["total_import_kwh"])
    after_import = float(result.summary_after["stats"]["total_import_kwh"])
    before_export = float(result.summary_before["stats"].get("solar_export_kwh", 0.0))
    after_export = float(result.summary_after["stats"].get("solar_export_kwh", 0.0))

    ev_kwh = float(result.explain["ev_kwh"])
    pv_kwh = float(result.explain["pv_kwh"])
    bat_dis = float(result.explain["battery_discharge_kwh"])
    bat_ch = float(result.explain["battery_charge_kwh"])
    export_delta = after_export - before_export

    # import_reduction: how much the scenario reduced net grid draw (EV adds, everything else reduces)
    import_reduction = before_import + ev_kwh - after_import
    pv_effective_on_import = pv_kwh + bat_dis - bat_ch - export_delta

    assert abs(import_reduction - pv_effective_on_import) < 1e-6, (
        f"Energy-balance invariant failed on solar customer: "
        f"import_reduction={import_reduction:.6f}, "
        f"pv_effective_on_import={pv_effective_on_import:.6f}"
    )


def test_ev_pv_battery_combo_golden_trace(day_30min):
    """Golden-trace test for full EV+PV+battery combo on an import-only baseline.

    Verifies per-interval import/export arrays match the manually computed dispatch.
    This ensures the combo path (ev → pv → battery) is wired in the correct order.
    """
    baseline = np.full(len(day_30min), 0.6, dtype=float)
    base = utils.build_canon_frame(
        day_30min,
        baseline,
        nmi="Q",
        channel="E1",
        flow="grid_import",
        cadence_min=30,
    )
    ev_cfg = mdtypes.EVConfig(
        daily_kwh=4.0,
        max_kw=4.0,
        window_start="19:00",
        window_end="21:00",
        days="ALL",
        strategy="immediate",
    )
    pv_cfg = mdtypes.PVConfig(system_kwp=5.0, inverter_kw=4.0, loss_fraction=0.15)
    bat_cfg = mdtypes.BatteryConfig(capacity_kwh=8.0, max_kw=4.0, round_trip_eff=0.9)

    result = scenario.run(base, ev=ev_cfg, pv=pv_cfg, battery=bat_cfg)

    # Manually reproduce the dispatch pipeline (import-only → s_export0=0)
    ev_arr = scenario._apply_ev(day_30min, ev_cfg, interval_h=0.5).to_numpy(dtype=float)
    pv_arr = scenario._apply_pv(day_30min, pv_cfg, interval_h=0.5).to_numpy(dtype=float)

    net_after = baseline + ev_arr - pv_arr  # net_before = baseline (no existing export)
    expected_import = np.maximum(net_after, 0.0)
    expected_excess = np.maximum(-net_after, 0.0)

    # Pass arrays directly — _apply_battery_self_consume mutates them in-place.
    _dis, _ch, _soc = scenario._apply_battery_self_consume(
        expected_import,  # mutated by battery discharge
        expected_excess,  # mutated by battery charge
        bat_cfg,
        0.5,
    )
    expected_import_final = expected_import  # post-battery (mutated)
    expected_export_final = expected_excess  # post-battery (mutated)

    actual_import = _series_from_after(result.df_after, day_30min, "grid_import")
    actual_export = _series_from_after(result.df_after, day_30min, "grid_export_solar")

    np.testing.assert_allclose(actual_import, expected_import_final, rtol=0, atol=1e-9)
    np.testing.assert_allclose(actual_export, expected_export_final, rtol=0, atol=1e-9)
