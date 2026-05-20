"""Tests for logical compression and reconstruction in formats."""

import polars as pl

from meterdatalogic import formats, ingest, utils, validate


def test_to_logical_empty_returns_list():
    df_empty = utils.empty_canon_frame()
    out = formats.to_logical(df_empty)
    assert out == []


def test_to_logical_basic_series(canon_df_one_nmi):
    df = ingest.from_dataframe(canon_df_one_nmi)
    lc = formats.to_logical(df)
    assert len(lc) == 1
    series = lc[0]
    assert series["nmi"] == "Q1234567890"
    assert series["channel"] == "E1"
    assert series["tz"]

    days = series["days"]
    assert len(days) >= 7
    day0 = days[0]
    assert isinstance(day0["interval_min"], int)
    assert day0["interval_min"] in (30, 60, 15)
    slots = int(24 * 60 / day0["interval_min"])
    assert day0["slots"] == slots
    flows = day0["flows"]
    assert "grid_import" in flows
    assert isinstance(flows["grid_import"], list)
    assert len(flows["grid_import"]) == slots


def test_roundtrip_logical_from_mixed_flows(canon_df_mixed_flows):
    df = ingest.from_dataframe(canon_df_mixed_flows)
    validate.assert_canon(df)

    obj = formats.to_logical(df)
    df2 = formats.from_logical(obj)

    validate.assert_canon(df2)

    # Total energy per flow preserved
    a = df.group_by("flow").agg(pl.col("kwh").sum()).sort("flow")
    b = df2.group_by("flow").agg(pl.col("kwh").sum()).sort("flow")
    assert set(a["flow"].to_list()) == set(b["flow"].to_list())
    for flow in a["flow"].to_list():
        a_kwh = float(a.filter(pl.col("flow") == flow)["kwh"][0])
        b_kwh = float(b.filter(pl.col("flow") == flow)["kwh"][0])
        assert abs(a_kwh - b_kwh) < 1e-6, f"Flow {flow}: {a_kwh} != {b_kwh}"
