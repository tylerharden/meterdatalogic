from __future__ import annotations
import math
from collections import defaultdict
from typing import Optional
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


def _normalised_pv_shape(t_start: pl.Series) -> pl.Series:
    """Normalised PV power shape (0..1), daylight window 06:00-18:00, peak ~12:00."""
    if t_start.dtype.time_zone is None:
        raise ValueError("t_start must be timezone-aware for accurate PV alignment.")
    hours = t_start.dt.hour().cast(pl.Float64) + t_start.dt.minute().cast(pl.Float64) / 60.0
    x = ((hours - 6.0) / 12.0 * math.pi).clip(0.0, math.pi)
    shape = x.sin().pow(1.2)
    in_daylight = ((hours >= 6.0) & (hours <= 18.0)).cast(pl.Float64)
    return shape * in_daylight


def _apply_ev(t_start: pl.Series, ev: EVConfig, interval_h: float) -> pl.Series:
    """Return per-interval kWh EV charging as a polars Series."""
    n = len(t_start)
    if ev is None or ev.daily_kwh <= 0 or ev.max_kw <= 0:
        return pl.Series([0.0] * n, dtype=pl.Float64)

    day_mask_list = utils.day_mask(t_start, ev.days).to_list()
    start_t = utils.parse_time_str(ev.window_start)
    end_t = utils.parse_time_str(ev.window_end)
    win_mask_list = utils.time_in_range(t_start, start_t, end_t).to_list()

    per_int_limit = ev.max_kw * interval_h
    kwh = [0.0] * n

    dates_py = t_start.dt.date().to_list()
    unique_days = sorted(set(dates_py))

    # Pre-group eligible positions by date in a single O(n) pass
    date_to_positions: dict = defaultdict(list)
    for i, (dd, dm, wm) in enumerate(zip(dates_py, day_mask_list, win_mask_list)):
        if dm and wm:
            date_to_positions[dd].append(i)

    if ev.strategy == "immediate":
        is_wraparound = start_t >= end_t
        for d in unique_days:
            positions = date_to_positions[d]
            if not positions:
                continue
            need = ev.daily_kwh
            if is_wraparound:
                pos_times = [t_start[p].time() for p in positions]
                evening = [p for p, t in zip(positions, pos_times) if t >= start_t]
                morning = [p for p, t in zip(positions, pos_times) if t < start_t]
                positions = evening + morning
            for p in positions:
                if need <= 1e-12:
                    break
                take = min(per_int_limit, need)
                kwh[p] = take
                need -= take

    elif ev.strategy == "scheduled":
        for d in unique_days:
            positions = date_to_positions[d]
            nc = len(positions)
            if nc == 0:
                continue
            per = min(per_int_limit, ev.daily_kwh / nc)
            for p in positions:
                kwh[p] += per

    return pl.Series(kwh, dtype=pl.Float64)


def _apply_pv(t_start: pl.Series, pv: PVConfig, interval_h: float) -> pl.Series:
    """Return per-interval kWh PV generation as a polars Series."""
    n = len(t_start)
    if pv is None or pv.system_kwp <= 0 or pv.inverter_kw <= 0:
        return pl.Series([0.0] * n, dtype=pl.Float64)

    base = _normalised_pv_shape(t_start)
    kw_ac = (base * pv.system_kwp * (1.0 - pv.loss_fraction)).clip(upper_bound=pv.inverter_kw)

    scale = pv.seasonal_scale or {}
    if scale:
        months_str = t_start.dt.month().cast(pl.String).str.zfill(2)
        mult = months_str.map_elements(lambda m: scale.get(m, 1.0), return_dtype=pl.Float64)
        kw_ac = kw_ac * mult

    return kw_ac * interval_h


def _apply_battery_self_consume(
    import_prebat: list[float],
    pv_excess_prebat: list[float],
    cfg: BatteryConfig,
    interval_h: float,
) -> tuple[list[float], list[float], list[float]]:
    """Returns (discharge_kwh, charge_kwh, soc_series_kwh)."""
    n = len(import_prebat)
    discharge = [0.0] * n
    charge = [0.0] * n
    soc = [0.0] * n

    cap = cfg.capacity_kwh
    soc_min = cfg.soc_min * cap
    soc_max = cfg.soc_max * cap
    p_cap = cfg.max_kw
    e_cap = p_cap * interval_h
    eff = max(min(cfg.round_trip_eff, 0.999), 0.01)
    charge_eff = discharge_eff = math.sqrt(eff)
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

    def _agg_to_ts(src: CanonFrame) -> pl.Series:
        if src.is_empty():
            return pl.Series([0.0] * len(all_ts), dtype=pl.Float64)
        agg = src.group_by("t_start").agg(pl.col("kwh").sum())
        full = pl.DataFrame({"t_start": all_ts}).join(agg, on="t_start", how="left")
        return full["kwh"].fill_null(0.0).cast(pl.Float64)

    import_arr = _agg_to_ts(df_imp)
    export_arr = _agg_to_ts(df_exp)

    interval_h = utils.interval_hours(df)

    ev_arr = _apply_ev(all_ts, ev, interval_h) if ev else pl.Series([0.0] * len(all_ts), dtype=pl.Float64)
    pv_arr = _apply_pv(all_ts, pv, interval_h) if pv else pl.Series([0.0] * len(all_ts), dtype=pl.Float64)

    net_before = import_arr - export_arr
    local_load_net = net_before + ev_arr - pv_arr

    # element-wise min(pv_arr, net_before + ev_arr), clipped to >= 0
    combined = net_before + ev_arr
    used_by_load_list = [max(min(p, c), 0.0) for p, c in zip(pv_arr.to_list(), combined.to_list())]

    import_prebat = local_load_net.clip(lower_bound=0.0).to_list()
    combined_excess = (-local_load_net).clip(lower_bound=0.0).to_list()

    bat_dis: list[float] = [0.0] * len(all_ts)
    bat_ch: list[float] = [0.0] * len(all_ts)
    if battery and battery.capacity_kwh > 0 and battery.max_kw > 0:
        bat_dis, bat_ch, _ = _apply_battery_self_consume(
            import_prebat=import_prebat,
            pv_excess_prebat=combined_excess,
            cfg=battery,
            interval_h=interval_h,
        )

    orig_imp_ts = set(df_imp["t_start"].to_list()) if not df_imp.is_empty() else set()
    orig_exp_ts = set(df_exp["t_start"].to_list()) if not df_exp.is_empty() else set()
    ts_list = all_ts.to_list()

    imp_mask = pl.Series(
        [ts in orig_imp_ts or import_prebat[i] > 0 for i, ts in enumerate(ts_list)]
    )
    exp_mask = pl.Series(
        [ts in orig_exp_ts or combined_excess[i] > 0 for i, ts in enumerate(ts_list)]
    )

    nmi_val = str(df["nmi"][0]) if "nmi" in df.columns and len(df) else None
    cad_min = int(df["cadence_min"][0]) if "cadence_min" in df.columns and len(df) else None
    tz = df["t_start"].dtype.time_zone

    imp_mask_list = imp_mask.to_list()
    exp_mask_list = exp_mask.to_list()

    parts = []
    if imp_mask.any():
        parts.append(
            utils.build_canon_frame(
                all_ts.filter(imp_mask),
                [v for v, m in zip(import_prebat, imp_mask_list) if m],
                nmi=nmi_val,
                channel="E1",
                flow="grid_import",
                cadence_min=cad_min,
            )
        )
    if exp_mask.any():
        parts.append(
            utils.build_canon_frame(
                all_ts.filter(exp_mask),
                [v for v, m in zip(combined_excess, exp_mask_list) if m],
                nmi=nmi_val,
                channel="B1",
                flow="grid_export_solar",
                cadence_min=cad_min,
            )
        )

    if parts:
        df_after: CanonFrame = pl.concat(parts).sort("t_start")
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

    pv_total = float(pv_arr.sum())

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
        "pv_kwh": pv_total,
        "battery_discharge_kwh": float(sum(bat_dis)),
        "battery_charge_kwh": float(sum(bat_ch)),
        "battery_cycles_est": (
            float(sum(bat_dis) / max(battery.capacity_kwh, 1e-6)) if battery else 0.0
        ),
        "pv_self_consumption_pct": (
            float(100.0 * sum(used_by_load_list) / max(pv_total, 1e-9))
            if pv and pv_total > 0
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
