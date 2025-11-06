import meterdatalogic as ml


def test_tou_bins_accepts_24_00(canon_df_one_nmi, tou_bands_basic):
    df = ml.ingest.from_dataframe(canon_df_one_nmi)
    out = ml.transform.tou_bins(df, tou_bands_basic)
    assert "month" in out.columns
    # Should have columns 'off', 'peak', 'shoulder' (even if some are zeros)
    for name in ["off", "peak", "shoulder"]:
        assert name in out.columns
