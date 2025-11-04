import pandas as pd
from meterdatalogic.readers.nem12 import read_nem12_tidy

def test_semantic_labels(data_dir):
    sample = data_dir / "unzipped/Example_NEM12_actual_interval.csv"
    tidy = read_nem12_tidy(str(sample))
    # If E1 present → must be labelled import
    if (tidy["channel"] == "E1").any():
        assert (tidy.loc[tidy["channel"]=="E1","semantic_channel"] == "grid_import_general").all()
    # If B1 present → must be labelled solar export
    if (tidy["channel"] == "B1").any():
        assert (tidy.loc[tidy["channel"]=="B1","semantic_channel"] == "grid_export_solar").all()
