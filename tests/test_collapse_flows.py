import meterdatalogic as ml
from meterdatalogic.scenario import _collapse_flows

def test_collapse_flows_handles_filtered_frames(canon_df_mixed_flows):
    df = ml.ingest.from_dataframe(canon_df_mixed_flows)
    imp, exp = _collapse_flows(df)
    assert len(imp) == len(df.index)
    assert len(exp) == len(df.index)
    # export should be >= 0 and present when flows include 'grid_export_solar'
    assert (exp >= 0).all()
