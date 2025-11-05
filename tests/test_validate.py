import pandas as pd
import pytest
import meterdatalogic as ml

def test_assert_canon_rejects_naive_index(canon_df_one_nmi):
    df = canon_df_one_nmi.copy()
    df.index = df.index.tz_localize(None)
    with pytest.raises(Exception):
        # must go through ingest to gain tz
        ml.validate.assert_canon(df)

def test_ensure_adds_tz_and_sorts(canon_df_one_nmi):
    out = ml.ingest.from_dataframe(canon_df_one_nmi, tz="Australia/Brisbane")
    out2 = ml.validate.ensure(out)
    assert out2.index.tz is not None
    assert out2.index.is_monotonic_increasing
