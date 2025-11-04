import pandas as pd
from nemreader import NEMFile
import pytz
from datetime import datetime
from meterdatalogic.readers.nem12 import read_nem12_tidy, select_series

def test_read_nem12_tidy_shapes_and_signs(data_dir):
    # Minimal synthetic NEM12 via nemreader’s CSV schema is non-trivial to handcraft,
    sample = data_dir /  "unzipped" / "Example_NEM12_actual_interval.csv"
    df = read_nem12_tidy(sample)

    # basic columns
    for col in ["nmi","meter_number","channel","kwh","uom","quality","semantic_channel"]:
        assert col in df.columns

    # tz-aware index
    assert df.index.tz is not None

    # Signs: imports (E1/E2) should be >=0, exports (B1) should be <=0
    if (df["channel"] == "E1").any():
        assert (df.loc[df["channel"] == "E1", "kwh"] >= 0).all()
    if (df["channel"] == "B1").any():
        assert (df.loc[df["channel"] == "B1", "kwh"] <= 0).all()

    # select_series should produce a single 'kwh' column
    df_import = select_series(df, semantic="grid_import_general")
    assert list(df_import.columns) == ["kwh"]
