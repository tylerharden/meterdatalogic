from __future__ import annotations
from typing import Optional
import numpy as np
import polars as pl

from ..analytics import pricing
from ..io import validate
from ..core import canon, utils
from ..core.types import CanonFrame

from .types import (
    EVConfig,
    PVConfig,
    BatteryConfig,
    ScenarioResult,
    ScenarioDelta,
    Plan,
    ScenarioExplain,
)


def _normalised_pv_shape(t_start: pl.Series) -> np.ndarray:
    """Normalised PV power shape (0..1), daylight window 06:00-18:00, peak ~12:00."""
    if t_start.dtype.time_zone is None:
        raise ValueError("t_start must be timezone-aware for accurate PV alignment.")
    hour = t_start.dt.hour().cast(pl.Float64).to_numpy()
    minute = t_start.dt.minute().cast(pl.Float64).to_numpy()
    hours = hour + minute / 60.0
    x = (hours - 6.0) / 12.0 * np.pi
    x = np.clip(x, 0.0, np.pi)
    shape = np.sin(x) ** 1.2
    shape[(hours < 6.0) | (hours > 18.0)] = 0.0
    return shape


def _apply_ev(t_start: pl.Series, ev: EVConfig, interval_h: float) -> np.ndarray:
    """Return per-interval kWh EV charging as a numpy array."""
    n = len(t_start)
    if ev is None or ev.daily_kwh <= 0 or ev.max_kw <= 0:
        return np.zeros(n, dtype=float)

    day_mask_arr = utils.day_mask(t_start, ev.days).to_numpy()
    start_t = utils.parse_time_str(ev.window_start)
    end_t = utils.parse_time_str(ev.window_end)
    win_mask_arr = utils.time_in_range(t_start, start_t, end_t).to_numpy()

    per_int_limit = ev.max_kw * interval_h
    kwh = np.zeros(n, dtype=float)

    dates_py = t_start.dt.date().to_list()
    unique_days = sorted(set(dates_py))

    if ev.strategy == "immediate":
        is_wraparound = start_t >= end_t
        for d in unique_days:
            positions = np.flatnonzero(
                np.array([dd == d for dd in dates_py]) & day_mask_arr & win_mask_arr
            )
            if not len(positions):
                continue
            need = ev.daily_kwh
            if is_wraparound:
                pos_times = [t_start[int(p)].time() for p in positions]
                is_evening = np.array([t >= start_t for t in pos_times])
                positions = np.concatenate([positions[is_evening], positions[~is_evening]])
            for p in positions:
                if need <= 1e-12:
                    break
                take = min(per_int_limit, need)
                kwh[p] = take
                need -= take

    elif ev.strategy == "scheduled":
        for d in unique_days:
            mask = np.array([dd == d for dd in dates_py]) & day_mask_arr & win_mask_arr
            nc = int(mask.sum())
            if nc == 0:
                continue
            per = min(per_int_limit, ev.daily_kwh / nc)
            kwh[mask] += per

    return kwh


def _apply_pv(t_start: pl.Series, pv: PVConfig, interval_h: float) -> np.ndarray:
    """Return per-interval kWh PV generation as a numpy array."""
    n = len(t_start)
    if pv is None or pv.system_kwp <= 0 or pv.inverter_kw <= 0:
        return np.zeros(n, dtype=float)

    base = _normalised_pv_shape(t_start)
    kw_ac = base * pv.system_kwp * (1.0 - pv.loss_fraction)
    kw_ac = np.minimum(kw_ac, pv.inverter_kw)

    scale = pv.seasonal_scale or {}
    if scale:
        months = [f"{ts.month:02d}" for ts in t_start.to_list()]
        mult = np.array([scale.get(m, 1.0) for m in months])
        kw_ac = kw_ac * mult

    return kw_ac * interval_h


def _apply_battery_self_consume(
    import_prebat: np.ndarray,
    pv_excess_prebat: np.ndarray,
    cfg: BatteryConfig,
    interval_h: float,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Returns (discharge_kwh, charge_kwh, soc_series_kwh)."""
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
    soc_now = soc_min

    for i in range(n):
        pv_avail = pv_excess_prebat[i]
        room = max(soc_max - soc_now, 0.0)
        can_store = room / charge_eff if charge_eff > 0 else 0.0
        ch = min(pv_avail, e_cap, can_store)
        if ch > 0:
            soc_now = min(soc_max, soc_now + ch * charge_eff)
            pv_excess_prebat[i] -= ch
            charge[i] = ch

        need = import_prebat[i]
        max_out_soc = max(soc_now - soc_min, 0.0) * discharge_eff
        out_e = min(need, e_cap, max_out_soc)
        if out_e > 0:
            draw = out_e / discharge_eff if discharge_eff > 0 else 0.0
            soc_now = max(soc_min, soc_now - draw)
            import_prebat[i] -= out_e
            discharge[i] = out_e

        soc[i] = soc_now

    return discharge, charge, soc


def run(
    df: CanonFrame,
    *,
    ev: Optional[EVConfig] = None,
    pv: Optional[PVConfig] = None,
    battery: Optional[BatteryConfig] = None,
    plan: Optional[Plan] = None,
) -> ScenarioResult:
    """
    Simulate EV, PV, and Battery against baseline load. Returns before/after DataFrames,
    summaries, optional cost tables, and deltas.
    """
    validate.assert_canon(df)

    if "t_start" not in df.columns:
        raise TypeError("scenario.run requires a 't_start' column.")

    all_ts = df["t_start"].unique().sort()
    df_imp = df.filter(pl.col("flow").str.contains("import"))
    df_exp = df.filter(pl.col("flow").str.contains("export"))

    def _agg_to_ts(src: CanonFrame) -> np.ndarray:
        if src.is_empty():
            return np.zeros(len(all_ts), dtype=float)
        agg = src.group_by("t_start").agg(pl.col("kwh").sum())
        full = pl.DataFrame({"t_start": all_ts}).join(agg, on="t_start", how="left")
        return full["kwh"].fill_null(0.0).cast(pl.Float64).to_numpy()

    import_arr = _agg_to_ts(df_imp)
    export_arr = _agg_to_ts(df_exp)

    interval_h = utils.interval_hours(df)

    ev_arr = _apply_ev(all_ts, ev, interval_h) if ev else np.zeros(len(all_ts))
    pv_arr = _apply_pv(all_ts, pv, interval_h) if pv else np.zeros(len(all_ts))

    net_before = import_arr - export_arr
    local_load_net = net_before + ev_arr - pv_arr
    used_by_load = np.maximum(np.minimum(pv_arr, net_before + ev_arr), 0.0)

    import_prebat = np.maximum(local_load_net, 0.0)
    combined_excess = np.maximum(-local_load_net, 0.0)

    bat_dis = bat_ch = soc_arr = np.zeros(len(all_ts))
    if battery and battery.capacity_kwh > 0 and battery.max_kw > 0:
        bat_dis, bat_ch, soc_arr = _apply_battery_self_consume(
            import_prebat=import_prebat,
            pv_excess_prebat=combined_excess,
            cfg=battery,
            interval_h=interval_h,
        )

    export_after = combined_excess

    orig_imp_ts = set(df_imp["t_start"].to_list()) if not df_imp.is_empty() else set()
    orig_exp_ts = set(df_exp["t_start"].to_list()) if not df_exp.is_empty() else set()
    ts_list = all_ts.to_list()

    imp_mask = np.array([ts in orig_imp_ts or import_prebat[i] > 0 for i, ts in enumerate(ts_list)])
    exp_mask = np.array([ts in orig_exp_ts or export_after[i] > 0 for i, ts in enumerate(ts_list)])

    nmi_val = str(df["nmi"][0]) if "nmi" in df.columns and len(df) else None
    cad_min = int(df["cadence_min"][0]) if "cadence_min" in df.columns and len(df) else None
    tz = df["t_start"].dtype.time_zone

    parts = []
    if imp_mask.any():
        parts.append(
            utils.build_canon_frame(
                all_ts.filter(pl.Series(imp_mask)),
                import_prebat[imp_mask],
                nmi=nmi_val,
                channel="E1",
                flow="grid_import",
                cadence_min=cad_min,
            )
        )
    if exp_mask.any():
        parts.append(
            utils.build_canon_frame(
                all_ts.filter(pl.Series(exp_mask)),
                export_after[exp_mask],
                nmi=nmi_val,
                channel="B1",
                flow="grid_export_solar",
                cadence_min=cad_min,
            )
        )

    if parts:
        df_after: CanonFrame = pl.concat(parts).sort("t_start")
        # Ensure tz matches input
        if tz and df_after["t_start"].dtype.time_zone != tz:
            df_after = df_after.with_columns(
                pl.col("t_start").dt.convert_time_zone(tz)
            )
    else:
        df_after = utils.empty_canon_frame(tz=tz or canon.DEFAULT_TZ)

    validate.assert_canon(df_after)

    from ..analytics import summary as _summary

    summary_before = _summary.summarise(df)
    summary_after = _summary.summarise(df_after)

    cost_before = cost_after = None
    if plan is not None:
        bill_b = pricing.compute_billables(df, plan, mode="monthly")
        cost_before = pricing.estimate_costs(bill_b, plan)
        bill_a = pricing.compute_billables(df_after, plan, mode="monthly")
        cost_after = pricing.estimate_costs(bill_a, plan)

    flow_before = utils.compute_flow_totals(df)
    flow_after = utils.compute_flow_totals(df_after) if len(df_after) else {}

    import_b = flow_before.get("grid_import", 0.0)
    export_b = flow_before.get("grid_export_solar", 0.0)
    import_a = flow_after.get("grid_import", 0.0)
    export_a = flow_after.get("grid_export_solar", 0.0)

    delta: ScenarioDelta = {
        "import_kwh_delta": import_a - import_b,
        "export_kwh_delta": export_a - export_b,
        "total_kwh_delta": (import_a + export_a) - (import_b + export_b),
        "cost_total_delta": (
            float(cost_after["total"].sum() - cost_before["total"].sum())
            if (cost_before is not None and cost_after is not None)
            else None
        ),
    }
    explain: ScenarioExplain = {
        "ev_kwh": float(ev_arr.sum()) if ev else 0.0,
        "pv_kwh": float(pv_arr.sum()) if pv else 0.0,
        "battery_discharge_kwh": float(np.sum(bat_dis)),
        "battery_charge_kwh": float(np.sum(bat_ch)),
        "battery_cycles_est": (
            float(np.sum(bat_dis) / max(battery.capacity_kwh, 1e-6)) if battery else 0.0
        ),
        "pv_self_consumption_pct": (
            float(100.0 * np.sum(used_by_load) / max(pv_arr.sum(), 1e-9))
            if pv and pv_arr.sum() > 0
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
