from __future__ import annotations
import pandas as pd
from typing import Optional, cast

from . import canon, exceptions


def assert_canon(df: pd.DataFrame) -> None:
    if df.index.name != canon.INDEX_NAME:
        raise exceptions.CanonError(f"Index must be '{canon.INDEX_NAME}'.")
    tz_index = cast(pd.DatetimeIndex, df.index)
    if tz_index.tz is None:
        raise exceptions.CanonError("Index must be tz-aware.")
    for col in canon.REQUIRED_COLS:
        if col not in df.columns:
            raise exceptions.CanonError(f"Missing required column '{col}'.")
    if not df.index.is_monotonic_increasing:
        raise exceptions.CanonError("Index must be sorted ascending.")
    if (df["kwh"] < 0).any():
        raise exceptions.CanonError("Negative kWh values detected; energy should be non-negative.")


def validate_nmi(df: pd.DataFrame, nmi: Optional[int] = None) -> pd.DataFrame:
    """
    Validate that DataFrame contains a single NMI, or filter to specified NMI.

    Args:
        df: DataFrame with 'nmi' column
        nmi: Optional NMI to filter to. If None and multiple NMIs exist, raises error.

    Returns:
        DataFrame filtered to single NMI

    Raises:
        ValueError: If multiple NMIs found without specifying which one to use,
                   or if specified NMI not found in data

    Example:
        >>> df = validate_nmi(multi_site_df, nmi=1234567890)
    """
    if "nmi" not in df.columns:
        raise ValueError("DataFrame does not have 'nmi' column")

    nmis = df["nmi"].unique()
    if len(nmis) > 1:
        if nmi is None:
            raise ValueError(
                f"Multiple NMIs detected: {', '.join(map(str, nmis))}. Please specify an NMI."
            )
        # Convert nmis to Python ints for comparison to avoid numpy type issues
        nmis_as_ints = [int(n) for n in nmis]
        if nmi not in nmis_as_ints:
            raise ValueError(
                f"Specified NMI {nmi} is not in the dataset. Available NMIs: {', '.join(map(str, nmis))}"
            )
        # Filter the dataframe by the specified NMI
        # Handle both string and int NMI columns by converting to int for comparison
        filtered = df[df["nmi"].astype(int) == nmi].copy()

        # Ensure the filtered dataframe is not empty
        if filtered.empty:
            raise ValueError(f"No data found for NMI {nmi} after filtering")

        return filtered
    return df
