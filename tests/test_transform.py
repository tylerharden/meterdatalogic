import meterdatalogic as ml
import pandas as pd

def test_groupby_day(canon_df_one_nmi):
    df = ml.ingest.from_dataframe(canon_df_one_nmi)
    day = ml.transform.groupby_day(df)
    assert "grid_import" in day.columns
    assert len(day.index) >= 1

def test_groupby_month(canon_df_one_nmi):
    df = ml.ingest.from_dataframe(canon_df_one_nmi)
    month = ml.transform.groupby_month(df)
    assert "month" in month.columns
    assert month.shape[0] >= 1

def test_profile24_shape(canon_df_one_nmi):
    df = ml.ingest.from_dataframe(canon_df_one_nmi)
    prof = ml.transform.profile24(df)
    # For 30-min cadence → 48 slots expected
    assert prof["slot"].nunique() == 48

def test_demand_window(canon_df_one_nmi):
    df = ml.ingest.from_dataframe(canon_df_one_nmi)
    demand = ml.transform.demand_window(df, start="16:00", end="21:00", days="MF")
    assert set(demand.columns) == {"month","demand_kw"}
    # Non-negative and finite
    assert (demand["demand_kw"] >= 0).all()

def test_resample_energy_no_warning(canon_df_one_nmi, recwarn):
    df = ml.ingest.from_dataframe(canon_df_one_nmi)
    _ = ml.transform.resample_energy(df, "1H")
    # ensure no FutureWarning from groupby.resample chain
    assert not any("FutureWarning" in str(w.message) for w in recwarn.list)
