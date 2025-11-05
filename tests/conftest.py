import pandas as pd
import pytest

TZ = "Australia/Brisbane"

@pytest.fixture
def halfhour_rng():
    return pd.date_range("2025-01-01", periods=48*7, freq="30min", tz=TZ)

@pytest.fixture
def canon_df_one_nmi(halfhour_rng):
    # Simple 7-day, one NMI, import (E1)
    df = pd.DataFrame({
        "t_start": halfhour_rng,
        "nmi": "Q1234567890",
        "channel": "E1",
        "kwh": 0.5
    }).set_index("t_start")
    return df

@pytest.fixture
def canon_df_mixed_flows(halfhour_rng):
    # Half import (E1), half export (B1) on interleaved slots
    df = pd.DataFrame({
        "t_start": halfhour_rng,
        "nmi": "Q1234567890",
        "channel": ["E1" if i % 2 == 0 else "B1" for i in range(len(halfhour_rng))],
        "kwh": 0.5
    }).set_index("t_start")
    return df

@pytest.fixture
def tou_bands_basic():
    return [
        {"name": "off", "start": "00:00", "end": "16:00"},
        {"name": "peak", "start": "16:00", "end": "21:00"},
        {"name": "shoulder", "start": "21:00", "end": "24:00"},
    ]
