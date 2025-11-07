from __future__ import annotations
from typing import Optional
import numpy as np
import pandas as pd
from .types import EVConfig, PVConfig, BatteryConfig, ScenarioResult, Plan
from . import utils, validate, pricing, canon


def apply_ev(idx: pd.DatetimeIndex, ev: EVConfig, interval_h: float) -> pd.Series:
    """Return per-interval kWh EV charging."""
    if ev is None or ev.daily_kwh <= 0 or ev.max_kw <= 0:
        return pd.Series(0.0, index=idx, name="ev_charge_kwh")

    # Local wall times; idx is already tz-aware from ingest
    times = pd.Series(idx.time, index=idx)
    day_mask = utils._mask_days(idx, ev.days)

    start_t = utils._parse_hhmm(ev.window_start).time()
    end_t = utils._parse_hhmm(ev.window_end).time()
    win_mask = utils._time_in_range(times, start_t, end_t).to_numpy()

    per_int_limit = ev.max_kw * interval_h
    kwh = np.zeros(len(idx), dtype=float)

    # Group by day (date) and fill per the chosen strategy
    dates = idx.date
    unique_days = np.unique(dates)

    if ev.strategy == "immediate":
        # Fill window from the start each eligible day until daily_kwh is met
        for d in unique_days:
            mask = (dates == d) & day_mask & win_mask
            if not mask.any():
                continue
            need = ev.daily_kwh
            positions = np.flatnonzero(mask)
            for p in positions:
                if need <= 1e-12:
                    break
                take = min(per_int_limit, need)
                kwh[p] = take
                need -= take

    elif ev.strategy == "scheduled":
        # Evenly spread the daily_kwh across all allowed intervals that day
        for d in unique_days:
            mask = (dates == d) & day_mask & win_mask
            n = int(mask.sum())
            if n == 0:
                continue
            per = min(per_int_limit, ev.daily_kwh / n)
            kwh[mask] += per

    else:
        # Unknown strategy → no-op (or raise if preferred)
        pass

    return pd.Series(kwh, index=idx, name="ev_charge_kwh")


def apply_pv(idx: pd.DatetimeIndex, pv: PVConfig, interval_h: float) -> pd.Series:
    """Return per-interval kWh PV generation at the meter (after losses & inverter clip)."""
    if pv is None or pv.system_kwp <= 0 or pv.inverter_kw <= 0:
        return pd.Series(0.0, index=idx, name="pv_kwh")

    from .profiles import normalized_pv_shape

    base = normalized_pv_shape(idx)  # 0..1, midday peak ~1
    # losses and inverter clipping
    kw_ac = base * pv.system_kwp * (1.0 - pv.loss_fraction)
    kw_ac = np.minimum(kw_ac, pv.inverter_kw)

    # Optional seasonal scaling
    if pv.seasonal_scale:
        months = pd.Series([f"{ts.month:02d}" for ts in idx], index=idx)
        mult = months.map(lambda m: pv.seasonal_scale.get(m, 1.0)).to_numpy()
        kw_ac = kw_ac * mult

    kwh = kw_ac * interval_h
    return pd.Series(kwh, index=idx, name="pv_kwh")


def apply_battery_self_consume(
    import_prebat: np.ndarray,
    pv_excess_prebat: np.ndarray,
    cfg: BatteryConfig,
    interval_h: float,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """
    Returns (discharge_kwh, charge_kwh, soc_series_kwh)
      - charge draws from PV excess only (MVP, no grid charge)
      - discharge offsets import only (no export)
    """
    n = len(import_prebat)
    discharge = np.zeros(n, dtype=float)
    charge = np.zeros(n, dtype=float)
    soc = np.zeros(n, dtype=float)

    cap = cfg.capacity_kwh
    soc_min = cfg.soc_min * cap
    soc_max = cfg.soc_max * cap
    p_cap = cfg.max_kw
    e_cap = p_cap * interval_h
    eff = max(min(cfg.round_trip_eff, 0.999), 0.01)
    charge_eff = discharge_eff = np.sqrt(eff)

    soc_now = soc_min  # start at minimum

    for i in range(n):
        # 1) Charge from PV excess
        pv_avail = pv_excess_prebat[i]
        room = max(soc_max - soc_now, 0.0)
        max_in = e_cap
        # energy into battery increases SOC by (charge_eff * charge_kwh)
        can_store = room / charge_eff if charge_eff > 0 else 0.0
        ch = min(pv_avail, max_in, can_store)
        if ch > 0:
            soc_now = min(soc_max, soc_now + ch * charge_eff)
            pv_excess_prebat[i] -= ch
            charge[i] = ch

        # 2) Discharge to offset import
        need = import_prebat[i]
        # output limited by inverter power, demand need, and available SOC
        max_out_power = e_cap
        max_out_soc = max(soc_now - soc_min, 0.0) * discharge_eff
        out = min(need, max_out_power, max_out_soc)
        if out > 0:
            # reduce SOC by energy drawn before eff
            draw = out / discharge_eff if discharge_eff > 0 else 0.0
            soc_now = max(soc_min, soc_now - draw)
            import_prebat[i] -= out
            discharge[i] = out

        soc[i] = soc_now

    return discharge, charge, soc


def run(
    df: pd.DataFrame,
    *,
    ev: Optional[EVConfig] = None,
    pv: Optional[PVConfig] = None,
    battery: Optional[BatteryConfig] = None,
    plan: Optional[Plan] = None,
) -> ScenarioResult:
    """
    Simulate EV, PV, and Battery against baseline load at the input cadence (canon in → canon out).
    Returns before/after dataframes, summaries, optional cost tables, and deltas.
    """
    validate.assert_canon(df)

    # Baseline import/export series
    s_import0, s_export0 = utils._collapse_flows(df)
    idx = s_import0.index
    interval_h = utils._interval_hours(df)

    # 1) EV charging adds to local load
    ev_series = apply_ev(idx, ev, interval_h) if ev else pd.Series(0.0, index=idx)
    local_load1 = (s_import0 + ev_series).to_numpy()

    # 2) PV generation offsets load then exports
    pv_series = apply_pv(idx, pv, interval_h) if pv else pd.Series(0.0, index=idx)
    pv_arr = pv_series.to_numpy()
    used_by_load = np.minimum(pv_arr, local_load1)
    leftover_pv = pv_arr - used_by_load
    import_prebat = local_load1 - used_by_load  # numpy array
    export_prebat = s_export0.to_numpy() + leftover_pv.copy()

    # 3) Battery dispatch (self-consume)
    bat_dis = bat_ch = soc = np.zeros(len(idx))
    if battery and battery.capacity_kwh > 0 and battery.max_kw > 0:
        bat_dis, bat_ch, soc = apply_battery_self_consume(
            import_prebat=import_prebat,
            pv_excess_prebat=leftover_pv,
            cfg=battery,
            interval_h=interval_h,
        )
        # After battery: import reduced by discharge; export reduced by charge (already in function)
        # export_prebat already had pv leftover; battery charge from PV has been subtracted inside dispatcher

    # 4) Final after series
    s_import_after = pd.Series(import_prebat, index=idx, name="grid_import")
    s_export_after = pd.Series(export_prebat, index=idx, name="grid_export_solar")

    # Vectorized build of df_after (only positive intervals)
    imp_mask = s_import_after.to_numpy() > 0
    exp_mask = s_export_after.to_numpy() > 0
    nmi_val = df["nmi"].iloc[0] if "nmi" in df.columns and len(df) else None
    cad_min = (
        int(df["cadence_min"].iloc[0])
        if "cadence_min" in df.columns and len(df)
        else None
    )

    parts = []
    if imp_mask.any():
        parts.append(
            utils.build_canon_frame(
                idx[imp_mask],
                s_import_after.to_numpy()[imp_mask],
                nmi=nmi_val,
                channel="E1",
                flow="grid_import",
                cadence_min=cad_min,
            )
        )
    if exp_mask.any():
        parts.append(
            utils.build_canon_frame(
                idx[exp_mask],
                s_export_after.to_numpy()[exp_mask],
                nmi=nmi_val,
                channel="B1",
                flow="grid_export_solar",
                cadence_min=cad_min,
            )
        )

    if parts:
        df_after = pd.concat(parts, ignore_index=False).sort_index()
        df_after.index = df_after.index.tz_convert(df.index.tz)
    else:
        df_after = pd.DataFrame(columns=canon.REQUIRED_COLS).set_index(
            pd.DatetimeIndex([], tz=df.index.tz, name=canon.INDEX_NAME)
        )
    validate.assert_canon(df_after)

    # Summaries
    summary_before = __import__("meterdatalogic").summary.summarise(df)
    summary_after = __import__("meterdatalogic").summary.summarise(df_after)

    # Costs
    cost_before = cost_after = None
    if plan is not None:
        cost_before = pricing.estimate_monthly_cost(df, plan)
        cost_after = pricing.estimate_monthly_cost(df_after, plan)

    # Deltas & explainables
    kwh_before = df.groupby("flow")["kwh"].sum()
    kwh_after = (
        df_after.groupby("flow")["kwh"].sum()
        if len(df_after)
        else pd.Series(dtype=float)
    )
    import_b = float(kwh_before.get("grid_import", 0.0))
    export_b = float(kwh_before.get("grid_export_solar", 0.0))
    import_a = float(kwh_after.get("grid_import", 0.0))
    export_a = float(kwh_after.get("grid_export_solar", 0.0))
    delta = {
        "import_kwh_delta": import_a - import_b,
        "export_kwh_delta": export_a - export_b,
        "total_kwh_delta": (import_a + export_a) - (import_b + export_b),
        "cost_total_delta": (
            float(cost_after["total"].sum() - cost_before["total"].sum())
            if (cost_before is not None and cost_after is not None)
            else None
        ),
    }

    explain = {
        "ev_kwh": float(ev_series.sum()) if ev else 0.0,
        "pv_kwh": float(pv_series.sum()) if pv else 0.0,
        "battery_discharge_kwh": float(np.sum(bat_dis)),
        "battery_charge_kwh": float(np.sum(bat_ch)),
        "battery_cycles_est": (
            float(np.sum(bat_dis) / max(battery.capacity_kwh, 1e-6)) if battery else 0.0
        ),
        "pv_self_consumption_pct": (
            float(100.0 * np.sum(used_by_load) / max(pv_series.sum(), 1e-9))
            if pv and pv_series.sum() > 0
            else None
        ),
    }

    return ScenarioResult(
        df_before=df,
        df_after=df_after,
        summary_before=summary_before,
        summary_after=summary_after,
        cost_before=cost_before,
        cost_after=cost_after,
        delta=delta,
        explain=explain,
    )
