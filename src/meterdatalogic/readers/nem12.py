from __future__ import annotations
from typing import Literal
import pandas as pd
from nemreader import NEMFile

TZ = "Australia/Brisbane"

# Semantic mapping: keep simple for PoC
# - E1: general import
# - E2/E3...: controlled load import
# - B1: PV export
def _semantic_for_suffix(suffix: str, kwh: float) -> str:
    if suffix == "B1":
        return "grid_export_solar"
    if suffix == "E1":
        return "grid_import_general" if kwh >= 0 else "grid_export_unknown"
    if suffix.startswith("E"):  # E2, E3... treat as controlled load
        return "controlled_load_import"
    return "unknown"

def read_nem12_tidy(path: str) -> pd.DataFrame:
    """
    Parse a NEM12 file into a tidy, tz-aware DataFrame.

    Index: tz-aware DatetimeIndex (t_start)
    Columns: nmi, meter_number, channel, kwh, uom, quality, semantic_channel

    Conventions:
    - Customer import is positive kWh.
    - PV export (B1) is negative kWh.
    """
    m = NEMFile(path)
    df = m.get_data_frame()  # columns: nmi, suffix, serno, t_start, t_end, value, quality, evt_code, evt_desc

    if df.empty:
        return pd.DataFrame(columns=["nmi","meter_number","channel","kwh","uom","quality","semantic_channel"])

    # Localise to AEST (no DST for PoC)
    df["t_start"] = pd.to_datetime(df["t_start"]).dt.tz_localize(TZ)
    df = df.set_index("t_start").sort_index()

    # Normalise naming + units
    df = df.rename(columns={"suffix": "channel", "serno": "meter_number", "value": "kwh"})
    df["uom"] = "kWh"

    # Sign convention: make B1 negative (export), otherwise import positive
    is_b1 = df["channel"] == "B1"
    df.loc[is_b1, "kwh"] = -df.loc[is_b1, "kwh"].abs()
    df.loc[~is_b1, "kwh"] = df.loc[~is_b1, "kwh"].abs()

    # Semantic labels
    df["semantic_channel"] = [
        _semantic_for_suffix(suf, k) for suf, k in zip(df["channel"], df["kwh"])
    ]

    # Keep just what we need
    keep = ["nmi", "meter_number", "channel", "kwh", "uom", "quality", "semantic_channel"]
    return df[keep]

def select_series(df_tidy: pd.DataFrame, *, semantic: str | None = None, channel: str | None = None) -> pd.DataFrame:
    """
    Return a single-series interval frame (index, 'kwh').
    Prefers: semantic filter -> channel filter -> all (net).
    """
    if semantic:
        sub = df_tidy[df_tidy["semantic_channel"] == semantic]
    elif channel:
        sub = df_tidy[df_tidy["channel"] == channel]
    else:
        sub = df_tidy

    if sub.empty:
        return pd.DataFrame({"kwh": []})

    # Sum across channels per timestamp to produce a single series
    return sub.groupby(sub.index)["kwh"].sum().to_frame("kwh")
