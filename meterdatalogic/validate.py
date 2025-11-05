from __future__ import annotations
import pandas as pd
from . import canon, utils

class CanonError(Exception):
    pass

def assert_canon(df: pd.DataFrame) -> None:
    if df.index.name != canon.INDEX_NAME:
        raise CanonError(f"Index must be '{canon.INDEX_NAME}'.")
    if df.index.tz is None:
        raise CanonError("Index must be tz-aware.")
    for col in canon.REQUIRED_COLS:
        if col not in df.columns:
            raise CanonError(f"Missing required column '{col}'.")
    if not df.index.is_monotonic_increasing:
        raise CanonError("Index must be sorted ascending.")
    if (df["kwh"] < 0).any():
        raise CanonError("Negative kWh values detected; energy should be non-negative.")

def dedupe(df: pd.DataFrame) -> pd.DataFrame:
    return df[~df.index.duplicated(keep="first")].copy()

def ensure(df: pd.DataFrame, tz: str = canon.DEFAULT_TZ) -> pd.DataFrame:
    df = df.sort_index()
    df = utils.ensure_tz_aware_index(df, tz)
    assert_canon(df)
    return df
