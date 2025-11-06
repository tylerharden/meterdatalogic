from __future__ import annotations
import pandas as pd
from . import canon, utils, exceptions
from typing import Optional


def assert_canon(df: pd.DataFrame) -> None:
    if df.index.name != canon.INDEX_NAME:
        raise exceptions.CanonError(f"Index must be '{canon.INDEX_NAME}'.")
    if df.index.tz is None:
        raise exceptions.CanonError("Index must be tz-aware.")
    for col in canon.REQUIRED_COLS:
        if col not in df.columns:
            raise exceptions.CanonError(f"Missing required column '{col}'.")
    if not df.index.is_monotonic_increasing:
        raise exceptions.CanonError("Index must be sorted ascending.")
    if (df["kwh"] < 0).any():
        raise exceptions.CanonError(
            "Negative kWh values detected; energy should be non-negative."
        )


def dedupe(df: pd.DataFrame) -> pd.DataFrame:
    return df[~df.index.duplicated(keep="first")].copy()


def ensure(df: pd.DataFrame, tz: str = canon.DEFAULT_TZ) -> pd.DataFrame:
    df = df.sort_index()
    df = utils._ensure_tz_aware_index(df, tz)
    assert_canon(df)
    return df


def validate_nmi(df: pd.DataFrame, nmi: Optional[int] = None) -> pd.DataFrame:
    """Validates that data contains a single NMI or raises an error."""
    nmis = df["nmi"].unique()
    if len(nmis) > 1:
        if nmi is None:
            raise ValueError(
                f"Multiple NMIs detected: {', '.join(map(str, nmis))}. Please specify an NMI."
            )
        if nmi not in nmis:
            raise ValueError(
                f"Specified NMI {nmi} is not in the dataset. Available NMIs: {', '.join(map(str, nmis))}"
            )
        # Filter the dataframe by the specified NMI
        df = df[df["nmi"] == nmi]
    return df
