"""Pricing tests exercising monthly billables merge and cost math.

- test_no_demand_no_export: plan without demand/feed-in; energy cost > 0, others 0.
- test_feed_in_credit_negative: presence of export yields negative credit.
- test_pricing_estimate_monthly_cost: full plan smoke with all components present.
"""

import pandas as pd
import numpy as np

from meterdatalogic import pricing, utils, ingest
import meterdatalogic.types as mdtypes


def _mk_io_week(idx):
    """Build a week with steady import and sparse export (every 4th slot)."""
    imp = utils.build_canon_frame(
        idx,
        np.ones(len(idx)) * 0.5,  # 0.5 kWh per slot
        nmi="Q123",
        channel="E1",
        flow="grid_import",
        cadence_min=30,
    )
    exp = utils.build_canon_frame(
        idx[::4],
        np.ones(len(idx[::4])) * 0.25,  # 0.25 kWh on a subset of slots
        nmi="Q123",
        channel="B1",
        flow="grid_export_solar",
        cadence_min=120,
    )
    return pd.concat([imp, exp]).sort_index()


def test_no_demand_no_export(halfhour_rng, monkeypatch):
    """If there is no demand and no export, only energy_cost should be > 0."""
    df = utils.build_canon_frame(
        halfhour_rng,
        np.ones(len(halfhour_rng)) * 0.5,
        nmi="Q",
        channel="E1",
        flow="grid_import",
        cadence_min=30,
    )
    # Plan with a single all-day band, no demand or feed-in.
    plan = mdtypes.Plan(
        usage_bands=[mdtypes.ToUBand(name="peak_kwh", start="00:00", end="24:00", rate_c_per_kwh=20.0)],
        demand=None,
        fixed_c_per_day=0.0,
        feed_in_c_per_kwh=0.0,
    )
    # Monkeypatch TOU to emit fixed monthly kWh for determinism.
    monkeypatch.setattr(
        pricing.transform,
        "tou_bins",
        lambda d, bands: pd.DataFrame(
            {
                "month": utils.month_label(d.index.unique()).unique(),
                "peak_kwh": [100.0] * len(utils.month_label(d.index.unique()).unique()),
            }
        ),
        raising=True,
    )
    # No demand in this plan.
    monkeypatch.setattr(
        pricing.transform,
        "aggregate",
        lambda *a, **k: pd.DataFrame(
            {
                "t_start": pd.to_datetime(
                    [m + "-01" for m in utils.month_label(df.index).unique()]
                ),
                "demand_kw": 0.0,
            }
        ),
        raising=True,
    )
    bill = pricing.compute_billables(df, plan, mode="monthly")
    cost = pricing.estimate_costs(bill, plan)
    assert (cost["demand_cost"] == 0).all()
    assert (cost["feed_in_credit"] == 0).all()
    assert (cost["energy_cost"] > 0).all()


def test_feed_in_credit_negative(halfhour_rng, monkeypatch):
    """Export presence should create a non-positive (negative/zero) feed-in credit."""
    df = _mk_io_week(halfhour_rng)
    plan = mdtypes.Plan(
        usage_bands=[mdtypes.ToUBand(name="peak_kwh", start="00:00", end="24:00", rate_c_per_kwh=30.0)],
        demand=None,
        fixed_c_per_day=0.0,
        feed_in_c_per_kwh=5.0,
    )
    # Deterministic TOU and zero demand for isolation.
    monkeypatch.setattr(
        pricing.transform,
        "tou_bins",
        lambda d, bands: pd.DataFrame(
            {
                "month": utils.month_label(d.index.unique()).unique(),
                "peak_kwh": [100.0] * len(utils.month_label(d.index.unique()).unique()),
            }
        ),
        raising=True,
    )
    monkeypatch.setattr(
        pricing.transform,
        "aggregate",
        lambda *a, **k: pd.DataFrame(
            {
                "t_start": pd.to_datetime(
                    [m + "-01" for m in utils.month_label(df.index).unique()]
                ),
                "demand_kw": 0.0,
            }
        ),
        raising=True,
    )
    bill = pricing.compute_billables(df, plan, mode="monthly")
    cost = pricing.estimate_costs(bill, plan)
    assert "export_kwh" in bill.columns  # monthly export aggregation included
    assert (cost["feed_in_credit"] <= 0).all()
    # Total must equal sum of components.
    recomputed = cost[["energy_cost", "demand_cost", "fixed_cost", "feed_in_credit"]].sum(axis=1)
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
        demand=mdtypes.DemandCharge(window_start="16:00", window_end="21:00", days="MF", rate_per_kw_per_month=12.0),
        fixed_c_per_day=95.0,
        feed_in_c_per_kwh=6.0,
    )
    bill = pricing.compute_billables(df, plan, mode="monthly")
    cost = pricing.estimate_costs(bill, plan)
    assert set(
        ["month", "energy_cost", "demand_cost", "fixed_cost", "feed_in_credit", "total"]
    ).issubset(cost.columns)
    assert cost["total"].dtype.kind in "fc"


def test_compute_billables_optional_flows(halfhour_rng):
    """Test that include_controlled_load and include_total_import add expected columns."""
    # Build data with controlled load and multiple import flows
    import_df = utils.build_canon_frame(
        halfhour_rng,
        np.ones(len(halfhour_rng)) * 0.5,
        nmi="Q123",
        channel="E1",
        flow="grid_import",
        cadence_min=30,
    )
    cl_df = utils.build_canon_frame(
        halfhour_rng[::2],  # Every other interval
        np.ones(len(halfhour_rng[::2])) * 0.3,
        nmi="Q123",
        channel="E2",
        flow="controlled_load_import",
        cadence_min=60,
    )
    export_df = utils.build_canon_frame(
        halfhour_rng[::3],
        np.ones(len(halfhour_rng[::3])) * 0.2,
        nmi="Q123",
        channel="B1",
        flow="grid_export_solar",
        cadence_min=90,
    )
    df = pd.concat([import_df, cl_df, export_df]).sort_index()

    plan = mdtypes.Plan(
        usage_bands=[mdtypes.ToUBand(name="all_day", start="00:00", end="24:00", rate_c_per_kwh=25.0)],
        demand=None,
        fixed_c_per_day=100.0,
        feed_in_c_per_kwh=8.0,
    )

    # Test default - no optional columns
    bill_default = pricing.compute_billables(df, plan, mode="monthly")
    assert "controlled_load_kwh" not in bill_default.columns
    assert "total_import_kwh" not in bill_default.columns
    assert "export_kwh" in bill_default.columns

    # Test with controlled load
    bill_cl = pricing.compute_billables(df, plan, mode="monthly", include_controlled_load=True)
    assert "controlled_load_kwh" in bill_cl.columns
    assert "total_import_kwh" not in bill_cl.columns
    assert (bill_cl["controlled_load_kwh"] >= 0).all()

    # Test with total import
    bill_ti = pricing.compute_billables(df, plan, mode="monthly", include_total_import=True)
    assert "controlled_load_kwh" not in bill_ti.columns
    assert "total_import_kwh" in bill_ti.columns
    assert (bill_ti["total_import_kwh"] >= 0).all()

    # Test with both
    bill_both = pricing.compute_billables(
        df, plan, mode="monthly", include_controlled_load=True, include_total_import=True
    )
    assert "controlled_load_kwh" in bill_both.columns
    assert "total_import_kwh" in bill_both.columns
    assert (bill_both["controlled_load_kwh"] >= 0).all()
    assert (bill_both["total_import_kwh"] >= 0).all()
    # Total import should be >= controlled load (since controlled_load is a type of import)
    assert (bill_both["total_import_kwh"] >= bill_both["controlled_load_kwh"]).all()
