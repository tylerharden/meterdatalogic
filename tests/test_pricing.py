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
        usage_bands=[mdtypes.ToUBand("peak_kwh", "00:00", "24:00", 20.0)],
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
        "demand_window",
        lambda *a, **k: pd.DataFrame(
            {"month": utils.month_label(df.index).unique(), "demand_kw": 0.0}
        ),
        raising=True,
    )
    cost = pricing.estimate_monthly_cost(df, plan)
    assert (cost["demand_cost"] == 0).all()
    assert (cost["feed_in_credit"] == 0).all()
    assert (cost["energy_cost"] > 0).all()


def test_feed_in_credit_negative(halfhour_rng, monkeypatch):
    """Export presence should create a non-positive (negative/zero) feed-in credit."""
    df = _mk_io_week(halfhour_rng)
    plan = mdtypes.Plan(
        usage_bands=[mdtypes.ToUBand("peak_kwh", "00:00", "24:00", 30.0)],
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
        "demand_window",
        lambda *a, **k: pd.DataFrame(
            {"month": utils.month_label(df.index).unique(), "demand_kw": 0.0}
        ),
        raising=True,
    )
    bill = pricing.monthly_billables(df, plan)
    cost = pricing.estimate_monthly_cost(df, plan)
    assert "export_kwh" in bill.columns  # monthly export aggregation included
    assert (cost["feed_in_credit"] <= 0).all()
    # Total must equal sum of components.
    recomputed = cost[
        ["energy_cost", "demand_cost", "fixed_cost", "feed_in_credit"]
    ].sum(axis=1)
    assert (abs(recomputed - cost["total"]) < 1e-9).all()


def test_pricing_estimate_monthly_cost(canon_df_mixed_flows):
    """Full-plan smoke test: all components present and numeric totals."""
    df = ingest.from_dataframe(canon_df_mixed_flows)
    plan = mdtypes.Plan(
        usage_bands=[
            mdtypes.ToUBand("off", "00:00", "16:00", 22.0),
            mdtypes.ToUBand("peak", "16:00", "21:00", 45.0),
            mdtypes.ToUBand("shoulder", "21:00", "24:00", 28.0),
        ],
        demand=mdtypes.DemandCharge("16:00", "21:00", "MF", 12.0),
        fixed_c_per_day=95.0,
        feed_in_c_per_kwh=6.0,
    )
    cost = pricing.estimate_monthly_cost(df, plan)
    assert set(
        ["month", "energy_cost", "demand_cost", "fixed_cost", "feed_in_credit", "total"]
    ).issubset(cost.columns)
    assert cost["total"].dtype.kind in "fc"
