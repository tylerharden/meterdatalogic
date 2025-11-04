import pandas as pd
import numpy as np
from nemreader import NEMFile

from meterdatalogic.readers.nem12 import read_nem12_tidy, select_series

def test_nem12_parity_with_nemreader(data_dir):
    # Load example NEM12 (same as nemreader docs)
    sample = data_dir / "unzipped" / "Example_NEM12_actual_interval.csv"

    m = NEMFile(str(sample))
    raw = m.get_data_frame()  # oracle from nemreader

    # Our tidy normalised frame
    tidy = read_nem12_tidy(str(sample))

    # 1) Shape & required columns
    assert not tidy.empty
    for col in ["nmi", "meter_number", "channel", "kwh", "uom", "quality", "semantic_channel"]:
        assert col in tidy.columns
    assert tidy.index.tz is not None  # tz-aware index

    # 2) Timestamp coverage (align tz before comparing)
    raw_ts = pd.to_datetime(raw["t_start"]).dt.tz_localize("Australia/Brisbane")
    tidy_ts = tidy.index.tz_convert("Australia/Brisbane")
    assert set(raw_ts) == set(tidy_ts)

    # 3) Per-(timestamp,channel) magnitude parity (handle tz types before merge)
    raw_norm = raw.copy()
    raw_norm["t_start"] = pd.to_datetime(raw_norm["t_start"])  # naive

    tidy_norm = tidy.reset_index().copy()
    tidy_norm["t_start"] = tidy_norm["t_start"].dt.tz_localize(None)  # make naive to match raw

    merged = (
        tidy_norm[["t_start", "channel", "kwh"]]
        .rename(columns={"t_start": "ts", "kwh": "kwh_tidy"})
        .merge(
            raw_norm.rename(columns={"t_start": "ts", "suffix": "channel", "value": "kwh_raw"})[
                ["ts", "channel", "kwh_raw"]
            ],
            on=["ts", "channel"],
            how="inner",
        )
    )

    assert not merged.empty
    # Same magnitudes (sign differs for export)
    assert np.allclose(merged["kwh_tidy"].abs(), merged["kwh_raw"].abs(), atol=1e-9)

    # 4) Sign convention checks
    if (merged["channel"] == "B1").any():
        assert (merged.loc[merged["channel"] == "B1", "kwh_tidy"] <= 0).all()
    if (merged["channel"].str.startswith("E")).any():
        assert (merged.loc[merged["channel"].str.startswith("E"), "kwh_tidy"] >= 0).all()

    # 5) Semantic selection produces sensible slices
    df_import = select_series(tidy, semantic="grid_import_general")
    assert "kwh" in df_import.columns
    if (tidy["channel"] == "B1").any():
        df_export = select_series(tidy, semantic="grid_export_solar")
        assert (df_export["kwh"] <= 0).all()
