"""Pricing tests exercising monthly billables merge and cost math."""

import datetime as _dt
import polars as pl
import pytest

from meterdatalogic import pricing, utils, ingest
import meterdatalogic.types as mdtypes

TZ = "Australia/Brisbane"


def _ts_range(start: str, periods: int, freq_min: int) -> pl.Series:
    base = _dt.datetime.fromisoformat(start)
    times = [base + _dt.timedelta(minutes=freq_min * i) for i in range(periods)]
    return pl.Series(times, dtype=pl.Datetime("us")).dt.replace_time_zone(TZ)


def _mk_io_week(halfhour_rng: pl.Series) -> pl.DataFrame:
    """Build a week with steady import and sparse export."""
    n = len(halfhour_rng)
    imp = utils.build_canon_frame(
        halfhour_rng,
        [0.5] * n,
        nmi="Q123",
        channel="E1",
        flow="grid_import",
        cadence_min=30,
    )
    export_idx = halfhour_rng.gather(list(range(0, n, 4)))
    exp = utils.build_canon_frame(
        export_idx,
        [0.25] * len(export_idx),
        nmi="Q123",
        channel="B1",
        flow="grid_export_solar",
        cadence_min=120,
    )
    return pl.concat([imp, exp]).sort("t_start")


def _months_from_series(ts: pl.Series) -> list[str]:
    return ts.dt.strftime("%Y-%m").unique().sort().to_list()


def test_no_demand_no_export(halfhour_rng, monkeypatch):
    """If there is no demand and no export, only energy_cost should be > 0."""
    df = utils.build_canon_frame(
        halfhour_rng,
        [0.5] * len(halfhour_rng),
        nmi="Q",
        channel="E1",
        flow="grid_import",
        cadence_min=30,
    )
    plan = mdtypes.Plan(
        usage_bands=[
            mdtypes.ToUBand(name="peak_kwh", start="00:00", end="24:00", rate_c_per_kwh=20.0)
        ],
        demand=None,
        fixed_c_per_day=0.0,
        feed_in_c_per_kwh=0.0,
    )

    def fake_tou(d, bands):
        months = _months_from_series(d["t_start"])
        return pl.DataFrame({"month": months, "peak_kwh": [100.0] * len(months)})

    monkeypatch.setattr(pricing.transform, "tou_bins", fake_tou, raising=True)

    bill = pricing.compute_billables(df, plan, mode="monthly")
    cost = pricing.estimate_costs(bill, plan)
    assert (cost["demand_cost"] == 0).all()
    assert (cost["feed_in_credit"] == 0).all()
    assert (cost["energy_cost"] > 0).all()


def test_feed_in_credit_negative(halfhour_rng, monkeypatch):
    """Export presence should create a non-positive feed-in credit."""
    df = _mk_io_week(halfhour_rng)
    plan = mdtypes.Plan(
        usage_bands=[
            mdtypes.ToUBand(name="peak_kwh", start="00:00", end="24:00", rate_c_per_kwh=30.0)
        ],
        demand=None,
        fixed_c_per_day=0.0,
        feed_in_c_per_kwh=5.0,
    )

    def fake_tou(d, bands):
        months = _months_from_series(d["t_start"])
        return pl.DataFrame({"month": months, "peak_kwh": [100.0] * len(months)})

    monkeypatch.setattr(pricing.transform, "tou_bins", fake_tou, raising=True)

    bill = pricing.compute_billables(df, plan, mode="monthly")
    cost = pricing.estimate_costs(bill, plan)
    assert "export_kwh" in bill.columns
    assert (cost["feed_in_credit"] <= 0).all()
    recomputed = (
        cost["energy_cost"] + cost["demand_cost"] + cost["fixed_cost"] + cost["feed_in_credit"]
    )
    assert (abs(recomputed - cost["total"]) < 1e-9).all()


def test_pricing_estimate_monthly_cost(canon_df_mixed_flows):
    """Full-plan smoke test: all components present and numeric totals."""
    df = ingest.from_dataframe(canon_df_mixed_flows)
    plan = mdtypes.Plan(
        usage_bands=[
            mdtypes.ToUBand(name="off", start="00:00", end="16:00", rate_c_per_kwh=22.0),
            mdtypes.ToUBand(name="peak", start="16:00", end="21:00", rate_c_per_kwh=45.0),
            mdtypes.ToUBand(name="shoulder", start="21:00", end="24:00", rate_c_per_kwh=28.0),
        ],
        demand=mdtypes.DemandCharge(
            window_start="16:00", window_end="21:00", days="MF", rate_per_kw_per_month=12.0
        ),
        fixed_c_per_day=95.0,
        feed_in_c_per_kwh=6.0,
    )
    bill = pricing.compute_billables(df, plan, mode="monthly")
    cost = pricing.estimate_costs(bill, plan)
    assert set(
        ["month", "energy_cost", "demand_cost", "fixed_cost", "feed_in_credit", "total"]
    ).issubset(set(cost.columns))
    assert cost["total"].dtype in (pl.Float64, pl.Float32)


def test_compute_billables_optional_flows(halfhour_rng):
    """include_controlled_load and include_total_import add expected columns."""
    import_df = utils.build_canon_frame(
        halfhour_rng,
        [0.5] * len(halfhour_rng),
        nmi="Q123",
        channel="E1",
        flow="grid_import",
        cadence_min=30,
    )
    n_cl = len(halfhour_rng) // 2
    cl_series = halfhour_rng.gather(list(range(0, len(halfhour_rng), 2)))
    cl_df = utils.build_canon_frame(
        cl_series,
        [0.3] * n_cl,
        nmi="Q123",
        channel="E2",
        flow="controlled_load_import",
        cadence_min=60,
    )
    n_exp = len(halfhour_rng) // 3
    exp_series = halfhour_rng.gather(list(range(0, len(halfhour_rng), 3)))
    export_df = utils.build_canon_frame(
        exp_series,
        [0.2] * n_exp,
        nmi="Q123",
        channel="B1",
        flow="grid_export_solar",
        cadence_min=90,
    )
    df = pl.concat([import_df, cl_df, export_df]).sort("t_start")

    plan = mdtypes.Plan(
        usage_bands=[
            mdtypes.ToUBand(name="all_day", start="00:00", end="24:00", rate_c_per_kwh=25.0)
        ],
        demand=None,
        fixed_c_per_day=100.0,
        feed_in_c_per_kwh=8.0,
    )

    bill_default = pricing.compute_billables(df, plan, mode="monthly")
    assert "controlled_load_kwh" not in bill_default.columns
    assert "total_import_kwh" not in bill_default.columns
    assert "export_kwh" in bill_default.columns

    bill_cl = pricing.compute_billables(df, plan, mode="monthly", include_controlled_load=True)
    assert "controlled_load_kwh" in bill_cl.columns
    assert "total_import_kwh" not in bill_cl.columns
    assert (bill_cl["controlled_load_kwh"] >= 0).all()

    bill_ti = pricing.compute_billables(df, plan, mode="monthly", include_total_import=True)
    assert "controlled_load_kwh" not in bill_ti.columns
    assert "total_import_kwh" in bill_ti.columns
    assert (bill_ti["total_import_kwh"] >= 0).all()

    bill_both = pricing.compute_billables(
        df, plan, mode="monthly", include_controlled_load=True, include_total_import=True
    )
    assert "controlled_load_kwh" in bill_both.columns
    assert "total_import_kwh" in bill_both.columns
    assert (bill_both["controlled_load_kwh"] >= 0).all()
    assert (bill_both["total_import_kwh"] >= 0).all()
    assert (bill_both["total_import_kwh"] >= bill_both["controlled_load_kwh"]).all()
