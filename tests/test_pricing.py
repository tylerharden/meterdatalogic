import meterdatalogic as ml


def test_pricing_estimate_monthly_cost(canon_df_mixed_flows):
    df = ml.ingest.from_dataframe(canon_df_mixed_flows)

    plan = ml.types.Plan(
        usage_bands=[
            ml.types.ToUBand("off", "00:00", "16:00", 22.0),
            ml.types.ToUBand("peak", "16:00", "21:00", 45.0),
            ml.types.ToUBand("shoulder", "21:00", "24:00", 28.0),
        ],
        demand=ml.types.DemandCharge("16:00", "21:00", "MF", 12.0),
        fixed_c_per_day=95.0,
        feed_in_c_per_kwh=6.0,
    )

    cost = ml.pricing.estimate_monthly_cost(df, plan)
    assert set(
        ["month", "energy_cost", "demand_cost", "fixed_cost", "feed_in_credit", "total"]
    ).issubset(cost.columns)
    # totals should be numeric
    assert cost["total"].dtype.kind in "fc"
