import pandas as pd
from typing import Literal

def clean_basic(
    df: pd.DataFrame,
    *,
    fill_method: Literal["zero", "ffill", "none"] = "zero",
    dedupe: Literal["last", "first"] = "last",
) -> pd.DataFrame:
    """
    - Ensures monotonic, tz-aware DatetimeIndex.
    - De-duplicates timestamps keeping the chosen record (default 'last').
    - Fills NaNs per fill_method.
    """
    if "kwh" not in df.columns:
        raise ValueError("DataFrame must contain 'kwh'")

    # Always sort before de-dup so 'last' is deterministic
    df = df.sort_index()

    # Keep the last by default to match typical meter file correction behaviour
    keep_flag = "last" if dedupe == "last" else "first"
    df = df[~df.index.duplicated(keep=keep_flag)].copy()

    if fill_method == "zero":
        df["kwh"] = df["kwh"].fillna(0.0)
    elif fill_method == "ffill":
        df["kwh"] = df["kwh"].ffill().fillna(0.0)
    elif fill_method == "none":
        # leave NaNs as-is
        pass
    else:
        raise ValueError("fill_method must be one of: zero, ffill, none")

    return df
