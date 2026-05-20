"""Tests for ingest.from_dataframe and ingest.from_nem12."""

import datetime as _dt
import polars as pl
import pytest

from meterdatalogic import ingest, validate, canon

TZ = "Australia/Brisbane"


def _ts_range(start: str, periods: int, freq_min: int, tz: str) -> pl.Series:
    base = _dt.datetime.fromisoformat(start)
    times = [base + _dt.timedelta(minutes=freq_min * i) for i in range(periods)]
    return pl.Series(times, dtype=pl.Datetime("us")).dt.replace_time_zone(tz)


def test_from_dataframe_produces_canon(canon_df_one_nmi):
    out = ingest.from_dataframe(canon_df_one_nmi, tz=TZ)
    validate.assert_canon(out)
    assert out["t_start"].dtype.time_zone is not None
    assert "t_start" in out.columns
    assert set(["nmi", "channel", "flow", "kwh", "cadence_min"]).issubset(set(out.columns))
    assert (out["kwh"] >= 0).all()


def test_from_dataframe_infers_cadence(canon_df_one_nmi):
    out = ingest.from_dataframe(canon_df_one_nmi, tz=TZ)
    assert out["cadence_min"][0] == 30


def test_from_dataframe_renames_columns_and_localizes():
    t_start = _ts_range("2025-01-01T00:00:00", 4, 30, TZ)
    df = pl.DataFrame(
        {
            "timestamp": t_start.dt.replace_time_zone(None),
            "nmi": pl.Series(["N1"] * 4),
            "channel": pl.Series(["E1"] * 4),
            "energy": pl.Series([0.25, 0.25, 0.25, 0.25], dtype=pl.Float64),
        }
    )
    out = ingest.from_dataframe(df, tz=TZ)
    assert out["t_start"].dtype.time_zone is not None
    assert "kwh" in out.columns
    assert abs(float(out["kwh"].sum()) - 1.0) < 1e-9


def test_from_nem12_monkeypatched(monkeypatch):
    """Monkeypatch NEMFile.get_data_frame_long for nemreader 1.0.0 API."""
    t_start = _ts_range("2025-01-01T00:00:00", 4, 30, TZ)

    class FauxNEMFile:
        def __init__(self, path):
            pass

        def get_data_frame_long(self):
            return pl.DataFrame(
                {
                    "nmi": pl.Series(["N1"] * 4),
                    "suffix": pl.Series(["E1", "E1", "B1", "B1"]),
                    "serno": pl.Series(["M1"] * 4),
                    "t_start": t_start.dt.replace_time_zone(None),
                    "t_end": t_start.dt.replace_time_zone(None),
                    "value": pl.Series([0.25, 0.25, 0.10, 0.10], dtype=pl.Float64),
                    "quality": pl.Series(["A"] * 4),
                    "evt_code": pl.Series([None] * 4, dtype=pl.String),
                    "evt_desc": pl.Series([None] * 4, dtype=pl.String),
                }
            )

    monkeypatch.setattr(ingest, "NEMFile", FauxNEMFile)

    out = ingest.from_nem12("fake.csv", tz=TZ)
    validate.assert_canon(out)
    assert (out["kwh"] >= 0).all()
    assert {"grid_import", "grid_export_solar"}.issubset(set(out["flow"].unique().to_list()))
