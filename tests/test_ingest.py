import pandas as pd
import pytest
import meterdatalogic as ml

TZ = "Australia/Brisbane"


def test_from_dataframe_produces_canon(canon_df_one_nmi):
    out = ml.ingest.from_dataframe(canon_df_one_nmi, tz=TZ)
    ml.validate.assert_canon(out)
    assert out.index.tz is not None
    assert out.index.name == ml.canon.INDEX_NAME
    assert set(["nmi", "channel", "flow", "kwh", "cadence_min"]).issubset(out.columns)
    assert (out["kwh"] >= 0).all()


def test_from_dataframe_infers_cadence(canon_df_one_nmi):
    out = ml.ingest.from_dataframe(
        canon_df_one_nmi.drop(columns=[], errors="ignore"), tz=TZ
    )
    assert out["cadence_min"].iloc[0] == 30  # 30min cadence inferred


def test_from_dataframe_renames_columns_and_localizes():
    # messy column names + naive timestamp
    df = pd.DataFrame(
        {
            "timestamp": pd.date_range("2025-01-01", periods=4, freq="30min"),
            "nmi": ["N1"] * 4,
            "channel": ["E1"] * 4,
            "energy": [0.25, 0.25, 0.25, 0.25],
        }
    )
    out = ml.ingest.from_dataframe(df, tz=TZ)
    assert out.index.tz is not None
    assert "kwh" in out.columns
    assert out["kwh"].sum() == 1.0


def test_from_nem12_monkeypatched(monkeypatch):
    # Monkeypatch NEMFile.get_data_frame to avoid real IO
    class FauxNEMFile:
        def __init__(self, path):
            pass

        def get_data_frame(self):
            return pd.DataFrame(
                {
                    "nmi": ["N1"] * 4,
                    "suffix": ["E1", "E1", "B1", "B1"],
                    "serno": ["M1"] * 4,
                    "t_start": pd.date_range("2025-01-01", periods=4, freq="30min"),
                    "t_end": pd.date_range("2025-01-01 00:30", periods=4, freq="30min"),
                    "value": [0.25, 0.25, 0.10, 0.10],
                    "quality": ["A"] * 4,
                }
            )

    monkeypatch.setattr(ml.ingest, "NEMFile", FauxNEMFile)

    out = ml.ingest.from_nem12("fake.csv", tz=TZ)
    ml.validate.assert_canon(out)
    # kwh made positive; flow encodes direction
    assert (out["kwh"] >= 0).all()
    assert {"grid_import", "grid_export_solar"}.issubset(set(out["flow"].unique()))
