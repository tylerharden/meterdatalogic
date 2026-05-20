"""Validation tests to enforce canonical frame invariants."""

import polars as pl
import pytest

from meterdatalogic import validate


def test_assert_canon_rejects_non_monotonic(halfhour_rng):
    ts = halfhour_rng.gather([1, 0, 2])
    df = pl.DataFrame({
        "t_start": ts,
        "nmi": ["Q"] * 3,
        "channel": ["E1"] * 3,
        "flow": ["grid_import"] * 3,
        "kwh": [1.0] * 3,
        "cadence_min": [30, 30, 30],
    })
    with pytest.raises(Exception):
        validate.assert_canon(df)


def test_assert_canon_rejects_naive_t_start(canon_df_one_nmi):
    df = canon_df_one_nmi.with_columns(pl.col("t_start").dt.replace_time_zone(None))
    with pytest.raises(Exception):
        validate.assert_canon(df)


def test_assert_canon_rejects_missing_column(canon_df_one_nmi):
    df = canon_df_one_nmi.drop("kwh")
    with pytest.raises(Exception):
        validate.assert_canon(df)


def test_assert_canon_accepts_valid(canon_df_one_nmi):
    validate.assert_canon(canon_df_one_nmi)


def test_validate_nmi_filters(canon_df_one_nmi):
    out = validate.validate_nmi(canon_df_one_nmi, nmi="Q1234567890")
    assert out["nmi"].unique().to_list() == ["Q1234567890"]


def test_validate_nmi_rejects_unknown(canon_df_one_nmi):
    with pytest.raises(ValueError, match="not in the dataset"):
        validate.validate_nmi(canon_df_one_nmi, nmi="UNKNOWN")
