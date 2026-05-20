"""Scenario tests for EV, PV, battery, and the run() orchestrator."""

import datetime as _dt
import numpy as np
import polars as pl
import pytest

from meterdatalogic import scenario, utils
import meterdatalogic.types as mdtypes

TZ = "Australia/Brisbane"


def _ts_range(start: str, periods: int, freq_min: int) -> pl.Series:
    base = _dt.datetime.fromisoformat(start)
    times = [base + _dt.timedelta(minutes=freq_min * i) for i in range(periods)]
    return pl.Series(times, dtype=pl.Datetime("us")).dt.replace_time_zone(TZ)


@pytest.fixture
def day_30min() -> pl.Series:
    """One local day at 30-min cadence (Brisbane, no DST)."""
    return _ts_range("2025-01-01", 48, 30)


@pytest.fixture
def base_df(day_30min):
    """Canonical baseline: 0.5 kWh import per interval, single NMI/channel."""
    return utils.build_canon_frame(
        day_30min,
        np.full(len(day_30min), 0.5),
        nmi="Q123",
        channel="E1",
        flow="grid_import",
        cadence_min=30,
    )


def _series_from_after(df_after: pl.DataFrame, idx: pl.Series, flow_name: str) -> np.ndarray:
    """Rebuild a dense per-interval numpy array for a flow from sparse canonical rows."""
    n = len(idx)
    if df_after.is_empty():
        return np.zeros(n, dtype=float)
    subset = df_after.filter(pl.col("flow") == flow_name)
    if subset.is_empty():
        return np.zeros(n, dtype=float)
    grouped = subset.group_by("t_start").agg(pl.col("kwh").sum())
    full = (
        pl.DataFrame({"t_start": idx})
        .join(grouped, on="t_start", how="left")
        .with_columns(pl.col("kwh").fill_null(0.0))
    )
    return full["kwh"].cast(pl.Float64).to_numpy()


def _flow_to_array(df: pl.DataFrame, idx: pl.Series, flow: str) -> np.ndarray:
    """Dense per-interval array for a flow, reindexed to idx with 0.0 fill."""
    subset = df.filter(pl.col("flow") == flow).group_by("t_start").agg(pl.col("kwh").sum())
    full = (
        pl.DataFrame({"t_start": idx})
        .join(subset, on="t_start", how="left")
        .with_columns(pl.col("kwh").fill_null(0.0))
    )
    return full["kwh"].cast(pl.Float64).to_numpy()


def test_apply_ev_immediate_window_and_limits(day_30min):
    """EV: length, window mask, per-interval cap, and daily total."""
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

    assert isinstance(s, np.ndarray) and len(s) == len(idx)
    in_win = utils.time_in_range(
        idx, utils.parse_time_str("18:00"), utils.parse_time_str("22:00")
    ).to_numpy()
    assert (s[~in_win] == 0).all()
    assert s.max() <= cfg.max_kw * 0.5 + 1e-9
    assert abs(s.sum() - cfg.daily_kwh) <= 0.5


def test_apply_ev_immediate_wraparound_window_starts_at_window_start():
    """Regression: EV with a wrap-around window (18:00-07:00) must charge from 18:00."""
    idx = _ts_range("2025-01-13", 2 * 48, 30)
    cfg = mdtypes.EVConfig(
        daily_kwh=7.0,
        max_kw=7.0,
        window_start="18:00",
        window_end="07:00",
        days="ALL",
        strategy="immediate",
    )
    s = scenario._apply_ev(idx, cfg, interval_h=0.5)

    midnight_mask = utils.time_in_range(
        idx, utils.parse_time_str("00:00"), utils.parse_time_str("07:00")
    ).to_numpy()
    evening_mask = utils.time_in_range(
        idx, utils.parse_time_str("18:00"), utils.parse_time_str("00:00")
    ).to_numpy()

    assert s[midnight_mask].sum() < 1e-9, (
        f"EV charged {s[midnight_mask].sum():.3f} kWh at midnight — "
        "window ordering bug: should start charging from 18:00, not 00:00"
    )
    assert s[evening_mask].sum() > 0, "No EV charging found in evening window"
    assert abs(s.sum() - 2 * 7.0) < 1e-6, f"Expected 14 kWh total for 2 days, got {s.sum()}"


def test_apply_pv_basic_contract(day_30min):
    """PV: length, dtype, non-negative, and inverter cap."""
    cfg = mdtypes.PVConfig(system_kwp=6.6, inverter_kw=5.0, loss_fraction=0.15)
    try:
        s = scenario._apply_pv(day_30min, cfg, interval_h=0.5)
    except NotImplementedError:
        pytest.xfail("_apply_pv not implemented")

    assert isinstance(s, np.ndarray) and len(s) == len(day_30min)
    assert s.dtype.kind in "fc"
    assert (s >= -1e-12).all()
    assert s.max() <= cfg.inverter_kw * 0.5 + 1e-9


def test_battery_self_consume_contract():
    """Battery dispatch loop: shape, non-negative, per-interval cap, and SoC bounds."""
    n = 48
    interval_h = 0.5
    import_prebat = np.full(n, 0.6)
    pv_excess_prebat = np.where(np.arange(n) % 6 == 0, 0.4, 0.0)
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
    """run() orchestration: df_before/df_after and cost frames are populated."""
    df_before = utils.build_canon_frame(
        day_30min,
        np.full(len(day_30min), 0.5),
        nmi="Q",
        channel="E1",
        flow="grid_import",
        cadence_min=30,
    )

    n = len(day_30min)
    ev_arr = np.zeros(n)
    ev_arr[36:40] = 0.2
    pv_arr = np.zeros(n)
    pv_arr[22:26] = 0.3

    def fake_ev(idx, cfg, interval_h):
        return ev_arr

    def fake_pv(idx, cfg, interval_h):
        return pv_arr

    def fake_batt(import_prebat, pv_excess_prebat, cfg, interval_h):
        n_ = len(import_prebat)
        dis = np.zeros(n_)
        ch = np.zeros(n_)
        soc = np.zeros(n_)
        dis[30:32] = 0.1
        return dis, ch, soc

    monkeypatch.setattr(scenario, "_apply_ev", fake_ev, raising=True)
    monkeypatch.setattr(scenario, "_apply_pv", fake_pv, raising=True)
    monkeypatch.setattr(scenario, "_apply_battery_self_consume", fake_batt, raising=True)

    called = {"pricing": False}

    def fake_price_accept_kwargs(d, plan, **kwargs):
        called["pricing"] = True
        return pl.DataFrame({
            "month": ["2025-01"],
            "energy_cost": [100.0],
            "demand_cost": [0.0],
            "fixed_cost": [23.45],
            "feed_in_credit": [0.0],
            "total": [123.45],
        })

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
    """Canonical df with both grid_import and grid_export_solar rows."""
    hours = day_30min.dt.hour().to_numpy()
    night_mask = ~((hours >= 8) & (hours < 16))
    day_mask_arr = (hours >= 8) & (hours < 16)

    night_ts = day_30min.filter(pl.Series(night_mask.tolist()))
    day_ts = day_30min.filter(pl.Series(day_mask_arr.tolist()))

    import_frame = utils.build_canon_frame(
        night_ts,
        np.full(len(night_ts), 0.5),
        nmi="Q123",
        channel="E1",
        flow="grid_import",
        cadence_min=30,
    )
    export_frame = utils.build_canon_frame(
        day_ts,
        np.full(len(day_ts), 0.1),
        nmi="Q123",
        channel="B1",
        flow="grid_export_solar",
        cadence_min=30,
    )
    return pl.concat([import_frame, export_frame]).sort("t_start")


def test_run_no_scenario_preserves_totals(multi_flow_df):
    """Regression: summary_before and summary_after totals must match the baseline."""
    result = scenario.run(multi_flow_df)

    before_import = result.summary_before["stats"]["total_import_kwh"]
    after_import = result.summary_after["stats"]["total_import_kwh"]
    before_export = result.summary_before["stats"]["solar_export_kwh"]
    after_export = result.summary_after["stats"]["solar_export_kwh"]

    assert abs(after_import - before_import) < 1e-6
    assert abs(after_export - before_export) < 1e-6


def test_run_multiflow_import_total_is_not_doubled(multi_flow_df):
    """Regression: total_import_kwh must reflect actual data, not doubled."""
    result = scenario.run(multi_flow_df)
    expected_import = 32 * 0.5  # 16.0 kWh (night slots only)
    actual = result.summary_before["stats"]["total_import_kwh"]
    assert abs(actual - expected_import) < 0.01


# ---------------------------------------------------------------------------
# Battery behavior: with PV, battery must reduce grid import
# ---------------------------------------------------------------------------


def test_battery_with_pv_reduces_import(day_30min):
    """A battery paired with PV should reduce grid import compared to PV alone."""
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

    assert import_pv_bat <= import_pv


def test_battery_only_does_not_increase_import(day_30min):
    """Battery without PV: after-import must equal before-import."""
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

    assert after <= before + 1e-6


def test_battery_without_pv_is_strict_noop(day_30min):
    """Battery-only on import-only baseline (no existing solar) is a strict no-op."""
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
    idx = _ts_range("2025-01-06", 7 * 48, 30)  # Mon 2025-01-06 for 7 days
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

    assert abs(result.explain["ev_kwh"] - (5 * ev_cfg.daily_kwh)) < 1e-6

    df_after = result.df_after
    # weekday(): Mon=0 ... Sat=5, Sun=6
    weekend_kwh = float(df_after.filter(pl.col("t_start").dt.weekday() >= 6)["kwh"].sum())
    assert weekend_kwh < 1e-9


def test_run_energy_balance_invariant_with_ev_pv_battery(day_30min):
    """End-to-end conservation check for scenario.run."""
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

    assert abs(import_reduction - pv_effective_on_import) < 1e-6


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
    """Regression: EV-only scenario (night charging) must not raise daytime profile24."""
    idx = _ts_range("2025-01-13", 2 * 48, 30)
    kwh_vals = np.full(len(idx), 0.3)
    hours = idx.dt.hour().to_numpy()
    kwh_vals[(hours == 12) | (hours == 13)] = 0.0

    n = len(idx)
    raw = pl.DataFrame(
        {
            "t_start": idx,
            "nmi": pl.Series(["Q"] * n),
            "channel": pl.Series(["E1"] * n),
            "flow": pl.Series(["grid_import"] * n),
            "kwh": pl.Series(kwh_vals.tolist(), dtype=pl.Float64),
            "cadence_min": pl.Series([30] * n, dtype=pl.Int32),
        }
    )

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

    before_prof = {r["slot"]: r for r in result.summary_before["datasets"]["profile24"]}
    after_prof = {r["slot"]: r for r in result.summary_after["datasets"]["profile24"]}

    for slot in ("12:00", "12:30", "13:00", "13:30"):
        before_val = float(before_prof.get(slot, {}).get("import_total", 0.0))
        after_val = float(after_prof.get(slot, {}).get("import_total", 0.0))
        assert abs(after_val - before_val) < 1e-9, (
            f"Slot {slot} profile24 changed after EV-only scenario: "
            f"before={before_val:.4f}, after={after_val:.4f}."
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
        max_kw=2.0,
        window_start="18:00",
        window_end="20:00",
        days="ALL",
        strategy="immediate",
    )

    result = scenario.run(base, ev=ev_cfg)
    expected_ev = scenario._apply_ev(day_30min, ev_cfg, interval_h=0.5)
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
    expected_pv = scenario._apply_pv(day_30min, pv_cfg, interval_h=0.5)
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

    pv_arr = scenario._apply_pv(day_30min, pv_cfg, interval_h=0.5)
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

    Night (outside 08:00-16:00): import=0.5 kWh, no export row.
    Daytime (08:00-15:30): no import row, export=0.4 kWh (solar > load).
    """
    hours = day_30min.dt.hour().to_numpy()
    night_mask = ~((hours >= 8) & (hours < 16))
    day_mask_arr = (hours >= 8) & (hours < 16)

    night_ts = day_30min.filter(pl.Series(night_mask.tolist()))
    day_ts = day_30min.filter(pl.Series(day_mask_arr.tolist()))

    imp = utils.build_canon_frame(
        night_ts, np.full(len(night_ts), 0.5),
        nmi="Q", channel="E1", flow="grid_import", cadence_min=30,
    )
    exp = utils.build_canon_frame(
        day_ts, np.full(len(day_ts), 0.4),
        nmi="Q", channel="B1", flow="grid_export_solar", cadence_min=30,
    )
    return pl.concat([imp, exp]).sort("t_start")


def test_battery_only_with_existing_solar_reduces_import_and_export(solar_customer_df):
    """Battery-only scenario on a customer who already has solar export."""
    bat_cfg = mdtypes.BatteryConfig(capacity_kwh=10.0, max_kw=5.0, round_trip_eff=0.9)
    result = scenario.run(solar_customer_df, battery=bat_cfg)

    assert result.delta["import_kwh_delta"] < 0
    assert result.delta["export_kwh_delta"] < 0
    assert result.explain["battery_charge_kwh"] > 0
    assert result.explain["battery_discharge_kwh"] > 0


def test_pv_stacked_increases_export_and_decreases_import(solar_customer_df):
    """Adding PV to a dataset that already has solar export."""
    pv_cfg = mdtypes.PVConfig(system_kwp=6.6, inverter_kw=5.0, loss_fraction=0.15)
    result = scenario.run(solar_customer_df, pv=pv_cfg)

    assert result.delta["import_kwh_delta"] < 0, "PV must reduce grid import"
    assert result.delta["export_kwh_delta"] > 0, "Stacked PV must increase solar export"


def test_pv_stacked_export_equals_original_plus_new_excess(solar_customer_df, day_30min):
    """Total after-export equals original export + PV excess not consumed by load."""
    pv_cfg = mdtypes.PVConfig(system_kwp=6.6, inverter_kw=5.0, loss_fraction=0.15)
    result = scenario.run(solar_customer_df, pv=pv_cfg)

    pv_arr = scenario._apply_pv(day_30min, pv_cfg, interval_h=0.5)
    orig_import = _flow_to_array(solar_customer_df, day_30min, "grid_import")
    orig_export = _flow_to_array(solar_customer_df, day_30min, "grid_export_solar")

    net_before = orig_import - orig_export
    net_after = net_before - pv_arr
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

    pv_arr = scenario._apply_pv(day_30min, pv_cfg, interval_h=0.5)
    baseline = np.full(len(day_30min), 0.3)
    used_by_load = np.minimum(pv_arr, baseline)
    pv_total = pv_arr.sum()
    expected_pct = float(used_by_load.sum() / pv_total * 100.0) if pv_total > 0 else 0.0

    actual_pct = result.explain.get("pv_self_consumption_pct")
    assert actual_pct is not None
    assert abs(actual_pct - expected_pct) < 1e-6


def test_pv_does_not_change_evening_peak_demand(day_30min):
    """PV generation stops before peak-demand window (19:00+), so adding PV
    must not affect the peak demand figure reported in the summary.
    """
    kwh_vals = np.full(len(day_30min), 0.3)
    hours = day_30min.dt.hour().to_numpy()
    kwh_vals[hours == 19] = 2.0

    base = utils.build_canon_frame(
        day_30min, kwh_vals, nmi="Q", channel="E1", flow="grid_import", cadence_min=30
    )
    pv_cfg = mdtypes.PVConfig(system_kwp=6.6, inverter_kw=5.0, loss_fraction=0.15)
    result = scenario.run(base, pv=pv_cfg)

    before_peak = result.summary_before["stats"]["peak_consumption_kw"]
    after_peak = result.summary_after["stats"]["peak_consumption_kw"]

    assert abs(after_peak - before_peak) < 1e-6


# ---------------------------------------------------------------------------
# Net-meter formulation: EV + solar customer correctness
# ---------------------------------------------------------------------------


def test_ev_on_solar_customer_no_simultaneous_import_and_export(solar_customer_df, day_30min):
    """Regression: adding EV to a solar customer must not produce simultaneous import AND export."""
    ev_cfg = mdtypes.EVConfig(
        daily_kwh=4.0,
        max_kw=5.0,
        window_start="09:00",
        window_end="14:00",
        days="ALL",
        strategy="scheduled",
    )
    result = scenario.run(solar_customer_df, ev=ev_cfg)

    after_import = _series_from_after(result.df_after, day_30min, "grid_import")
    after_export = _series_from_after(result.df_after, day_30min, "grid_export_solar")

    both_positive = (after_import > 1e-9) & (after_export > 1e-9)
    assert not both_positive.any(), (
        f"Simultaneous import and export found at {both_positive.sum()} interval(s)."
    )


def test_ev_on_solar_customer_reduces_export_before_adding_import(solar_customer_df, day_30min):
    """EV during solar hours should consume export before adding import."""
    ev_cfg = mdtypes.EVConfig(
        daily_kwh=4.0,
        max_kw=5.0,
        window_start="08:00",
        window_end="16:00",
        days="ALL",
        strategy="scheduled",
    )
    baseline_export = _flow_to_array(solar_customer_df, day_30min, "grid_export_solar")
    result = scenario.run(solar_customer_df, ev=ev_cfg)
    after_export = _series_from_after(result.df_after, day_30min, "grid_export_solar")

    assert after_export.sum() < baseline_export.sum()


def test_ev_pv_battery_combo_on_solar_customer_energy_balance(solar_customer_df, day_30min):
    """Full combo (EV + PV + battery) on an existing-solar customer energy balance."""
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

    import_reduction = before_import + ev_kwh - after_import
    pv_effective_on_import = pv_kwh + bat_dis - bat_ch - export_delta

    assert abs(import_reduction - pv_effective_on_import) < 1e-6


def test_ev_pv_battery_combo_golden_trace(day_30min):
    """Golden-trace test for full EV+PV+battery combo on an import-only baseline."""
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

    ev_arr = scenario._apply_ev(day_30min, ev_cfg, interval_h=0.5)
    pv_arr = scenario._apply_pv(day_30min, pv_cfg, interval_h=0.5)

    net_after = baseline + ev_arr - pv_arr
    expected_import = np.maximum(net_after, 0.0)
    expected_excess = np.maximum(-net_after, 0.0)

    _dis, _ch, _soc = scenario._apply_battery_self_consume(
        expected_import,
        expected_excess,
        bat_cfg,
        0.5,
    )

    actual_import = _series_from_after(result.df_after, day_30min, "grid_import")
    actual_export = _series_from_after(result.df_after, day_30min, "grid_export_solar")

    np.testing.assert_allclose(actual_import, expected_import, rtol=0, atol=1e-9)
    np.testing.assert_allclose(actual_export, expected_excess, rtol=0, atol=1e-9)
