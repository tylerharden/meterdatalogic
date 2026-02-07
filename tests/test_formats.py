"""Tests for logical compression and reconstruction in formats.

Covers:
- Empty canon frame -> logical []
- Basic series -> correct days/slots/interval_min and flows arrays
- Round-trip: canon -> logical -> canon preserves data
"""

import pandas as pd
import pandas.testing as pdt

from meterdatalogic import formats, ingest, canon, validate


def _required_cols(df: pd.DataFrame) -> pd.DataFrame:
    return df[canon.REQUIRED_COLS].copy()


def test_to_logical_empty_returns_list():
    df_empty = pd.DataFrame(columns=canon.REQUIRED_COLS).set_index(
        pd.DatetimeIndex([], tz=canon.DEFAULT_TZ, name=canon.INDEX_NAME)
    )
    out = formats.to_logical(df_empty)  # type: ignore[arg-type]
    assert out == []


def test_to_logical_basic_series(canon_df_one_nmi):
    df = ingest.from_dataframe(canon_df_one_nmi)
    lc = formats.to_logical(df)
    # One series for a single (nmi, channel)
    assert len(lc) == 1
    series = lc[0]
    assert series["nmi"] == "Q1234567890"
    assert series["channel"] == "E1"
    assert series["tz"]

    days = series["days"]
    # 7 days from the fixture
    assert len(days) >= 7
    day0 = days[0]
    assert isinstance(day0["interval_min"], int)
    assert day0["interval_min"] in (30, 60, 15)  # cadence inferred
    slots = int(24 * 60 / day0["interval_min"])
    assert day0["slots"] == slots
    # Should include import flow with array length == slots
    flows = day0["flows"]
    assert "grid_import" in flows
    assert isinstance(flows["grid_import"], list)
    assert len(flows["grid_import"]) == slots


def test_roundtrip_logical_from_mixed_flows(canon_df_mixed_flows):
    # ingest adds flow/cadence_min and enforces canon
    df = ingest.from_dataframe(canon_df_mixed_flows)
    validate.assert_canon(df)

    obj = formats.to_logical(df)
    df2 = formats.from_logical(obj)

    # Validate output is canon
    validate.assert_canon(df2)

    # Compare invariants instead of row-by-row (cadence/grouping may differ per-channel)
    # 1) Total energy per flow preserved
    a_flow = df.groupby("flow")["kwh"].sum()
    b_flow = df2.groupby("flow")["kwh"].sum()
    pdt.assert_series_equal(a_flow.sort_index(), b_flow.sort_index())

    # 2) Per-day totals per flow preserved
    a_day = (
        df.reset_index()
        .assign(day=lambda x: x["t_start"].dt.normalize().dt.strftime("%Y-%m-%d"))
        .groupby(["day", "flow"])["kwh"]
        .sum()
        .sort_index()
    )
    b_day = (
        df2.reset_index()
        .assign(day=lambda x: x["t_start"].dt.normalize().dt.strftime("%Y-%m-%d"))
        .groupby(["day", "flow"])["kwh"]
        .sum()
        .sort_index()
    )
    pdt.assert_series_equal(a_day, b_day)
