import meterdatalogic as ml

def test_summary_payload_structure(canon_df_mixed_flows):
    df = ml.ingest.from_dataframe(canon_df_mixed_flows)
    payload = ml.summary.summarize(df)
    assert "meta" in payload and "energy" in payload and "profile24" in payload and "months" in payload
    assert payload["meta"]["cadence_min"] == 30
    assert payload["meta"]["nmis"] == 1
    # energy keys for flows present
    keys = payload["energy"].keys()
    assert "grid_import" in keys or "grid_export_solar" in keys
    # profile24 has slots
    assert len(payload["profile24"]) >= 1
