"""Validation tests to enforce canonical frame invariants."""

import pandas as pd
import pytest
from meterdatalogic import validate, ingest


def test_assert_canon_rejects_non_monotonic(halfhour_rng):
    """Indices must be strictly increasing; shuffled rows should fail."""
    df = pd.DataFrame(
        {"t_start": halfhour_rng[[1, 0, 2]], "nmi": "Q", "channel": "E1", "kwh": 1.0}
    ).set_index("t_start")
    with pytest.raises(Exception):
        validate.assert_canon(df)


def test_assert_canon_rejects_mixed_nmi(halfhour_rng):
    """Frames must be single‑NMI; mixing NMIs should fail."""
    df = pd.DataFrame(
        {
            "t_start": halfhour_rng,
            "nmi": ["A", "B"] * (len(halfhour_rng) // 2),
            "channel": "E1",
            "kwh": 1.0,
        }
    ).set_index("t_start")
    with pytest.raises(Exception):
        validate.assert_canon(df)


def test_assert_canon_rejects_naive_index_via_ingest(canon_df_one_nmi):
    """Naive indices are invalid; assert_canon should reject them."""
    df = canon_df_one_nmi.copy()
    df.index = df.index.tz_localize(None)
    with pytest.raises(Exception):
        validate.assert_canon(df)


def test_ensure_adds_tz_and_sorts(canon_df_one_nmi):
    """ensure() should output tz-aware, sorted index without mutation errors."""
    out = ingest.from_dataframe(canon_df_one_nmi, tz="Australia/Brisbane")
    out2 = validate.ensure(out)
    assert out2.index.tz is not None
    assert out2.index.is_monotonic_increasing


def test_assert_canon_rejects_invalid_columns(canon_df_one_nmi):
    """Missing required columns (e.g., kwh) should raise."""
    df = canon_df_one_nmi.copy()
    df = df.drop(columns=["kwh"])
    with pytest.raises(Exception):
        validate.assert_canon(df)
